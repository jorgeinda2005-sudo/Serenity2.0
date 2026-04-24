import os
import psycopg2
from psycopg2 import pool
from config import logger

# Cargamos la URL
DATABASE_URL = os.getenv("DATABASE_URL")

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            print("❌ ERROR CRÍTICO: La variable DATABASE_URL está VACÍA en Railway.")
            return None
        try:
            # Añadimos un timeout de 10 segundos para que no se quede colgado
            _pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1, 
                maxconn=10, 
                dsn=DATABASE_URL,
                connect_timeout=10
            )
            print("✅ CONEXIÓN EXITOSA: El pool de Supabase se ha creado correctamente.")
        except Exception as e:
            print(f"❌ FALLO AL CREAR EL POOL: {str(e)}")
            print(f"🔍 URL detectada (revisa el formato): {DATABASE_URL[:20]}...")
            return None
    return _pool

def get_conn():
    p = get_pool()
    return p.getconn() if p else None

def release_conn(conn):
    p = get_pool()
    if p and conn:
        p.putconn(conn)

def execute_query(sql, params=(), fetch=False):
    conn = get_conn()
    if not conn:
        print("⚠️ No hay conexión disponible para ejecutar la consulta.")
        return [] if fetch else None
    
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            result = cur.fetchall() if fetch else None
        conn.commit()
        return result
    except Exception as e:
        conn.rollback()
        print(f"🔥 ERROR DE BASE DE DATOS: {str(e)}")
        try:
            conn.close()
        except:
            pass
        return [] if fetch else None
    finally:
        release_conn(conn)

# --- Funciones para main.py y ai_core.py ---

def crear_base_datos():
    # Esta función se llama al inicio. Si esto no imprime "Base de datos verificada", nada funciona.
    sql = "SELECT 1;" 
    res = execute_query(sql, fetch=True)
    if res:
        print("🚀 SERENITY: Conexión con Supabase verificada y lista.")
    else:
        print("💀 SERENITY: No se pudo verificar la conexión inicial.")

def guardar_usuario(user_id, username, first_name, last_name):
    sql = "INSERT INTO usuarios (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING;"
    execute_query(sql, (user_id, username))

def completar_registro(user_id, nombre, matricula, correo, telefono):
    sql = "UPDATE usuarios SET nombre_completo=%s, matricula=%s, correo=%s, telefono=%s, registrado=TRUE WHERE user_id=%s"
    execute_query(sql, (nombre, matricula, correo, telefono, user_id))

def usuario_registrado(user_id):
    sql = "SELECT registrado FROM usuarios WHERE user_id=%s"
    res = execute_query(sql, (user_id,), fetch=True)
    return res[0][0] if res else False

def obtener_datos_usuario(user_id):
    sql = "SELECT user_id, username, nombre_completo, matricula, correo, telefono, facultad FROM usuarios WHERE user_id=%s"
    res = execute_query(sql, (user_id,), fetch=True)
    if res:
        row = res[0]
        return {"id": row[0], "username": row[1], "nombre_completo": row[2], "matricula": row[3], "correo": row[4], "telefono": row[5], "facultad": row[6]}
    return {}

def guardar_mensaje(user_id, role, content):
    sql = "INSERT INTO conversaciones (user_id, role, content) VALUES (%s, %s, %s)"
    execute_query(sql, (user_id, role, content))

def obtener_historial(user_id, limite=10):
    sql = "SELECT role, content FROM conversaciones WHERE user_id=%s ORDER BY timestamp DESC LIMIT %s"
    res = execute_query(sql, (user_id, limite), fetch=True)
    return [{"role": row[0], "content": row[1]} for row in reversed(res or [])]

def registrar_alerta(user_id, nivel_riesgo, tema, razon):
    sql = "INSERT INTO alertas (user_id, nivel_riesgo, tema, razon) VALUES (%s, %s, %s, %s)"
    execute_query(sql, (user_id, nivel_riesgo, tema, razon))

def contar_mensajes_usuario(user_id):
    res = execute_query("SELECT COUNT(*) FROM conversaciones WHERE user_id=%s AND role='user'", (user_id,), fetch=True)
    return res[0][0] if res else 0

def registrar_dependencia(user_id, nivel, reporte):
    sql = """
        INSERT INTO dependencias (user_id, nivel, reporte, timestamp) 
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
    """
    execute_query(sql, (user_id, nivel, reporte))

def registrar_perfil_emocional(user_id, analisis):
    sql = """
        INSERT INTO perfil_emocional (user_id, analisis, timestamp) 
        VALUES (%s, %s, CURRENT_TIMESTAMP)
    """
    execute_query(sql, (user_id, analisis))