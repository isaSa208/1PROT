"""
=====================================================
MÓDULO: Registro de Producción con Sistema de Tiempos
=====================================================
Versión: 3.3 - Corregido duplicación al iniciar
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
    # TABLA DETALLE - EDITABLE SI YA INICIÓ
    # ========================================
    cursor.execute("SELECT * FROM ordenes WHERE lote_padre = %s", (lote_padre,))
    filas = cursor.fetchall()

    if filas:
        df = pd.DataFrame(filas)

        st.markdown("### 📋 Detalle del Corte")

        if mi_sesion:
            # ========================================
            # MODO EDICIÓN (Ya inició producción)
            # ========================================
            st.info("✏️ **Modo edición activado** - Puede modificar los campos resaltados")
            
            # Capturar datos editados
            datos_editados = []
            
            for idx, row in enumerate(df.to_dict('records')):
                st.markdown(f"**Orden {idx + 1}: {row['lote_completo']}**")
                
                col_ed1, col_ed2, col_ed3 = st.columns(3)
                
                with col_ed1:
                    cant_cortada = st.number_input(
                        "Cant. Cortada:",
                        min_value=0,
                        value=int(row['cant'] * planchas_proc),
                        key=f"cant_cortada_{idx}",
                        help="Cantidad real cortada"
                    )
                
                with col_ed2:
                    ancho_fleje = st.number_input(
                        "Ancho Fleje (mm):",
                        min_value=0,
                        value=int(row['desarrollo'] or 0),
                        key=f"ancho_fleje_{idx}",
                        help="Ancho real del fleje"
                    )
                
                with col_ed3:
                    destino_edit = st.selectbox(
                        "Destino:",
                        ["PLEGADO", "VENTA"],
                        index=0 if row['destino'] == 'PLEGADO' else 1,
                        key=f"destino_{idx}"
                    )
                
                # Guardar datos editados
                datos_editados.append({
                    'lote_completo': row['lote_completo'],
                    'cant_cortada_real': cant_cortada,
                    'ancho_fleje_real': ancho_fleje,
                    'destino_real': destino_edit
                })
                
                st.divider()
            
            # Mostrar tabla resumen
            df["Cant Cortada"] = [d['cant_cortada_real'] for d in datos_editados]
            df["Ancho Fleje"] = [d['ancho_fleje_real'] for d in datos_editados]
            df["Flejes Pend."] = df["desaplancha"] - df["Cant Cortada"]
            df["Destino"] = [d['destino_real'] for d in datos_editados]
            df["Peso Total"] = df["peso_unitario"] * df["Cant Cortada"]

            columnas_resumen = {
                "lote_completo": "Lote",
                "cantidad_planchas": "Cant Plancha",
                "desaplancha": "Aprov.",
                "Ancho Fleje": "Ancho Fleje",
                "largo": "Largo",
                "Cant Cortada": "Cant Cortada",
                "Flejes Pend.": "Flejes Pend.",
                "Destino": "Destino",
                "peso_unitario": "Peso Unit.",
                "Peso Total": "Peso Total",
                "cod_IBS": "Cód. IBS"
            }

            df_mostrar = df[list(columnas_resumen.keys())].copy()
            
            # Sin decimales excepto pesos
            for col in ["cantidad_planchas", "desaplancha", "Ancho Fleje", "largo", 
                       "Cant Cortada", "Flejes Pend."]:
                if col in df_mostrar.columns:
                    df_mostrar[col] = df_mostrar[col].fillna(0).astype(int)
            
            if "peso_unitario" in df_mostrar.columns:
                df_mostrar["peso_unitario"] = df_mostrar["peso_unitario"].map('{:.4f}'.format)
            if "Peso Total" in df_mostrar.columns:
                df_mostrar["Peso Total"] = df_mostrar["Peso Total"].map('{:.4f}'.format)

            st.table(df_mostrar.rename(columns=columnas_resumen))
            
        else:
            # ========================================
            # MODO LECTURA (No ha iniciado)
            # ========================================
            datos_editados = None
            
            df["Cant. Cortada Calc"] = (planchas_proc * df["cant"]).astype(int)
            df["Peso Total Calc"] = df["peso_unitario"] * df["Cant. Cortada Calc"]

            columnas_ver = {
                "cantidad_planchas": "Cant. Plancha",
                "desaplancha": "Aprovechamiento",
                "desarrollo": "Ancho",
                "largo": "Largo",
                "Cant. Cortada Calc": "Cant. Cortada",
                "destino": "Destino",
                "peso_unitario": "Peso Unitario",
                "Peso Total Calc": "Peso Total",
                "cod_IBS": "Código",
                "orden": "Orden",
                "lote_completo": "Lote"
            }

            df_mostrar = df[list(columnas_ver.keys())].copy()
            
            for col in ["cantidad_planchas", "desaplancha", "desarrollo", "largo", 
                       "Cant. Cortada Calc", "orden"]:
                if col in df_mostrar.columns:
                    df_mostrar[col] = df_mostrar[col].fillna(0).astype(int)
            
            if "peso_unitario" in df_mostrar.columns:
                df_mostrar["peso_unitario"] = df_mostrar["peso_unitario"].map('{:.4f}'.format)
            if "Peso Total Calc" in df_mostrar.columns:
                df_mostrar["Peso Total Calc"] = df_mostrar["Peso Total Calc"].map('{:.4f}'.format)

            st.table(df_mostrar.rename(columns=columnas_ver))

        # ========================================
        # BOTÓN DINÁMICO
        # ========================================
        if mi_sesion:
            # FINALIZAR
            if st.button(
                "✅ FINALIZAR Y GUARDAR",
                use_container_width=True,
                key="btn_finalizar"
            ):
                if 'procesando_finalizacion' not in st.session_state:
                    st.session_state.procesando_finalizacion = True
                    
                    finalizar_produccion(
                        mi_sesion['id_registro'],
                        lote_fisico,
                        ancho_real,
                        observaciones,
                        datos_editados
                    )
        else:
            # INICIAR
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
                        lote_padre,  # ← Cambiado: solo pasamos el lote_padre
                        planchas_proc,
                        maquina_real
                    )

    conn.close()


# ============================================================
# FUNCIÓN: INICIAR PRODUCCIÓN (CORREGIDA)
# ============================================================
def iniciar_produccion(lote_padre, planchas, maq_r):
    """
    Inserta UN SOLO registro con estado='procesando'
    """
    conn = get_connection()
    if not conn:
        st.error("❌ Error de conexión a la base de datos.")
        if 'procesando_inicio' in st.session_state:
            del st.session_state.procesando_inicio
        return

    try:
        cursor = conn.cursor(dictionary=True)
        id_op = st.session_state.usuario["id"]
        hora_actual = datetime.now()

        # Verificar que no exista sesión activa
        cursor.execute("""
            SELECT COUNT(*) as total
            FROM produccion 
            WHERE id_personal = %s 
              AND estado = 'procesando'
        """, (id_op,))
        
        existe = cursor.fetchone()
        
        if existe and existe['total'] > 0:
            st.warning("⚠️ Ya tienes una sesión activa. Recargando...")
            if 'procesando_inicio' in st.session_state:
                del st.session_state.procesando_inicio
            st.rerun()
            return

        # Obtener el PRIMER lote_completo del lote_padre
        cursor.execute("""
            SELECT lote_completo 
            FROM ordenes 
            WHERE lote_padre = %s 
            LIMIT 1
        """, (lote_padre,))
        
        primera_orden = cursor.fetchone()
        
        if not primera_orden:
            st.error("❌ No se encontraron órdenes para este lote.")
            if 'procesando_inicio' in st.session_state:
                del st.session_state.procesando_inicio
            return

        # Insertar UN SOLO registro
        query = """
            INSERT INTO produccion
            (lote_referencia, id_personal, planchas_procesadas,
             maquina_real, hora_inicio, estado)
            VALUES (%s, %s, %s, %s, %s, 'procesando')
        """
        cursor.execute(
            query,
            (
                primera_orden['lote_completo'],
                id_op,
                planchas,
                maq_r,
                hora_actual
            )
        )

        conn.commit()
        
        if 'procesando_inicio' in st.session_state:
            del st.session_state.procesando_inicio
        
        st.success("🚀 Producción iniciada. Ahora puede editar los datos del corte.")
        st.rerun()

    except Exception as e:
        st.error(f"❌ Error al iniciar producción: {e}")
        conn.rollback()
        
        if 'procesando_inicio' in st.session_state:
            del st.session_state.procesando_inicio
            
    finally:
        conn.close()


# ============================================================
# FUNCIÓN: FINALIZAR PRODUCCIÓN
# ============================================================
def finalizar_produccion(id_registro, lote_f, ancho_r, obs, datos_editados):
    """
    Actualiza produccion y guarda detalles editados
    """
    conn = get_connection()
    if not conn:
        st.error("❌ Error de conexión a la base de datos.")
        if 'procesando_finalizacion' in st.session_state:
            del st.session_state.procesando_finalizacion
        return

    try:
        cursor = conn.cursor(dictionary=True)
        hora_actual = datetime.now()

        # Verificar que el registro esté en procesando
        cursor.execute("""
            SELECT estado 
            FROM produccion 
            WHERE id_registro = %s
        """, (id_registro,))
        
        registro = cursor.fetchone()
        
        if not registro:
            st.error(f"❌ No se encontró el registro {id_registro}")
            if 'procesando_finalizacion' in st.session_state:
                del st.session_state.procesando_finalizacion
            return
            
        if registro['estado'] == 'finalizado':
            st.warning("⚠️ Esta producción ya fue finalizada.")
            if 'procesando_finalizacion' in st.session_state:
                del st.session_state.procesando_finalizacion
            st.rerun()
            return

        # 1. Actualizar tabla produccion
        query_produccion = """
            UPDATE produccion
            SET hora_fin = %s,
                estado = 'finalizado',
                lote_de_planchas = %s,
                ancho_real = %s,
                observacciones = %s
            WHERE id_registro = %s
        """
        cursor.execute(
            query_produccion,
            (
                hora_actual,
                lote_f if lote_f else None,
                ancho_r if ancho_r > 0 else None,
                obs if obs != "" else None,
                id_registro
            )
        )

        # 2. Guardar detalles editados
        if datos_editados:
            for dato in datos_editados:
                query_detalle = """
                    INSERT INTO detalles_produccion 
                    (id_registro_produccion, lote_completo, cant_cortada_real, 
                     ancho_fleje_real, destino_real)
                    VALUES (%s, %s, %s, %s, %s)
                """
                cursor.execute(
                    query_detalle,
                    (
                        id_registro,
                        dato['lote_completo'],
                        dato['cant_cortada_real'],
                        dato['ancho_fleje_real'],
                        dato['destino_real']
                    )
                )
        
        conn.commit()

        # Limpiar session_state
        if 'procesando_finalizacion' in st.session_state:
            del st.session_state.procesando_finalizacion
            
        for key in [
            "input_lote",
            "maquina_real",
            "planchas_proc",
            "lote_fisico",
            "ancho_real",
            "observaciones"
        ]:
            if key in st.session_state:
                del st.session_state[key]

        st.success("✅ Producción finalizada y guardada correctamente.")
        st.rerun()

    except Exception as e:
        st.error(f"❌ Error al finalizar producción: {e}")
        conn.rollback()
        
        if 'procesando_finalizacion' in st.session_state:
            del st.session_state.procesando_finalizacion
            
    finally:
        conn.close()


# ============================================================
# FIN DEL MÓDULO
# ============================================================