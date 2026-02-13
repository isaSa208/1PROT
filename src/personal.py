"""
=====================================================
MÓDULO: Registro de Producción con Órdenes Dinámicas
=====================================================
- Agregar nuevas órdenes con correlativo automático
- Cálculo automático de pesos
- Mostrar descripción SAP al hacer clic
Versión: 5.0 - Completo
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

    # Si hay sesión activa, verificar si es de OTRO lote
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
    # OBTENER MÁQUINAS DISPONIBLES
    # ========================================
    cursor.execute("""
        SELECT DISTINCT nombre_maquina 
        FROM ordenes 
        WHERE nombre_maquina IS NOT NULL
        ORDER BY nombre_maquina
    """)
    
    lista_maquinas = ["Seleccione Máquina..."] + \
        [row['nombre_maquina'] for row in cursor.fetchall() if row['nombre_maquina']]

    # ========================================
    # CALCULAR ESTADO DE PRODUCCIÓN
    # ========================================
    query_saldo = """
        SELECT 
            MAX(o.cantidad_planchas) as meta,
            
            (SELECT IFNULL(SUM(planchas_procesadas), 0) 
             FROM produccion 
             WHERE lote_referencia IN 
                   (SELECT lote_completo FROM ordenes WHERE lote_padre = %s)
               AND estado = 'finalizado') as finalizado,
            
            (SELECT IFNULL(SUM(planchas_procesadas), 0) 
             FROM produccion 
             WHERE lote_referencia IN 
                   (SELECT lote_completo FROM ordenes WHERE lote_padre = %s)
               AND estado = 'procesando') as en_proceso
               
        FROM ordenes o 
        WHERE o.lote_padre = %s
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
    total_ocupado = finalizado + en_proceso
    faltante = meta - total_ocupado

    # ========================================
    # PANEL DE ESTADO EN TIEMPO REAL
    # ========================================
    st.markdown("### 📊 Estado de Producción")

    col_estado1, col_estado2, col_estado3 = st.columns(3)
    
    with col_estado1:
        st.metric(
            label="✅ Finalizadas",
            value=f"{finalizado} / {meta}",
            delta=f"{(finalizado/meta*100):.1f}%" if meta > 0 else "0%"
        )
    
    with col_estado2:
        st.metric(
            label="⏳ En Proceso",
            value=en_proceso,
            delta="Activo" if en_proceso > 0 else None
        )
    
    with col_estado3:
        st.metric(
            label="📦 Pendientes",
            value=faltante,
            delta=f"{(faltante/meta*100):.1f}%" if meta > 0 else "0%"
        )

    if meta > 0:
        progreso = finalizado / meta
        st.progress(progreso)

    # Mostrar quién está trabajando
    if en_proceso > 0:
        cursor.execute("""
            SELECT 
                p.planchas_procesadas,
                p.hora_inicio,
                TIMESTAMPDIFF(MINUTE, p.hora_inicio, NOW()) as minutos,
                u.nombre_usuario as operario
            FROM produccion p
            INNER JOIN usuarios u ON p.id_personal = u.id
            WHERE p.lote_referencia IN 
                  (SELECT lote_completo FROM ordenes WHERE lote_padre = %s)
              AND p.estado = 'procesando'
        """, (lote_padre,))
        
        trabajadores = cursor.fetchall()
        
        if trabajadores:
            st.info("👷 **Personal trabajando ahora:**")
            for t in trabajadores:
                st.write(
                    f"• **{t['operario']}** - {t['planchas_procesadas']} planchas "
                    f"(Iniciado hace {t['minutos']} min)"
                )

    # Bloquear si ya está completo
    if faltante <= 0 and en_proceso == 0:
        st.success(
            f"✅ Producción completada: **{meta}** de **{meta}** planchas procesadas."
        )
        conn.close()
        return

    # ========================================
    # FORMULARIO DE PRODUCCIÓN
    # ========================================
    st.subheader("⚙️ 2. Registrar Producción")

    # Verificar si ESTE operario tiene sesión activa en ESTE lote
    cursor.execute("""
        SELECT id_registro, planchas_procesadas, maquina_real, hora_inicio
        FROM produccion 
        WHERE id_personal = %s 
          AND lote_referencia IN 
              (SELECT lote_completo FROM ordenes WHERE lote_padre = %s)
          AND estado = 'procesando'
        LIMIT 1
    """, (id_operario, lote_padre))
    
    mi_sesion = cursor.fetchone()

    with st.container(border=True):
        
        col1, col2 = st.columns(2)

        with col1:
            # MÁQUINA (bloqueada si ya inició)
            if mi_sesion:
                st.text_input(
                    "Máquina de Proceso:",
                    value=mi_sesion['maquina_real'] or "N/A",
                    disabled=True,
                    key="maquina_bloqueada"
                )
                maquina_real = mi_sesion['maquina_real']
            else:
                maquina_real = st.selectbox(
                    "Máquina de Proceso:",
                    lista_maquinas,
                    key="maquina_real"
                )

            # PLANCHAS (bloqueadas si ya inició)
            if mi_sesion:
                st.number_input(
                    "Planchas a Procesar:",
                    value=int(mi_sesion['planchas_procesadas']),
                    disabled=True,
                    key="planchas_bloqueadas"
                )
                planchas_proc = int(mi_sesion['planchas_procesadas'])
            else:
                planchas_proc = st.number_input(
                    "Planchas a Procesar:",
                    min_value=1,
                    max_value=max(faltante, 1),
                    step=1,
                    value=min(10, max(faltante, 1)),
                    key="planchas_proc"
                )

        with col2:
            # Campos solo habilitados al finalizar
            lote_fisico = st.text_input(
                "Lote de Planchas:",
                disabled=not mi_sesion,
                key="lote_fisico",
                help="Se habilita al finalizar" if not mi_sesion else None,
                placeholder="Ej: LP-001"
            )

            ancho_real = st.number_input(
                "Ancho Real Plancha (mm):",
                min_value=0,
                disabled=not mi_sesion,
                key="ancho_real",
                help="Se habilita al finalizar" if not mi_sesion else None
            )

            observaciones = st.selectbox(
                "Observación:",
                [
                    "",
                    "Descuadre", "Ondulado", "Quebrado",
                    "Oxidado", "Rayado", "Rebaba",
                    "Bajo espesor", "Daño de maquina"
                ],
                disabled=not mi_sesion,
                key="observaciones",
                help="Se habilita al finalizar" if not mi_sesion else None
            )

        # CRONÓMETRO
        if mi_sesion:
            tiempo_transcurrido = datetime.now() - mi_sesion['hora_inicio']
            minutos_totales = int(tiempo_transcurrido.total_seconds() / 60)
            horas = minutos_totales // 60
            mins = minutos_totales % 60
            
            if horas > 0:
                tiempo_str = f"{horas}h {mins}min"
            else:
                tiempo_str = f"{mins} minutos"
                
            st.info(
                f"⏱️ **Tiempo transcurrido:** {tiempo_str} "
                f"(Inicio: {mi_sesion['hora_inicio'].strftime('%H:%M:%S')})"
            )

    # ========================================
    # TABLA DETALLE
    # ========================================
    cursor.execute("SELECT * FROM ordenes WHERE lote_padre = %s ORDER BY lote_completo", (lote_padre,))
    ordenes_originales = cursor.fetchall()

    if ordenes_originales:
        st.markdown("### 📋 Detalle del Corte")
        
        if mi_sesion:
            # ========================================
            # MODO EDICIÓN (Ya inició producción)
            # ========================================
            # Guardar cursor en session_state para usar en callbacks
            st.session_state.cursor_temp = cursor
            
            mostrar_tabla_edicion(ordenes_originales, planchas_proc, lote_padre)
            
            # BOTÓN FINALIZAR
            # Validar que estén llenos lote_fisico y ancho_real
            boton_finalizar_deshabilitado = (
                not lote_fisico or lote_fisico.strip() == "" or
                ancho_real <= 0
            )
            
            if st.button(
                "✅ FINALIZAR Y GUARDAR",
                use_container_width=True,
                key="btn_finalizar",
                disabled=boton_finalizar_deshabilitado,
                help="Debe llenar 'Lote de Planchas' y 'Ancho Real' para continuar" if boton_finalizar_deshabilitado else None
            ):
                if 'procesando_finalizacion' not in st.session_state:
                    st.session_state.procesando_finalizacion = True
                    
                    finalizar_produccion(
                        mi_sesion['id_registro'],
                        lote_fisico,
                        ancho_real,
                        observaciones
                    )
        else:
            # ========================================
            # MODO LECTURA (No ha iniciado)
            # ========================================
            mostrar_tabla_lectura(ordenes_originales, planchas_proc)
            
            # BOTÓN INICIAR
            boton_deshabilitado = (
                maquina_real == "Seleccione Máquina..." or
                planchas_proc <= 0 or
                faltante <= 0
            )

            if st.button(
                "🚀 INICIAR PRODUCCIÓN",
                use_container_width=True,
                disabled=boton_deshabilitado,
                key="btn_iniciar"
            ):
                if 'procesando_inicio' not in st.session_state:
                    st.session_state.procesando_inicio = True
                    
                    iniciar_produccion(
                        lote_padre,
                        planchas_proc,
                        maquina_real
                    )

    conn.close()


# ============================================================
# FUNCIÓN: MOSTRAR TABLA EN MODO LECTURA
# ============================================================
def mostrar_tabla_lectura(ordenes, planchas_proc):
    """
    Muestra tabla antes de iniciar con: Lote, Cant Plancha, Largo, Cód SAP, Cód IBS, Orden
    """
    df = pd.DataFrame(ordenes)
    
    columnas_ver = {
        "lote_completo": "Lote",
        "cantidad_planchas": "Cant Plancha",
        "largo": "Largo",
        "cod_SAP": "Código SAP",
        "cod_IBS": "Código IBS",
        "orden": "Orden"
    }
    
    df_mostrar = df[list(columnas_ver.keys())].copy()
    
    # Sin decimales
    for col in ["cantidad_planchas", "largo", "orden"]:
        if col in df_mostrar.columns:
            df_mostrar[col] = df_mostrar[col].fillna(0).astype(int)
    
    st.table(df_mostrar.rename(columns=columnas_ver))


# ============================================================
# FUNCIÓN: MOSTRAR TABLA EN MODO EDICIÓN
# ============================================================
def mostrar_tabla_edicion(ordenes_originales, planchas_proc, lote_padre):
    """
    Muestra tabla editable con órdenes existentes + nuevas agregadas
    """
    # Obtener cursor de session_state
    cursor = st.session_state.get('cursor_temp')
    # Inicializar órdenes editables en session_state
    if 'ordenes_editables' not in st.session_state:
        st.session_state.ordenes_editables = []
        for orden in ordenes_originales:
            st.session_state.ordenes_editables.append({
                'lote_completo': orden['lote_completo'],
                'cant_cortada': int(orden['cant'] * planchas_proc),
                'ancho_fleje': int(orden['desarrollo'] or 0),
                'destino': orden['destino'] or 'VENTA',
                'largo': int(orden['largo'] or 0),
                'espesor': float(orden['espesor'] or 0),
                'cod_SAP': orden['cod_SAP'] or '',
                'cod_IBS': orden['cod_IBS'] or '',
                'orden': int(orden['orden'] or 0),
                'descrip_SAP': orden['descrip_SAP'] or '',
                'peso_unitario_base': float(orden['peso_unitario'] or 0),
                'cant': int(orden['cant'] or 0),
                'can_total': int(orden['can_total'] or 0),  # Flejes Pendientes
                'planchas_cortadas': planchas_proc,
                'es_nueva': False
            })
    
    # Mostrar cada orden
    filas_a_eliminar = []
    
    for idx, orden_edit in enumerate(st.session_state.ordenes_editables):
        with st.expander(
            f"📦 {orden_edit['lote_completo']}" + 
            (" [NUEVA]" if orden_edit.get('es_nueva') else ""),
            expanded=True
        ):
            # Botón para ver descripción SAP
            if st.button(f"ℹ️ Ver Descripción", key=f"desc_{idx}"):
                st.info(f"**{orden_edit['cod_SAP']}**: {orden_edit['descrip_SAP']}")
            
            col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
            
            with col1:
                cant = st.number_input(
                    "Cant. Cortada:",
                    min_value=0,
                    value=orden_edit['cant_cortada'],
                    key=f"cant_{idx}"
                )
                st.session_state.ordenes_editables[idx]['cant_cortada'] = cant
            
            with col2:
                ancho = st.number_input(
                    "Ancho Fleje (mm):",
                    min_value=0,
                    value=orden_edit['ancho_fleje'],
                    key=f"ancho_{idx}"
                )
                
                # Actualizar ancho
                st.session_state.ordenes_editables[idx]['ancho_fleje'] = ancho
                
                # Si es nueva orden, buscar datos automáticamente cuando hay ancho
                if orden_edit.get('es_nueva') and ancho > 0 and cursor:
                    # Solo buscar si no tiene peso_unitario o el ancho cambió
                    peso_actual = orden_edit.get('peso_unitario_base', 0)
                    
                    if peso_actual == 0 or ancho != orden_edit.get('ancho_fleje_anterior', 0):
                        cursor.execute("""
                            SELECT peso_unitario, largo, espesor, can_total, cod_SAP, cod_IBS
                            FROM ordenes 
                            WHERE desarrollo = %s 
                            LIMIT 1
                        """, (ancho,))
                        
                        peso_ref = cursor.fetchone()
                        if peso_ref:
                            st.session_state.ordenes_editables[idx]['peso_unitario_base'] = float(peso_ref['peso_unitario'] or 0)
                            st.session_state.ordenes_editables[idx]['largo'] = int(peso_ref['largo'] or 0)
                            st.session_state.ordenes_editables[idx]['espesor'] = float(peso_ref['espesor'] or 0)
                            st.session_state.ordenes_editables[idx]['can_total'] = int(peso_ref['can_total'] or 0)
                            st.session_state.ordenes_editables[idx]['cod_SAP'] = peso_ref['cod_SAP'] or ''
                            st.session_state.ordenes_editables[idx]['cod_IBS'] = peso_ref['cod_IBS'] or ''
                            st.session_state.ordenes_editables[idx]['ancho_fleje_anterior'] = ancho
            
            with col3:
                destino = st.selectbox(
                    "Destino:",
                    ["PLEGADO", "VENTA"],
                    index=0 if orden_edit['destino'] == 'PLEGADO' else 1,
                    key=f"dest_{idx}"
                )
                st.session_state.ordenes_editables[idx]['destino'] = destino
            
            with col4:
                if orden_edit.get('es_nueva'):
                    if st.button("🗑️", key=f"del_{idx}"):
                        filas_a_eliminar.append(idx)
            
            # Calcular pesos usando el peso_unitario de la BD
            peso_unit = orden_edit.get('peso_unitario_base', 0)
            peso_total = peso_unit * cant
            
            # Guardar sin mostrar
            st.session_state.ordenes_editables[idx]['peso_unitario'] = peso_unit
            st.session_state.ordenes_editables[idx]['peso_total'] = peso_total
            
            # Mostrar info adicional
            col_info1, col_info2, col_info3 = st.columns(3)
            with col_info1:
                st.caption(f"📏 Largo: {orden_edit['largo']} mm")
            with col_info2:
                st.caption(f"🏷️ SAP: {orden_edit['cod_SAP']}")
            with col_info3:
                st.caption(f"📊 IBS: {orden_edit['cod_IBS']}")
    
    # Eliminar filas marcadas
    for idx in sorted(filas_a_eliminar, reverse=True):
        st.session_state.ordenes_editables.pop(idx)
        st.rerun()
    
    # Botón para agregar nueva orden
    if st.button("➕ Agregar Nueva Orden", use_container_width=True):
        agregar_nueva_orden(lote_padre)
        st.rerun()
    
    # Mostrar tabla resumen
    mostrar_tabla_resumen()


# ============================================================
# FUNCIÓN: AGREGAR NUEVA ORDEN
# ============================================================
def agregar_nueva_orden(lote_padre):
    """
    Agrega una nueva orden con correlativo automático
    planchas_cortadas = mismo valor que las otras órdenes
    """
    cursor = st.session_state.get('cursor_temp')
    # Obtener planchas_cortadas de la primera orden
    planchas_cortadas_ref = 0
    if st.session_state.ordenes_editables:
        planchas_cortadas_ref = st.session_state.ordenes_editables[0].get('planchas_cortadas', 0)
    
    # Obtener el último correlativo
    ordenes_actuales = st.session_state.ordenes_editables
    
    if ordenes_actuales:
        numeros = []
        for orden in ordenes_actuales:
            lote = orden['lote_completo']
            if '-' in lote:
                try:
                    num = int(lote.split('-')[-1])
                    numeros.append(num)
                except:
                    pass
        
        if numeros:
            siguiente_num = max(numeros) + 1
        else:
            siguiente_num = 1
    else:
        siguiente_num = 1
    
    # Generar nuevo lote
    nuevo_lote = f"{lote_padre}-{siguiente_num:02d}"
    
    # Agregar nueva orden CON CAMPOS EN BLANCO
    st.session_state.ordenes_editables.append({
        'lote_completo': nuevo_lote,
        'cant_cortada': 0,
        'ancho_fleje': 0,
        'destino': 'VENTA',
        'largo': 0,
        'espesor': 0,
        'cod_SAP': '',
        'cod_IBS': '',
        'orden': 0,
        'descrip_SAP': '',
        'peso_unitario_base': 0,
        'cant': 0,
        'can_total': 0,
        'planchas_cortadas': planchas_cortadas_ref,  # Copia de las otras
        'es_nueva': True
    })


# ============================================================
# FUNCIÓN: MOSTRAR TABLA RESUMEN
# ============================================================
def mostrar_tabla_resumen():
    """
    Muestra tabla resumen con todos los campos
    Flejes Pend. = can_total (de la BD)
    """
    st.markdown("#### 📊 Resumen de Órdenes")
    
    if not st.session_state.ordenes_editables:
        return
    
    datos = []
    for orden in st.session_state.ordenes_editables:
        # Flejes Pendientes = can_total
        flejes_pend = orden.get('can_total', 0)
        
        datos.append({
            'Lote': orden['lote_completo'],
            'Cant Cortada': orden['cant_cortada'],
            'Planchas Cortadas': orden.get('planchas_cortadas', 0),
            'Ancho Fleje': orden['ancho_fleje'],
            'Flejes Pend.': flejes_pend,
            'Destino': orden['destino'],
            'Peso Unit.': f"{orden.get('peso_unitario', 0):.4f}",
            'Peso Total': f"{orden.get('peso_total', 0):.4f}",
            'Largo': orden['largo'],
            'Cód. SAP': orden['cod_SAP'],
            'Cód. IBS': orden['cod_IBS'],
            'Orden': orden['orden']
        })
    
    df = pd.DataFrame(datos)
    st.dataframe(df, use_container_width=True, hide_index=True)


# ============================================================
# FUNCIÓN: CALCULAR PESO UNITARIO
# ============================================================
def calcular_peso_unitario(ancho_fleje, largo, espesor):
    """
    Calcula peso unitario: (ancho * largo * espesor * 7.85) / 1000000
    """
    try:
        if ancho_fleje > 0 and largo > 0 and espesor > 0:
            densidad = 7.85  # kg/dm³ (acero)
            peso = (ancho_fleje * largo * espesor * densidad) / 1000000
            return round(peso, 4)
        return 0
    except:
        return 0


# ============================================================
# FUNCIÓN: INICIAR PRODUCCIÓN
# ============================================================
def iniciar_produccion(lote_padre, planchas, maq_r):
    """
    Inserta UN SOLO registro
    """
    conn = get_connection()
    if not conn:
        st.error("❌ Error de conexión.")
        if 'procesando_inicio' in st.session_state:
            del st.session_state.procesando_inicio
        return

    try:
        cursor = conn.cursor(dictionary=True)
        id_op = st.session_state.usuario["id"]
        hora_actual = datetime.now()

        # Verificar sesión activa
        cursor.execute("""
            SELECT COUNT(*) as total
            FROM produccion 
            WHERE id_personal = %s AND estado = 'procesando'
        """, (id_op,))
        
        existe = cursor.fetchone()
        
        if existe and existe['total'] > 0:
            st.warning("⚠️ Ya tienes una sesión activa.")
            if 'procesando_inicio' in st.session_state:
                del st.session_state.procesando_inicio
            st.rerun()
            return

        # Obtener primer lote
        cursor.execute("""
            SELECT lote_completo 
            FROM ordenes 
            WHERE lote_padre = %s 
            LIMIT 1
        """, (lote_padre,))
        
        primera_orden = cursor.fetchone()
        
        if not primera_orden:
            st.error("❌ No se encontraron órdenes.")
            if 'procesando_inicio' in st.session_state:
                del st.session_state.procesando_inicio
            return

        # Insertar
        query = """
            INSERT INTO produccion
            (lote_referencia, id_personal, planchas_procesadas,
             maquina_real, hora_inicio, estado)
            VALUES (%s, %s, %s, %s, %s, 'procesando')
        """
        cursor.execute(query, (
            primera_orden['lote_completo'],
            id_op,
            planchas,
            maq_r,
            hora_actual
        ))

        conn.commit()
        
        if 'procesando_inicio' in st.session_state:
            del st.session_state.procesando_inicio
        
        st.success("🚀 Producción iniciada.")
        st.rerun()

    except Exception as e:
        st.error(f"❌ Error: {e}")
        conn.rollback()
        if 'procesando_inicio' in st.session_state:
            del st.session_state.procesando_inicio
    finally:
        conn.close()


# ============================================================
# FUNCIÓN: FINALIZAR PRODUCCIÓN
# ============================================================
def finalizar_produccion(id_registro, lote_f, ancho_r, obs):
    """
    Guarda producción con todas las órdenes (originales + nuevas)
    """
    conn = get_connection()
    if not conn:
        st.error("❌ Error de conexión.")
        if 'procesando_finalizacion' in st.session_state:
            del st.session_state.procesando_finalizacion
        return

    try:
        cursor = conn.cursor(dictionary=True)
        hora_actual = datetime.now()

        # 1. Actualizar produccion
        query_produccion = """
            UPDATE produccion
            SET hora_fin = %s,
                estado = 'finalizado',
                lote_de_planchas = %s,
                ancho_real = %s,
                observacciones = %s
            WHERE id_registro = %s
        """
        cursor.execute(query_produccion, (
            hora_actual,
            lote_f if lote_f else None,
            ancho_r if ancho_r > 0 else None,
            obs if obs != "" else None,
            id_registro
        ))

        # 2. Guardar detalles
        if 'ordenes_editables' in st.session_state:
            for orden in st.session_state.ordenes_editables:
                query_detalle = """
                    INSERT INTO detalles_produccion 
                    (id_registro_produccion, lote_completo, cant_cortada_real, 
                     ancho_fleje_real, destino_real)
                    VALUES (%s, %s, %s, %s, %s)
                """
                cursor.execute(query_detalle, (
                    id_registro,
                    orden['lote_completo'],
                    orden['cant_cortada'],
                    orden['ancho_fleje'],
                    orden['destino']
                ))
        
        conn.commit()

        # Limpiar
        if 'ordenes_editables' in st.session_state:
            del st.session_state['ordenes_editables']
        if 'procesando_finalizacion' in st.session_state:
            del st.session_state.procesando_finalizacion
            
        for key in ["input_lote", "maquina_real", "planchas_proc",
                   "lote_fisico", "ancho_real", "observaciones"]:
            if key in st.session_state:
                del st.session_state[key]

        st.success("✅ Producción finalizada correctamente.")
        st.rerun()

    except Exception as e:
        st.error(f"❌ Error: {e}")
        conn.rollback()
        if 'procesando_finalizacion' in st.session_state:
            del st.session_state.procesando_finalizacion
    finally:
        conn.close()


# ============================================================
# FIN DEL MÓDULO
# ============================================================