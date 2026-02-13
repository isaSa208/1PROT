"""
=====================================================
MÓDULO: Registro de Producción con Órdenes Dinámicas
=====================================================
- Búsqueda automática de Peso Unitario por Desarrollo
- Agregar nuevas órdenes con correlativo automático
- Cálculo dinámico de pesos y validación de sesiones
Versión: 6.0 - Búsqueda Dinámica por Desarrollo
=====================================================
"""

import streamlit as st
import pandas as pd
from datetime import datetime
from src.database import get_connection

def mostrar_pantalla():
    """
    Pantalla principal de registro de producción
    """
    st.title("🛠️ Registro de Producción")

    # ========================================
    # PASO 1: INGRESAR LOTE
    # ========================================
    st.subheader("📦 1. Ingrese Lote")

    lote_padre = st.text_input(
        "LOTE (Padre):",
        key="input_lote",
        placeholder="Ej: 4019635"
    ).strip()

    if not lote_padre:
        st.info("👉 Ingrese primero el número de lote para continuar.")
        return

    # Conectar a base de datos
    conn = get_connection()
    if not conn:
        st.error("❌ No hay conexión a la base de datos.")
        return

    cursor = conn.cursor(dictionary=True)

    # ========================================
    # VERIFICAR SESIÓN ACTIVA DEL OPERARIO
    # ========================================
    id_operario = st.session_state.usuario["id"]
    
    cursor.execute("""
        SELECT id_registro, lote_referencia, planchas_procesadas, hora_inicio
        FROM produccion 
        WHERE id_personal = %s 
          AND estado = 'procesando'
        LIMIT 1
    """, (id_operario,))
    
    sesion_activa = cursor.fetchone()

    if sesion_activa:
        cursor.execute("""
            SELECT lote_padre 
            FROM ordenes 
            WHERE lote_completo = %s
        """, (sesion_activa['lote_referencia'],))
        
        lote_activo = cursor.fetchone()
        
        if lote_activo and lote_activo['lote_padre'] != lote_padre:
            otro_lote = lote_activo['lote_padre']
            st.error(
                f"⚠️ Ya tienes una producción activa en el lote **{otro_lote}**. "
                f"Debes finalizarla antes de iniciar otra."
            )
            conn.close()
            return

    # ========================================
    # OBTENER MÁQUINAS Y SALDOS
    # ========================================
    cursor.execute("SELECT DISTINCT nombre_maquina FROM ordenes WHERE nombre_maquina IS NOT NULL ORDER BY nombre_maquina")
    lista_maquinas = ["Seleccione Máquina..."] + [row['nombre_maquina'] for row in cursor.fetchall()]

    query_saldo = """
        SELECT 
            MAX(o.cantidad_planchas) as meta,
            (SELECT IFNULL(SUM(planchas_procesadas), 0) FROM produccion 
             WHERE lote_referencia IN (SELECT lote_completo FROM ordenes WHERE lote_padre = %s)
               AND estado = 'finalizado') as finalizado,
            (SELECT IFNULL(SUM(planchas_procesadas), 0) FROM produccion 
             WHERE lote_referencia IN (SELECT lote_completo FROM ordenes WHERE lote_padre = %s)
               AND estado = 'procesando') as en_proceso
        FROM ordenes o WHERE o.lote_padre = %s
    """
    cursor.execute(query_saldo, (lote_padre, lote_padre, lote_padre))
    resumen = cursor.fetchone()

    if not resumen or not resumen["meta"]:
        st.warning("⚠️ No se encontraron órdenes para este lote.")
        conn.close()
        return

    meta = int(resumen["meta"])
    finalizado = int(resumen["finalizado"] or 0)
    en_proceso = int(resumen["en_proceso"] or 0)
    faltante = meta - (finalizado + en_proceso)

    # Panel de métricas
    st.markdown("### 📊 Estado de Producción")
    c1, c2, c3 = st.columns(3)
    c1.metric("✅ Finalizadas", f"{finalizado} / {meta}")
    c2.metric("⏳ En Proceso", en_proceso)
    c3.metric("📦 Pendientes", faltante)
    st.progress(finalizado / meta if meta > 0 else 0)

    if faltante <= 0 and en_proceso == 0:
        st.success(f"✅ Producción completada.")
        conn.close()
        return

    # ========================================
    # FORMULARIO Y TABLA EDITABLE
    # ========================================
    st.subheader("⚙️ 2. Registrar Producción")

    cursor.execute("""
        SELECT id_registro, planchas_procesadas, maquina_real, hora_inicio
        FROM produccion 
        WHERE id_personal = %s AND lote_referencia IN 
              (SELECT lote_completo FROM ordenes WHERE lote_padre = %s)
          AND estado = 'procesando' LIMIT 1
    """, (id_operario, lote_padre))
    mi_sesion = cursor.fetchone()

    with st.container(border=True):
        col_f1, col_f2 = st.columns(2)
        if mi_sesion:
            maquina_real = col_f1.text_input("Máquina:", value=mi_sesion['maquina_real'], disabled=True)
            planchas_proc = col_f1.number_input("Planchas:", value=int(mi_sesion['planchas_procesadas']), disabled=True)
            lote_fisico = col_f2.text_input("Lote de Planchas:", key="lote_fisico", placeholder="LP-XXXX")
            ancho_real = col_f2.number_input("Ancho Real Plancha (mm):", min_value=0, key="ancho_real")
            observaciones = col_f2.selectbox("Observación:", ["", "Descuadre", "Ondulado", "Quebrado", "Oxidado", "Rayado", "Rebaba", "Bajo espesor", "Daño de maquina"], key="observaciones")
        else:
            maquina_real = col_f1.selectbox("Máquina de Proceso:", lista_maquinas, key="maquina_real")
            planchas_proc = col_f1.number_input("Planchas a Procesar:", min_value=1, max_value=max(faltante, 1), value=min(10, max(faltante, 1)), key="planchas_proc")
            st.info("💡 Inicie producción para habilitar los campos de cierre.")

    # Cargar órdenes para la tabla
    cursor.execute("SELECT * FROM ordenes WHERE lote_padre = %s ORDER BY lote_completo", (lote_padre,))
    ordenes_originales = cursor.fetchall()

    if ordenes_originales:
        st.markdown("### 📋 Detalle del Corte")
        if mi_sesion:
            st.session_state.cursor_temp = cursor # Guardar para búsqueda dinámica
            mostrar_tabla_edicion(ordenes_originales, planchas_proc, lote_padre)
            
            btn_fin_disabled = not lote_fisico or ancho_real <= 0
            if st.button("✅ FINALIZAR Y GUARDAR", use_container_width=True, disabled=btn_fin_disabled):
                finalizar_produccion(mi_sesion['id_registro'], lote_fisico, ancho_real, observaciones)
        else:
            mostrar_tabla_lectura(ordenes_originales)
            if st.button("🚀 INICIAR PRODUCCIÓN", use_container_width=True, disabled=(maquina_real == "Seleccione Máquina...")):
                iniciar_produccion(lote_padre, planchas_proc, maquina_real)

    conn.close()

def mostrar_tabla_lectura(ordenes):
    df = pd.DataFrame(ordenes)[["lote_completo", "cantidad_planchas", "largo", "desarrollo", "cod_SAP", "orden"]]
    st.table(df.rename(columns={"lote_completo": "Lote", "desarrollo": "Ancho (Des.)", "cantidad_planchas": "Cant"}))

def mostrar_tabla_edicion(ordenes_originales, planchas_proc, lote_padre):
    cursor = st.session_state.get('cursor_temp')
    
    if 'ordenes_editables' not in st.session_state:
        st.session_state.ordenes_editables = []
        for o in ordenes_originales:
            st.session_state.ordenes_editables.append({
                'lote_completo': o['lote_completo'],
                'cant_cortada': int(o['cant'] * planchas_proc),
                'ancho_fleje': int(o['desarrollo'] or 0),
                'destino': o['destino'] or 'VENTA',
                'largo': int(o['largo'] or 0),
                'espesor': float(o['espesor'] or 0),
                'cod_SAP': o['cod_SAP'] or '',
                'cod_IBS': o['cod_IBS'] or '',
                'peso_unitario': float(o['peso_unitario'] or 0),
                'es_nueva': False
            })

    filas_a_eliminar = []
    for idx, orden in enumerate(st.session_state.ordenes_editables):
        with st.expander(f"📦 {orden['lote_completo']} {'[NUEVA]' if orden['es_nueva'] else ''}", expanded=True):
            col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
            
            with col1:
                cant = st.number_input("Cant. Cortada:", min_value=0, value=orden['cant_cortada'], key=f"c_{idx}")
                st.session_state.ordenes_editables[idx]['cant_cortada'] = cant
            
            with col2:
                ancho_n = st.number_input("Ancho (Desarrollo):", min_value=0, value=orden['ancho_fleje'], key=f"a_{idx}")
                # BÚSQUEDA DINÁMICA DE PESO POR DESARROLLO
                if ancho_n != orden['ancho_fleje']:
                    st.session_state.ordenes_editables[idx]['ancho_fleje'] = ancho_n
                    if ancho_n > 0 and cursor:
                        cursor.execute("SELECT peso_unitario, cod_SAP, cod_IBS, largo, espesor FROM ordenes WHERE desarrollo = %s LIMIT 1", (ancho_n,))
                        ref = cursor.fetchone()
                        if ref:
                            st.session_state.ordenes_editables[idx].update({
                                'peso_unitario': float(ref['peso_unitario'] or 0),
                                'cod_SAP': ref['cod_SAP'], 'cod_IBS': ref['cod_IBS'],
                                'largo': int(ref['largo'] or 0), 'espesor': float(ref['espesor'] or 0)
                            })
                            st.rerun()
                        else:
                            st.warning("⚠️ Ancho no encontrado en base de datos.")

            with col3:
                dest = st.selectbox("Destino:", ["PLEGADO", "VENTA"], index=0 if orden['destino'] == 'PLEGADO' else 1, key=f"d_{idx}")
                st.session_state.ordenes_editables[idx]['destino'] = dest
            
            if orden['es_nueva'] and col4.button("🗑️", key=f"del_{idx}"):
                filas_a_eliminar.append(idx)

            peso_t = orden['peso_unitario'] * orden['cant_cortada']
            st.session_state.ordenes_editables[idx]['peso_total'] = peso_t
            st.caption(f"⚖️ Peso Unit: **{orden['peso_unitario']:.4f}** | SAP: **{orden['cod_SAP']}** | Largo: **{orden['largo']}mm**")

    for idx in sorted(filas_a_eliminar, reverse=True):
        st.session_state.ordenes_editables.pop(idx)
        st.rerun()
    
    if st.button("➕ Agregar Nueva Orden", use_container_width=True):
        agregar_nueva_orden(lote_padre)
        st.rerun()
    
    mostrar_tabla_resumen()

def agregar_nueva_orden(lote_padre):
    ordenes = st.session_state.ordenes_editables
    nums = [int(o['lote_completo'].split('-')[-1]) for o in ordenes if '-' in o['lote_completo']]
    sig = max(nums) + 1 if nums else 1
    st.session_state.ordenes_editables.append({
        'lote_completo': f"{lote_padre}-{sig:02d}", 'cant_cortada': 0, 'ancho_fleje': 0,
        'destino': 'VENTA', 'largo': 0, 'espesor': 0, 'cod_SAP': '', 'cod_IBS': '',
        'peso_unitario': 0, 'es_nueva': True
    })

def mostrar_tabla_resumen():
    st.markdown("#### 📊 Resumen de Órdenes")
    if st.session_state.ordenes_editables:
        df = pd.DataFrame(st.session_state.ordenes_editables)
        st.dataframe(df[["lote_completo", "cant_cortada", "ancho_fleje", "peso_unitario", "peso_total", "cod_SAP"]], use_container_width=True, hide_index=True)

def iniciar_produccion(lote_p, planchas, maq):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT lote_completo FROM ordenes WHERE lote_padre = %s LIMIT 1", (lote_p,))
        primero = cursor.fetchone()
        query = "INSERT INTO produccion (lote_referencia, id_personal, planchas_procesadas, maquina_real, hora_inicio, estado) VALUES (%s, %s, %s, %s, NOW(), 'procesando')"
        cursor.execute(query, (primero[0], st.session_state.usuario["id"], planchas, maq))
        conn.commit()
        st.rerun()
    finally: conn.close()

def finalizar_produccion(id_reg, lote_f, ancho_r, obs):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE produccion SET hora_fin = NOW(), estado = 'finalizado', lote_de_planchas = %s, ancho_real = %s, observacciones = %s WHERE id_registro = %s", (lote_f, ancho_r, obs, id_reg))
        for o in st.session_state.ordenes_editables:
            cursor.execute("INSERT INTO detalles_produccion (id_registro_produccion, lote_completo, cant_cortada_real, ancho_fleje_real, destino_real) VALUES (%s, %s, %s, %s, %s)", (id_reg, o['lote_completo'], o['cant_cortada'], o['ancho_fleje'], o['destino']))
        conn.commit()
        if 'ordenes_editables' in st.session_state: del st.session_state['ordenes_editables']
        st.success("✅ Guardado.")
        st.rerun()
    finally: conn.close()