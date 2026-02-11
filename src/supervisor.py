import streamlit as st
import pandas as pd
import numpy as np
from src.database import get_connection

def mostrar_pantalla():
    st.title("Panel del Supervisor")
    st.subheader("Carga de Órdenes de Producción")

    # 1. Agregamos un botón para resetear la vista si ya se subió algo
    if st.button("Cargar un nuevo archivo"):
        st.rerun()

    # 2. El cargador de archivos
    archivo = st.file_uploader("Sube el archivo Excel (.xlsx)", type=['xlsx'], key="supervisor_upload")

    if archivo:
        try:
            df = pd.read_excel(archivo)
            st.write("### Vista previa de los datos")
            st.dataframe(df.head())

            if st.button("Guardar todo en Base de Datos", key="btn_guardar"):
                # Ejecutamos el guardado
                procesar_y_guardar(df)
                
                # Mensaje final y opción de continuar
                st.info("Para subir otro archivo diferente, presiona el botón 'Cargar un nuevo archivo' arriba.")
                
        except Exception as e:
            st.error(f"Error al leer el archivo: {e}")

def procesar_y_guardar(df):
    # (El resto de tu código de guardado se mantiene igual aquí...)
    conn = get_connection()
    if not conn:
        st.error("No se pudo conectar a la base de datos.")
        return

    try:
        cursor = conn.cursor()
        df = df.replace({np.nan: None})
        exitos = 0
        
        for index, row in df.iterrows():
            lote_completo = str(row['LOTE'])
            lote_padre = lote_completo.split('-')[0]

            query = """
                INSERT INTO ordenes (
                    lote_completo, lote_padre, id_maquina, nombre_maquina, 
                    cantidad_planchas, ancho_pl, desaplancha, espesor, 
                    calidad, largo, desarrollo, cant, can_total, 
                    destino, cof_FA, cod_SAP, cod_UTIL, cod_IBS, 
                    peso_unitario, peso_total, orden, lot_insp, 
                    COD_proceso, descrip_SAP
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    cantidad_planchas = VALUES(cantidad_planchas),
                    can_total = VALUES(can_total),
                    peso_total = VALUES(peso_total)
            """

            valores = (
                lote_completo, lote_padre, row['ID MAQUINA'], row['MAQUINA'],
                row['Cant. Planchas'], row['Ancho Pl.'], row['Desaplancha'],
                row['Espesor'], row['Calidad'], row['Largo'], row['Desarrollo'],
                row['Cant.'], row['can.total'], row['Destino'], row['COD.FA'],
                row['COD.SAP'], row['COD.UTIL'], row['COD.IBS'], row['Peso Unt.'],
                row['Peso Total'], row['ORDEN'], row['Lot. Insp.'], row['COD'],
                row['DESCRIP. SAP']
            )

            cursor.execute(query, valores)
            exitos += 1

        conn.commit()
        st.success(f"Se han guardado {exitos} registros correctamente.")

    except Exception as e:
        st.error(f"Error al procesar los datos: {e}")
    finally:
        conn.close()