import streamlit as st
import pandas as pd
from src.database import get_connection


def mostrar_pantalla():
    st.title("🛠️ Registro de Producción")

    
    # 1PASO 1 – INGRESAR LOTE
    #
    st.subheader("1 Ingrese Lote")

    lote_padre = st.text_input(
        "LOTE (Padre):",
        key="input_lote"
    ).strip()

    if not lote_padre:
        st.info("Ingrese primero el número de lote para continuar.")
        return

    conn = get_connection()
    if not conn:
        st.error("No hay conexión a la base de datos.")
        return

    cursor = conn.cursor(dictionary=True)

    # 
    #  ESTADO DE PRODUCCIÓN
    # 
    cursor.execute("SELECT DISTINCT nombre_maquina FROM ordenes")
    lista_maquinas = ["Seleccione Máquina..."] + \
        [row['nombre_maquina'] for row in cursor.fetchall()]

    query_saldo = """
        SELECT 
            MAX(o.cantidad_planchas) as meta,
            (SELECT IFNULL(SUM(planchas_procesadas), 0) FROM produccion 
             WHERE lote_referencia IN 
             (SELECT lote_completo FROM ordenes WHERE lote_padre = %s)) 
             / (SELECT COUNT(*) FROM ordenes WHERE lote_padre = %s) as hecho
        FROM ordenes o 
        WHERE o.lote_padre = %s
    """
    cursor.execute(query_saldo, (lote_padre, lote_padre, lote_padre))
    resumen = cursor.fetchone()

    if not resumen or not resumen["meta"]:
        st.warning("No se encontraron órdenes para este lote.")
        conn.close()
        return

    meta = int(resumen["meta"])
    hecho = int(resumen["hecho"] or 0)
    faltante = meta - hecho

    st.markdown("### 📊 Estado de Producción")

    if faltante > 0:
        progreso = hecho / meta
        st.progress(progreso)
        st.info(
            f"Procesadas **{hecho}** de **{meta}** planchas. "
            f"Pendientes: **{faltante}**"
        )
    else:
        st.success(
            f"✅ Producción completada: {meta} de {meta} planchas procesadas."
        )
        conn.close()
        return  # 🔒 Bloquea todo si ya terminó

    #  FORMULARIO

    st.subheader(" Registrar Producción")

    with st.container(border=True):

        col1, col2 = st.columns(2)

        with col1:
            maquina_real = st.selectbox(
                "Maq. Proceso (Real):",
                lista_maquinas,
                key="maquina_real"
            )

            planchas_proc = st.number_input(
                "Planchas Procesadas:",
                min_value=1,
                max_value=faltante,  # 🔒 no puede exceder lo pendiente
                step=1,
                key="planchas_proc"
            )

        with col2:
            lote_fisico = st.text_input(
                "Lote de Planchas:",
                key="lote_fisico"
            )

            ancho_real = st.number_input(
                "Ancho Real Plancha:",
                min_value=0,
                key="ancho_real"
            )

            observaciones = st.selectbox(
                "Observación (Opcional):",
                [
                    "",  # 🔹 permite vacío
                    "Descuadre", "Ondulado", "Quebrado",
                    "Oxidado", "Rayado", "Rebaba",
                    "Bajo espesor", "Daño de maquina"
                ],
                key="observaciones"
            )

 
    4#TABLA DETALLE
    
    cursor.execute("SELECT * FROM ordenes WHERE lote_padre = %s", (lote_padre,))
    filas = cursor.fetchall()

    if filas:
        df = pd.DataFrame(filas)

        df["Cant. Cortada Calc"] = planchas_proc * df["cant"]
        df["Peso Total Calc"] = df["peso_unitario"] * df["Cant. Cortada Calc"]

        st.markdown("### 📋 Detalle del Corte")

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

        st.table(
            df[list(columnas_ver.keys())]
            .rename(columns=columnas_ver)
        )

        
        # BOTÓN GUARDAR
        
        boton_deshabilitado = (
            maquina_real == "Seleccione Máquina..."
        )

        if st.button(
            "GUARDAR REGISTRO",
            use_container_width=True,
            disabled=boton_deshabilitado
        ):
            guardar_y_limpiar_interfaz(
                filas,
                planchas_proc,
                lote_fisico,
                ancho_real,
                observaciones,
                maquina_real
            )

    conn.close()


def guardar_y_limpiar_interfaz(
    filas, planchas, lote_f, ancho_r, obs, maq_r
):
    conn = get_connection()
    if not conn:
        st.error("Error de conexión.")
        return

    try:
        cursor = conn.cursor()
        id_op = st.session_state.usuario["id"]

        for row in filas:
            query = """
                INSERT INTO produccion
                (lote_referencia, id_personal, lote_de_planchas,
                 planchas_procesadas, observacciones,
                 ancho_real, maquina_real)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(
                query,
                (
                    row["lote_completo"],
                    id_op,
                    lote_f,
                    planchas,
                    obs if obs != "" else None,  # guarda NULL si está vacío
                    ancho_r,
                    maq_r
                )
            )

        conn.commit()

        #  Limpieza SOLO del formulario
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

        st.success(" Registro guardado correctamente.")
        st.rerun()

    except Exception as e:
        st.error(f"Error al guardar: {e}")
    finally:
        conn.close()
