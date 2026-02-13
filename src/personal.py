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
    lote_padre = st.text_input("LOTE (Padre):", key="input_lote", placeholder="Ej: 4019635").strip()

    if not lote_padre:
        st.info("👉 Ingrese el número de lote para continuar.")
        return

    conn = get_connection()
    if not conn: return
    cursor = conn.cursor(dictionary=True)

    # Verificar sesión activa
    id_operario = st.session_state.usuario["id"]
    cursor.execute("""
        SELECT id_registro, lote_referencia, planchas_procesadas, hora_inicio, maquina_real
        FROM produccion WHERE id_personal = %s AND estado = 'procesando' LIMIT 1
    """, (id_operario,))
    mi_sesion = cursor.fetchone()

    # Cargar órdenes base
    cursor.execute("SELECT * FROM ordenes WHERE lote_padre = %s", (lote_padre,))
    filas_base = cursor.fetchall()
    
    if not filas_base:
        st.warning("⚠️ No hay órdenes.")
        conn.close()
        return

    # Inicializar estado para nuevas filas si no existe
    if 'nuevas_filas' not in st.session_state:
        st.session_state.nuevas_filas = []

    # ========================================
    # PANEL DE DATOS Y FORMULARIO
    # ========================================
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            if mi_sesion:
                st.text_input("Máquina:", value=mi_sesion['maquina_real'], disabled=True)
                planchas_proc = int(mi_sesion['planchas_procesadas'])
            else:
                cursor.execute("SELECT DISTINCT nombre_maquina FROM ordenes WHERE nombre_maquina IS NOT NULL")
                maquinas = ["Seleccione..."] + [r['nombre_maquina'] for r in cursor.fetchall()]
                maquina_real = st.selectbox("Máquina:", maquinas)
                planchas_proc = st.number_input("Planchas a Procesar:", min_value=1, value=10)

        with col2:
            lote_fisico = st.text_input("Lote Físico:", disabled=not mi_sesion)
            ancho_real_p = st.number_input("Ancho Real Plancha:", disabled=not mi_sesion)

    # ========================================
    # TABLA DE DATOS (LECTURA / EDICIÓN)
    # ========================================
    st.subheader("📋 Detalle del Corte")
    
    # Preparar DataFrame
    df = pd.DataFrame(filas_base)
    
    if mi_sesion:
        # --- MODO EDICIÓN ---
        datos_editados = []
        
        # Unir filas base con las nuevas agregadas por el usuario
        todas_las_filas = filas_base + st.session_state.nuevas_filas
        
        for idx, row in enumerate(todas_las_filas):
            with st.expander(f"Orden: {row['lote_completo']}", expanded=True):
                c1, c2, c3 = st.columns(3)
                # Valores sugeridos
                val_cant = int(row.get('cant', 0) * planchas_proc) if 'cant' in row else 0
                val_ancho = int(row.get('desarrollo', 0))
                
                cant_c = c1.number_input("Cant. Cortada", min_value=0, value=val_cant, key=f"c_{idx}")
                ancho_f = c2.number_input("Ancho Fleje (mm)", min_value=0, value=val_ancho, key=f"a_{idx}")
                dest = c3.selectbox("Destino", ["PLEGADO", "VENTA"], key=f"d_{idx}")
                
                # Cálculos automáticos para la lógica de negocio
                peso_u = (ancho_f * 0.00785) # Ejemplo de fórmula de peso unitario simplificada
                peso_t = peso_u * cant_c
                
                datos_editados.append({
                    'lote_completo': row['lote_completo'],
                    'cant_cortada': cant_c,
                    'ancho_fleje': ancho_f,
                    'destino': dest,
                    'peso_u': peso_u,
                    'peso_t': peso_t,
                    'pendiente': (row.get('desaplancha', 0) if 'desaplancha' in row else 0) - cant_c
                })

        # Mostrar Tabla Resumen de lo editado
        st.table(pd.DataFrame(datos_editados))

        # BOTÓN AGREGAR (Punto 3)
        if st.button("➕ Agregar Nueva Orden"):
            # Generar correlativo (Punto 4)
            ultimo_lote = todas_las_filas[-1]['lote_completo']
            prefix, correl = ultimo_lote.rsplit('-', 1)
            nuevo_lote = f"{prefix}-{int(correl)+1:02d}"
            
            st.session_state.nuevas_filas.append({
                'lote_completo': nuevo_lote,
                'desarrollo': 0,
                'destino': 'VENTA'
            })
            st.rerun()

    else:
        # --- MODO LECTURA ANTES DE INICIAR (Punto 1) ---
        columnas_lectura = {
            "lote_completo": "Lote",
            "cantidad_planchas": "Cant Plancha",
            "largo": "Largo",
            "cod_SAP": "Código SAP",
            "cod_IBS": "Código IBS",
            "orden": "Orden"
        }
        st.table(df[list(columnas_lectura.keys())].rename(columns=columnas_lectura))

    # ========================================
    # BOTONES DE ACCIÓN
    # ========================================
    if not mi_sesion:
        if st.button("🚀 INICIAR PRODUCCIÓN", use_container_width=True):
            iniciar_produccion(lote_padre, planchas_proc, maquina_real)
    else:
        if st.button("✅ FINALIZAR Y GUARDAR", use_container_width=True):
            finalizar_produccion(mi_sesion['id_registro'], lote_fisico, ancho_real_p, datos_editados)




# ============================================================
# FUNCIÓN: INICIAR PRODUCCIÓN (CORREGIDA)
# ============================================================
def iniciar_produccion(lote_padre, planchas, maq_r):
    conn = get_connection()
    if not conn: return
    
    try:
        cursor = conn.cursor(dictionary=True)
        id_op = st.session_state.usuario["id"]
        
        # 1. Obtenemos el lote_completo principal para referencia inicial
        cursor.execute("SELECT lote_completo FROM ordenes WHERE lote_padre = %s LIMIT 1", (lote_padre,))
        primer_lote = cursor.fetchone()
        
        # 2. Creamos el registro en la tabla de producción
        query = """
            INSERT INTO produccion 
            (lote_referencia, id_personal, planchas_procesadas, maquina_real, hora_inicio, estado)
            VALUES (%s, %s, %s, %s, NOW(), 'procesando')
        """
        cursor.execute(query, (primer_lote['lote_completo'], id_op, planchas, maq_r))
        
        conn.commit()
        st.success("🚀 Producción iniciada!")
        st.rerun()
    except Exception as e:
        st.error(f"Error: {e}")
    finally:
        conn.close()


# ============================================================
# FUNCIÓN: FINALIZAR PRODUCCIÓN
# ============================================================
def finalizar_produccion(id_registro, lote_f, ancho_r, datos_editados):
    conn = get_connection()
    if not conn: return
    
    try:
        cursor = conn.cursor()
        
        # 1. Actualizar el registro principal (Cabezal)
        query_cabezal = """
            UPDATE produccion 
            SET hora_fin = NOW(), 
                estado = 'finalizado', 
                lote_de_planchas = %s, 
                ancho_real = %s 
            WHERE id_registro = %s
        """
        cursor.execute(query_cabezal, (lote_f, ancho_r, id_registro))
        
        # 2. Guardar el detalle de cada fleje (Originales y Nuevos)
        # Usamos REPLACE o INSERT para asegurar que se guarden los datos reales cortados
        query_detalle = """
            INSERT INTO detalles_produccion 
            (id_registro_produccion, lote_completo, cant_cortada_real, 
             ancho_fleje_real, destino_real, peso_unitario_real, peso_total_real)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        
        for fila in datos_editados:
            cursor.execute(query_detalle, (
                id_registro,
                fila['lote_completo'],
                fila['cant_cortada'],
                fila['ancho_fleje'],
                fila['destino'],
                fila['peso_u'], # Calculado automáticamente en la interfaz
                fila['peso_t']  # Calculado automáticamente en la interfaz
            ))
        
        conn.commit()
        
        # Limpiar variables de sesión para el siguiente lote
        if 'nuevas_filas' in st.session_state:
            del st.session_state.nuevas_filas
            
        st.success("✅ Producción y detalles guardados con éxito.")
        st.rerun()
        
    except Exception as e:
        conn.rollback()
        st.error(f"❌ Error al finalizar: {e}")
    finally:
        conn.close()