import streamlit as st
import pandas as pd
from datetime import datetime
from src.database import get_connection

def mostrar_pantalla():
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
        st.info("Ingrese primero el número de lote para continuar.")
        return

    conn = get_connection()
    if not conn:
        st.error("No hay conexión a la base de datos.")
        return

    cursor = conn.cursor(dictionary=True)

    # VERIFICAR SESIÓN ACTIVA
    id_operario = st.session_state.usuario["id"]
    cursor.execute("""
        SELECT id_registro, lote_referencia, planchas_procesadas, hora_inicio
        FROM produccion 
        WHERE id_personal = %s AND estado = 'procesando'
        LIMIT 1
    """, (id_operario,))
    sesion_activa = cursor.fetchone()

    if sesion_activa:
        cursor.execute("SELECT lote_padre FROM ordenes WHERE lote_completo = %s", (sesion_activa['lote_referencia'],))
        lote_activo = cursor.fetchone()
        if lote_activo and lote_activo['lote_padre'] != lote_padre:
            st.error(f"⚠️ Tienes una producción activa en el lote **{lote_activo['lote_padre']}**.")
            conn.close()
            return

    # OBTENER MÁQUINAS Y MÁQUINA SUGERIDA
    cursor.execute("SELECT DISTINCT nombre_maquina FROM ordenes WHERE nombre_maquina IS NOT NULL ORDER BY nombre_maquina")
    lista_maquinas = ["Seleccione Máquina..."] + [row['nombre_maquina'] for row in cursor.fetchall()]
    
    # BUSCAR MÁQUINA ASIGNADA ORIGINALMENTE
    cursor.execute("SELECT nombre_maquina FROM ordenes WHERE lote_padre = %s LIMIT 1", (lote_padre,))
    maq_sugerida = cursor.fetchone()
    maq_info = maq_sugerida['nombre_maquina'] if maq_sugerida else "No asignada"

    # RESUMEN DE SALDOS
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

    meta, finalizado, en_proceso = int(resumen["meta"]), int(resumen["finalizado"]), int(resumen["en_proceso"])
    faltante = meta - (finalizado + en_proceso)

    st.markdown("### 📊 Estado de Producción")
    c1, c2, c3 = st.columns(3)
    c1.metric("✅ Finalizadas", f"{finalizado} / {meta}")
    c2.metric("⏳ En Proceso", en_proceso)
    c3.metric("📦 Pendientes", faltante)
    st.progress(finalizado / meta if meta > 0 else 0)

    # FORMULARIO
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
            maquina_real = col_f1.text_input("Máquina Utilizada:", value=mi_sesion['maquina_real'], disabled=True)
            planchas_proc = col_f1.number_input("Planchas:", value=int(mi_sesion['planchas_procesadas']), disabled=True)
            lote_fisico = col_f2.text_input("Lote de Planchas:", key="lote_fisico", placeholder="LP-XXXX")
            ancho_real = col_f2.number_input("Ancho Real Plancha (mm):", min_value=0, key="ancho_real")
            observaciones = col_f2.selectbox("Observación:", ["", "Descuadre", "Ondulado", "Quebrado", "Oxidado", "Rayado", "Rebaba", "Bajo espesor", "Daño de maquina"], key="observaciones")
        else:
            col_f1.info(f" **Máquina Sugerida:** {maq_info}")
            maquina_real = col_f1.selectbox("Máquina a utilizar hoy:", lista_maquinas, key="maquina_real")
            planchas_proc = col_f1.number_input("Planchas a Procesar:", min_value=1, max_value=max(faltante, 1), value=min(10, max(faltante, 1)), key="planchas_proc")
            st.info("💡 Revise el detalle abajo antes de Iniciar Producción.")

    # TABLA DE ÓRDENES
    cursor.execute("SELECT * FROM ordenes WHERE lote_padre = %s ORDER BY lote_completo", (lote_padre,))
    ordenes_originales = cursor.fetchall()

    if ordenes_originales:
        st.markdown("### 📋 Detalle de la Orden de Trabajo")
        if mi_sesion:
            st.session_state.cursor_temp = cursor
            mostrar_tabla_edicion(ordenes_originales, planchas_proc, lote_padre)
            btn_fin_disabled = not lote_fisico or ancho_real <= 0
            if st.button("FINALIZAR Y GUARDAR", use_container_width=True, disabled=btn_fin_disabled):
                finalizar_produccion(mi_sesion['id_registro'], lote_fisico, ancho_real, observaciones)
        else:
            # MOSTRAR TABLA COMPLETA ANTES DE INICIAR
            mostrar_tabla_lectura(ordenes_originales)
            if st.button("INICIAR PRODUCCIÓN", use_container_width=True, disabled=(maquina_real == "Seleccione Máquina...")):
                iniciar_produccion(lote_padre, planchas_proc, maquina_real)

    conn.close()

def mostrar_tabla_lectura(ordenes):
    """Muestra la tabla detallada antes de iniciar, similar al resumen final"""
    datos = []
    for o in ordenes:
        datos.append({
            'Lote': o['lote_completo'],
            'Cant x Plancha': o['cant'],
            'Ancho (Des.)': o['desarrollo'],
            'Flejes Pend.': o['can_total'],
            'Largo': o['largo'],
            'Peso Unit.': f"{o['peso_unitario']:.4f}",
            'Código SAP': o['cod_SAP'],
            'Código IBS': o['cod_IBS'],
            'Orden': o['orden']
        })
    df = pd.DataFrame(datos)
    st.dataframe(df, use_container_width=True, hide_index=True)

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
                'descrip_SAP': o['descrip_SAP'] or '',  
                'peso_unitario': float(o['peso_unitario'] or 0),
                'planchas_procesadas': planchas_proc,
                'cant': int(o['cant'] or 0),
                'can_total': int(o['can_total'] or 0),
                'orden': int(o['orden'] or 0),
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
                ancho_n = st.number_input("Ancho Fleje (mm):", min_value=0, value=orden['ancho_fleje'], key=f"a_{idx}")
                
                if ancho_n != orden['ancho_fleje']:
                    st.session_state.ordenes_editables[idx]['ancho_fleje'] = ancho_n
                    if ancho_n > 0 and cursor:
                        cursor.execute("""
                            SELECT peso_unitario, largo, espesor, descrip_SAP, cod_SAP, cod_IBS
                            FROM ordenes 
                            WHERE desarrollo = %s 
                            LIMIT 1
                        """, (ancho_n,))
                        ref = cursor.fetchone()
                        if ref:
                            st.session_state.ordenes_editables[idx].update({
                                'peso_unitario': float(ref['peso_unitario'] or 0),
                                'largo': int(ref['largo'] or 0),
                                'espesor': float(ref['espesor'] or 0),
                                'descrip_SAP': ref['descrip_SAP'] or '',
                                'cod_SAP': ref['cod_SAP'] or '',
                                'cod_IBS': ref['cod_IBS'] or ''
                            })
                            st.rerun()

            with col3:
                dest = st.selectbox("Destino:", ["PLEGADO", "VENTA"], index=0 if orden['destino'] == 'PLEGADO' else 1, key=f"d_{idx}")
                st.session_state.ordenes_editables[idx]['destino'] = dest
            
            if orden['es_nueva'] and col4.button("🗑️", key=f"del_{idx}"):
                filas_a_eliminar.append(idx)

            # Cálculo de peso
            peso_t = orden['peso_unitario'] * orden['cant_cortada']
            st.session_state.ordenes_editables[idx]['peso_total'] = peso_t
            
            # --- INFORMACIÓN VISUAL RESTAURADA ---
            # 1. Descripción SAP destacada
            st.markdown(f"📝 **Descripción:** {orden.get('descrip_SAP', 'N/A')}")
            
            # 2. Datos técnicos en una sola línea gris
            st.caption(
                f"Largo: {orden['largo']}mm | "
                f"SAP: {orden['cod_SAP']} | "
                f"IBS: {orden['cod_IBS']} | "
                f"Orden: {orden['orden']}"
            )

    for idx in sorted(filas_a_eliminar, reverse=True):
        st.session_state.ordenes_editables.pop(idx)
        st.rerun()
    
    if st.button("➕ Agregar Nueva Orden", use_container_width=True):
        agregar_nueva_orden(lote_padre, planchas_proc)
        st.rerun()
    
    mostrar_tabla_resumen()

def agregar_nueva_orden(lote_padre, planchas_proc):
    """Agrega orden nueva con flejes pendientes = 0"""
    ordenes = st.session_state.ordenes_editables
    nums = [int(o['lote_completo'].split('-')[-1]) for o in ordenes if '-' in o['lote_completo']]
    sig = max(nums) + 1 if nums else 1
    st.session_state.ordenes_editables.append({
        'lote_completo': f"{lote_padre}-{sig:02d}",
        'cant_cortada': 0,
        'ancho_fleje': 0,
        'destino': 'VENTA',
        'largo': 0,
        'espesor': 0,
        'cod_SAP': '',
        'cod_IBS': '',
        'descrip_SAP': '',
        'peso_unitario': 0,
        'planchas_procesadas': planchas_proc,
        'cant': 0,
        'can_total': 0,  # Flejes Pendientes = 0 en nueva orden
        'orden': 0,
        'es_nueva': True
    })

def mostrar_tabla_resumen():
    """Tabla con todos los campos solicitados"""
    st.markdown("#### 📊 Resumen de Órdenes")
    if st.session_state.ordenes_editables:
        datos = []
        for o in st.session_state.ordenes_editables:
            datos.append({
                'Lote': o['lote_completo'],
                'Cant Cortada': o['cant_cortada'],
                'Planchas Procesadas': o.get('planchas_procesadas', 0),
                'Ancho Fleje': o['ancho_fleje'],
                'Flejes Pend.': o.get('can_total', 0),
                'Destino': o['destino'],
                'Peso Unit.': f"{o['peso_unitario']:.4f}",
                'Peso Total': f"{o.get('peso_total', 0):.4f}",
                'Largo': o['largo'],
                'Cód. SAP': o['cod_SAP'],
                'Cód. IBS': o['cod_IBS'],
                'Orden': o['orden']
            })
        df = pd.DataFrame(datos)
        st.dataframe(df, use_container_width=True, hide_index=True)

def iniciar_produccion(lote_p, planchas, maq):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT lote_completo FROM ordenes WHERE lote_padre = %s LIMIT 1", (lote_p,))
        primero = cursor.fetchone()
        query = "INSERT INTO produccion (lote_referencia, id_personal, planchas_procesadas, maquina_real, hora_inicio, estado) VALUES (%s, %s, %s, %s, NOW(), 'procesando')"
        cursor.execute(query, (primero[0], st.session_state.usuario["id"], planchas, maq))
        conn.commit()
        st.success("Producción iniciada.")
        st.rerun()
    finally: 
        conn.close()

def finalizar_produccion(id_reg, lote_f, ancho_r, obs):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE produccion SET hora_fin = NOW(), estado = 'finalizado', lote_de_planchas = %s, ancho_real = %s, observacciones = %s WHERE id_registro = %s", (lote_f, ancho_r, obs, id_reg))
        
        # Guardar detalles
        for o in st.session_state.ordenes_editables:
            cursor.execute("""
                INSERT INTO detalles_produccion 
                (id_registro_produccion, lote_completo, cant_cortada_real, ancho_fleje_real, destino_real)
                VALUES (%s, %s, %s, %s, %s)
            """, (id_reg, o['lote_completo'], o['cant_cortada'], o['ancho_fleje'], o['destino']))
        
        conn.commit()
        
        # Limpiar
        if 'ordenes_editables' in st.session_state:
            del st.session_state['ordenes_editables']
        for key in ["input_lote", "lote_fisico", "ancho_real", "observaciones"]:
            if key in st.session_state:
                del st.session_state[key]
        
        st.success("Producción finalizada y guardada.")
        st.rerun()
    finally:
        conn.close()