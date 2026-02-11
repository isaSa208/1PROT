import streamlit as st
from src.auth import validar_usuario

# Configuración básica de la página
st.set_page_config(page_title="Sistema Vidrios", layout="wide")

def main():
    # Inicializar el estado de la sesión si no existe
    if 'usuario' not in st.session_state:
        st.session_state.usuario = None

    # --- PANTALLA DE LOGIN ---
    if st.session_state.usuario is None:
        st.title("🔐 Control de Producción - Login")
        
        col1, col2 = st.columns([1, 1])
        with col1:
            with st.form("login_form"):
                user_input = st.text_input("Usuario")
                pass_input = st.text_input("Contraseña", type="password")
                submit = st.form_submit_button("Ingresar")

                if submit:
                    user_data = validar_usuario(user_input, pass_input)
                    if user_data:
                        st.session_state.usuario = user_data
                        st.success(f"Bienvenido {user_data['nombre_usuario']}")
                        st.rerun()
                    else:
                        st.error("Credenciales incorrectas")

    # --- PANTALLA UNA VEZ LOGUEADO ---
    else:
        rol = st.session_state.usuario['rol']
        nombre = st.session_state.usuario['nombre_usuario']

        # Barra lateral común
        st.sidebar.title(f"Bienvenido, {nombre}")
        st.sidebar.write(f"Rol: **{rol.upper()}**")
        
        if st.sidebar.button("Cerrar Sesión"):
            st.session_state.usuario = None
            st.rerun()

        # Diferenciar Vistas
        if rol == 'supervisor':
            import src.supervisor as supervisor_view
            supervisor_view.mostrar_pantalla()
        else:
            import src.personal as personal_view
            personal_view.mostrar_pantalla()

if __name__ == "__main__":
    main()