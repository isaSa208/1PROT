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

    # VERIFICAR SESIÓN ACTIVA DEL OPERARIO
    id_operario = st.session_state.usuario["id"]
    nombre_operador = st.session_state.usuario.get("nombre_usuario", "Operador")

    # CORRECCIÓN 1: Verificar sesión en CUALQUIER lote, no solo este
    cursor.execute("""
        SELECT * FROM produccion 
        WHERE id_personal = %s AND estado = 'procesando'
        LIMIT 1
    """, (id_operario,))
    sesion_activa = cursor.fetchone()

    # CORRECCIÓN 2: Si tiene sesión activa en OTRO lote, bloquearlo
    if sesion_activa:
        cursor.execute("""
            SELECT lote_padre 
            FROM ordenes 
            WHERE lote_completo = %s
        """, (sesion_activa['lote_referencia'],))
        
        lote_de_sesion = cursor.fetchone()
        
        if lote_de_sesion and lote_de_sesion['lote_padre'] != lote_padre:
            st.error(f"⚠️ Tienes una producción activa en el lote **{lote_de_sesion['lote_padre']}**. Finalízala primero.")
            conn.close()
            return

    # OBTENER MÁQUINAS Y MÁQUINA SUGERIDA (PROGRAMADA)
    cursor.execute("SELECT DISTINCT nombre_maquina FROM ordenes WHERE nombre_maquina IS NOT NULL ORDER BY nombre_maquina")
    lista_maquinas = ["Seleccione Máquina..."] + [row['nombre_maquina'] for row in cursor.fetchall()]
    
    cursor.execute("SELECT nombre_maquina FROM ordenes WHERE lote_padre = %s LIMIT 1", (lote_padre,))
    maq_prog = cursor.fetchone()
    maquina_programada = maq_prog['nombre_maquina'] if maq_prog else "No asignada"

    # RESUMEN DE SALDOS (MÉTRICAS) - Cuenta planchas una vez por sesión
    query_saldo = """
        SELECT 
            MAX(o.cantidad_planchas) as meta,
            IFNULL((SELECT SUM(sub.planchas) FROM (
                SELECT MAX(p.planchas_procesadas) as planchas
                FROM produccion p
                INNER JOIN ordenes o2 ON p.lote_referencia = o2.lote_completo
                WHERE o2.lote_padre = %s AND p.estado = 'finalizado'
                GROUP BY p.hora_inicio, p.id_personal
            ) sub), 0) as finalizado,
            IFNULL((SELECT SUM(sub.planchas) FROM (
                SELECT MAX(p.planchas_procesadas) as planchas
                FROM produccion p
                INNER JOIN ordenes o2 ON p.lote_referencia = o2.lote_completo
                WHERE o2.lote_padre = %s AND p.estado = 'procesando'
                GROUP BY p.hora_inicio, p.id_personal
            ) sub), 0) as en_proceso
        FROM ordenes o WHERE o.lote_padre = %s
    """
    cursor.execute(query_saldo, (lote_padre, lote_padre, lote_padre))
    resumen = cursor.fetchone()

    if not resumen or not resumen["meta"]:
        st.warning("⚠️ No se encontraron órdenes para este lote.")
        conn.close()
        return

    meta = int(resumen["meta"] or 0)
    finalizado = int(resumen["finalizado"] or 0)
    en_proceso = int(resumen["en_proceso"] or 0)
    faltante = meta - (finalizado + en_proceso)  # CORRECCIÓN 3: Calcular faltante correctamente
    
    # CORRECCIÓN 4: Evitar progreso > 1.0
    progreso_calculado = finalizado / meta if meta > 0 else 0
    progreso_seguro = min(progreso_calculado, 1.0)
    
    # Métricas visuales
    st.markdown("### 📊 Estado de Producción")
    c1, c2, c3 = st.columns(3)
    c1.metric("✅ Finalizadas", f"{finalizado} / {meta}")
    c2.metric("⏳ En Proceso", en_proceso)
    c3.metric("📦 Pendientes", max(faltante, 0))  # CORRECCIÓN 5: No negativos
    st.progress(progreso_seguro)

    # CORRECCIÓN 6: Bloquear si ya está completo
    if faltante <= 0 and en_proceso == 0:
        st.success(f"✅ Producción completada: {meta} de {meta} planchas.")
        conn.close()
        return

    # ========================================
    # PASO 2: FORMULARIO DE REGISTRO
    # ========================================
    st.subheader("⚙️ 2. Registrar Producción")
    
    # CORRECCIÓN 7: Verificar sesión del LOTE ACTUAL (cualquier sublote del lote_padre)
    cursor.execute("""
        SELECT p.* 
        FROM produccion p
        INNER JOIN ordenes o ON p.lote_referencia = o.lote_completo
        WHERE p.id_personal = %s 
          AND o.lote_padre = %s
          AND p.estado = 'procesando'
        LIMIT 1
    """, (id_operario, lote_padre))
    mi_sesion = cursor.fetchone()
    
    with st.container(border=True):
        col_f1, col_f2 = st.columns(2)
        if mi_sesion:
            # Sesión en curso: Solo mostrar campos de cierre
            st.success(f"🚀 Producción iniciada a las {mi_sesion['hora_inicio'].strftime('%H:%M:%S')}")
            maquina_real = col_f1.text_input("Maq. Real:", value=mi_sesion['maquina_real'], disabled=True)
            planchas_proc = int(mi_sesion['planchas_procesadas'])
            col_f1.number_input("Planchas:", value=planchas_proc, disabled=True)
            
            lote_fisico = col_f2.text_input("Lote de Planchas:", key="lote_fisico", placeholder="LP-XXXX")
            ancho_real = col_f2.number_input("Ancho Real Plancha (mm):", min_value=0, key="ancho_real")
            observaciones = col_f2.selectbox("Observación:", ["", "Descuadre", "Ondulado", "Quebrado", "Oxidado", "Rayado", "Rebaba", "Bajo espesor", "Daño de maquina"], key="observaciones")
        else:
            # Antes de iniciar: Elige máquina y planchas
            col_f1.warning(f"📌 **Maq. Programada:** {maquina_programada}") 
            maquina_real = col_f1.selectbox("Maq. Real (Elegir):", lista_maquinas, key="maquina_real")
            # CORRECCIÓN 8: max_value basado en faltante
            planchas_proc = col_f1.number_input(
                "Planchas a Procesar:", 
                min_value=1, 
                max_value=max(faltante, 1), 
                value=min(10, max(faltante, 1)), 
                key="planchas_proc"
            )
            st.info("💡 Revise el detalle abajo antes de Iniciar Producción.")

    # TABLA DE ÓRDENES
    cursor.execute("SELECT * FROM ordenes WHERE lote_padre = %s ORDER BY lote_completo", (lote_padre,))
    ordenes_originales = cursor.fetchall()

    if ordenes_originales:
        if mi_sesion:
            # MODO CUADRE (EDICIÓN)
            st.session_state.cursor_temp = cursor
            mostrar_tabla_edicion(ordenes_originales, planchas_proc, lote_padre)
            
            btn_fin_disabled = not lote_fisico or ancho_real <= 0
            if st.button("✅ FINALIZAR Y GUARDAR", use_container_width=True, disabled=btn_fin_disabled):
                finalizar_produccion(mi_sesion['id_registro'], lote_fisico, ancho_real, observaciones)
        else:
            # MODO VISTA PREVIA (LECTURA)
            st.markdown("### 📋 Vista Previa de la Orden")
            mostrar_tabla_lectura(ordenes_originales)
            if st.button("🚀 INICIAR PRODUCCIÓN", use_container_width=True, disabled=(maquina_real == "Seleccione Máquina...")):
                iniciar_produccion(lote_padre, planchas_proc, maquina_real, maquina_programada)

    conn.close()




def mostrar_tabla_lectura(ordenes):
    """Muestra la tabla informativa antes de iniciar"""
    datos = []
    for o in ordenes:
        datos.append({
            'LOTE': o['lote_completo'],
            'ORDEN': o['orden'],
            'can.total': o['can_total'],
            'Desarrollo': o['desarrollo'],
            'Largo': o['largo'],
            'Espesor': f"{o['espesor']:.2f}",
            'Destino': o['destino'],
            'Maq. Progam': o['nombre_maquina'],
            'Peso Unt.': f"{o['peso_unitario']:.4f}",
            'Descripción': o.get('descrip_SAP', 'N/A'),
            'Fecha Emisión': o.get('fecha_subida', 'N/A')
        })
    st.dataframe(pd.DataFrame(datos), use_container_width=True, hide_index=True)

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
                'desarrollo': int(o['desarrollo'] or 0),  # CORRECCIÓN 10: Agregar desarrollo
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
                
                # CORRECCIÓN 11: Solo buscar si es NUEVA o cambió el ancho
                if ancho_n != orden['ancho_fleje']:
                    st.session_state.ordenes_editables[idx]['ancho_fleje'] = ancho_n
                    st.session_state.ordenes_editables[idx]['desarrollo'] = ancho_n
                    
                    if ancho_n > 0 and cursor:
                        cursor.execute("""
                            SELECT peso_unitario, largo, espesor, descrip_SAP
                            FROM ordenes 
                            WHERE desarrollo = %s 
                            LIMIT 1
                        """, (ancho_n,))
                        ref = cursor.fetchone()
                        if ref:
                            # CORRECCIÓN 12: NO cambiar cod_SAP ni cod_IBS
                            st.session_state.ordenes_editables[idx].update({
                                'peso_unitario': float(ref['peso_unitario'] or 0),
                                'largo': int(ref['largo'] or 0),
                                'espesor': float(ref['espesor'] or 0),
                                'descrip_SAP': ref['descrip_SAP'] or ''
                            })
                            st.success(f"✅ Peso: {float(ref['peso_unitario'] or 0):.4f} kg")
            
            with col3:
                dest = st.selectbox("Destino:", ["PLEGADO", "VENTA"], index=0 if orden['destino'] == 'PLEGADO' else 1, key=f"d_{idx}")
                st.session_state.ordenes_editables[idx]['destino'] = dest
            
            if orden['es_nueva'] and col4.button("🗑️", key=f"del_{idx}"):
                filas_a_eliminar.append(idx)

            # Calcular peso total
            peso_t = orden['peso_unitario'] * orden['cant_cortada']
            st.session_state.ordenes_editables[idx]['peso_total'] = peso_t
            
            st.markdown(f"📝 **Descripción:** {orden.get('descrip_SAP', 'N/A')}")
            st.caption(f"Largo: {orden['largo']}mm | SAP: {orden['cod_SAP']} | IBS: {orden['cod_IBS']} | Orden: {orden['orden']}")

    for idx in sorted(filas_a_eliminar, reverse=True):
        st.session_state.ordenes_editables.pop(idx)
        st.rerun()
    
    if st.button("➕ Agregar Nueva Orden", use_container_width=True):
        agregar_nueva_orden(lote_padre, planchas_proc)
        st.rerun()
    
    mostrar_tabla_resumen()

def agregar_nueva_orden(lote_padre, planchas_proc):
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
        'can_total': 0, 
        'orden': 0,
        'desarrollo': 0,  # CORRECCIÓN 13: Agregar desarrollo
        'es_nueva': True
    })

def mostrar_tabla_resumen():
    st.markdown("#### 📊 Resumen de Órdenes")
    if st.session_state.ordenes_editables:
        datos = []
        for o in st.session_state.ordenes_editables:
            datos.append({
                'Lote': o['lote_completo'], 
                'Cant Cortada': o['cant_cortada'],
                'Ancho Fleje': o['ancho_fleje'], 
                'Flejes Pend.': o.get('can_total', 0),
                'Destino': o['destino'],
                'Peso Unit.': f"{o['peso_unitario']:.4f}", 
                'Peso Total': f"{o.get('peso_total', 0):.4f}",
                'Largo': o['largo'], 
                'SAP': o['cod_SAP'], 
                'Orden': o['orden']
            })
        st.dataframe(pd.DataFrame(datos), use_container_width=True, hide_index=True)

def iniciar_produccion(lote_p, planchas, maq_real, maq_programada):
    """Inserta UN REGISTRO por cada LOTE COMPLETO del lote padre"""
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Obtener TODAS las órdenes del lote padre
        cursor.execute("SELECT * FROM ordenes WHERE lote_padre = %s ORDER BY lote_completo", (lote_p,))
        todas_ordenes = cursor.fetchall()
        
        if not todas_ordenes:
            st.error("❌ No se encontraron órdenes.")
            return
        
        nombre_op = st.session_state.usuario.get("nombre_usuario", "Operador")
        id_usuario = st.session_state.usuario["id"]
        hora_inicio_comun = datetime.now()
        
        # Insertar UN REGISTRO POR CADA LOTE COMPLETO
        for o in todas_ordenes:
            query = """
                INSERT INTO produccion 
                (lote_referencia, id_personal, planchas_procesadas, maquina_real, maq_proces, 
                operador, hora_inicio, estado, orden, can_total, desarrollo, largo, espesor, 
                peso_unitario, fecha_emision) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'procesando', %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, (
                o['lote_completo'],  # 4019783-01, 4019783-02, etc.
                id_usuario, 
                planchas, 
                maq_real,
                maq_programada,
                nombre_op, 
                hora_inicio_comun,  # Misma hora para todos
                o['orden'], 
                o['can_total'], 
                o['desarrollo'], 
                o['largo'], 
                o['espesor'], 
                o['peso_unitario'],
                o['fecha_subida']
            ))
        
        conn.commit()
        st.success(f"✅ Producción iniciada: {len(todas_ordenes)} órdenes registradas.")
        st.rerun()
    except Exception as e:
        st.error(f"❌ Error al iniciar: {e}")
        conn.rollback()
    finally: 
        conn.close()

def finalizar_produccion(id_reg, lote_f, ancho_r, obs):
    """
    Actualiza registros existentes e INSERTA las nuevas órdenes agregadas
    calculando el tiempo ponderado en formato HH:MM:SS.
    """
    if 'ordenes_editables' not in st.session_state:
        st.error("❌ Error: No se encontraron datos para guardar.")
        return

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        
        # 1. Obtener información base para la tanda (lote padre y tiempo)
        cursor.execute("""
            SELECT o.lote_padre, p.hora_inicio, p.id_personal, p.planchas_procesadas,
                   p.maquina_real, p.maq_proces, p.operador
            FROM produccion p
            INNER JOIN ordenes o ON p.lote_referencia = o.lote_completo
            WHERE p.id_registro = %s
        """, (id_reg,))
        
        info = cursor.fetchone()
        if not info:
            st.error("❌ No se encontró el registro de producción.")
            return
        
        lote_padre = info['lote_padre']
        h_inicio = info['hora_inicio']
        h_fin = datetime.now()
        
        # --- CÁLCULO DE TIEMPO PONDERADO (HH:MM:SS) ---
        diferencia = h_fin - h_inicio
        total_segundos = int(diferencia.total_seconds())
        horas, residuo = divmod(total_segundos, 3600)
        minutos, segundos = divmod(residuo, 60)
        tiempo_formateado = f"{horas:02d}:{minutos:02d}:{segundos:02d}"
        
        # Separar datos: editados vs nuevos
        datos_por_lote = {o['lote_completo']: o for o in st.session_state.ordenes_editables}
        ordenes_nuevas = [o for o in st.session_state.ordenes_editables if o.get('es_nueva')]
        
        # Obtener TODOS los registros en proceso del lote padre
        cursor.execute("""
            SELECT p.id_registro, p.lote_referencia
            FROM produccion p
            INNER JOIN ordenes o ON p.lote_referencia = o.lote_completo
            WHERE o.lote_padre = %s AND p.estado = 'procesando'
        """, (lote_padre,))
        registros_activos = cursor.fetchall()
        
        # 2. ACTUALIZAR registros que ya estaban en la base de datos
        for reg in registros_activos:
            lote_c = reg['lote_referencia']
            edit = datos_por_lote.get(lote_c, {})
            
            query_update = """
                UPDATE produccion 
                SET hora_fin = %s, estado = 'finalizado', lote_de_planchas = %s, 
                    ancho_real = %s, observacciones = %s, tiempo_ponderado = %s, 
                    peso_total = %s, cant_cortada_real = %s, ancho_fleje_real = %s, 
                    destino_real = %s
                WHERE id_registro = %s
            """
            cursor.execute(query_update, (
                h_fin, lote_f, ancho_r, obs, tiempo_formateado, 
                edit.get('peso_total', 0), edit.get('cant_cortada', 0), 
                edit.get('ancho_fleje', 0), edit.get('destino', 'VENTA'),
                reg['id_registro']
            ))
            
            # Guardar histórico en detalles_produccion
            cursor.execute("""
                INSERT INTO detalles_produccion 
                (id_registro_produccion, lote_completo, cant_cortada_real, ancho_fleje_real, destino_real) 
                VALUES (%s, %s, %s, %s, %s)
            """, (reg['id_registro'], lote_c, edit.get('cant_cortada', 0), edit.get('ancho_fleje', 0), edit.get('destino', 'VENTA')))

        # 3. INSERTAR órdenes nuevas (Filas agregadas manualmente)
        if ordenes_nuevas:
            for nueva in ordenes_nuevas:
                query_insert = """
                    INSERT INTO produccion 
                    (lote_referencia, id_personal, planchas_procesadas, maquina_real, maq_proces, 
                     operador, hora_inicio, hora_fin, estado, orden, can_total, desarrollo, largo, 
                     espesor, peso_unitario, peso_total, lote_de_planchas, ancho_real, 
                     observacciones, tiempo_ponderado, cant_cortada_real, ancho_fleje_real, destino_real) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'finalizado', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(query_insert, (
                    nueva['lote_completo'], info['id_personal'], info['planchas_procesadas'],
                    info['maquina_real'], info['maq_proces'], info['operador'], h_inicio, h_fin,
                    nueva.get('orden', 0), nueva.get('can_total', 0), nueva.get('desarrollo', 0),
                    nueva.get('largo', 0), nueva.get('espesor', 0), nueva.get('peso_unitario', 0),
                    nueva.get('peso_total', 0), lote_f, ancho_r, obs, tiempo_formateado,
                    nueva.get('cant_cortada', 0), nueva.get('ancho_fleje', 0), nueva.get('destino', 'VENTA')
                ))
                
                # Detalle para la nueva orden
                cursor.execute("""
                    INSERT INTO detalles_produccion 
                    (id_registro_produccion, lote_completo, cant_cortada_real, ancho_fleje_real, destino_real) 
                    VALUES (%s, %s, %s, %s, %s)
                """, (cursor.lastrowid, nueva['lote_completo'], nueva.get('cant_cortada', 0), nueva.get('ancho_fleje', 0), nueva.get('destino', 'VENTA')))

        conn.commit()
        
        # 4. Limpieza y éxito
        if 'ordenes_editables' in st.session_state:
            del st.session_state['ordenes_editables']
        for key in ["input_lote", "lote_fisico", "ancho_real", "observaciones"]:
            if key in st.session_state: del st.session_state[key]
            
        st.success(f"✅ Producción guardada con éxito. Tiempo total: {tiempo_formateado}")
        st.rerun()

    except Exception as e:
        conn.rollback()
        st.error(f"❌ Error al guardar: {e}")
    finally:
        conn.close()