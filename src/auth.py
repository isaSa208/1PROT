from src.database import get_connection

def validar_usuario(nombre_usuario, password):
    conn = get_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            query = "SELECT id, nombre_usuario, rol FROM usuarios WHERE nombre_usuario = %s AND clave = %s"
            cursor.execute(query, (nombre_usuario, password))
            usuario = cursor.fetchone()
            return usuario
        except Exception as e:
            print(f"Error: {e}")
            return None
        finally:
            conn.close()
    return None