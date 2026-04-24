import os
import psycopg2
from psycopg2 import pool
from config import logger
from datetime import datetime

# URL de conexión a Supabase (debe estar en tus variables de entorno)
DATABASE_URL = os.getenv("DATABASE_URL")

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            logger.error("DATABASE_URL no configurada en el .env")
            return None
        # Usamos un pool para manejar conexiones a Supabase sin que se caiga
        _pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=DATABASE_URL)
    return _pool

def get_conn():
    """Obtiene una conexión del pool."""
    pool = get_pool()
    if pool:
        return pool.getconn()
    return None

def release_conn(conn):
    """Devuelve la conexión al pool."""
    pool = get_pool()
    if pool and conn:
        pool.putconn(conn)

def execute_query(sql, params=(), fetch=False):
    """Ejecuta una consulta SQL de forma segura, cerrando conexiones rotas e imprimiendo errores."""
    conn = get_conn()
    if not conn:
        print("❌ ERROR CRÍTICO: No se pudo obtener conexión del Pool")
        return [] if fetch else None
    
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if fetch:
                result = cur.fetchall()
            else:
                result = None
        conn.commit()
        return result
    except Exception as e:
        conn.rollback()
        # ESTA LÍNEA ES CLAVE: Imprime el error real en los logs de Railway
        print(f"🔥 ERROR DE BASE DE DATOS: {str(e)}") 
        try:
            conn.close()
        except:
            pass
        return [] if fetch else None
    finally:
        release_conn(conn)

# ══════════════════════════════════════════════════════════════════════════════
# FUNCIONES EXPORTADAS PARA MAIN.PY Y AI_CORE.PY
# ══════════════════════════════════════════════════════════════════════════════

def crear_base_datos():
    """Crea las tablas en Supabase si no existen."""
    sql = """
    CREATE TABLE IF NOT EXISTS usuarios (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        nombre_completo TEXT,
        matricula TEXT,
        correo TEXT,
        telefono TEXT,
        facultad TEXT,
        registrado BOOLEAN DEFAULT FALSE,
        fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS conversaciones (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        role TEXT,
        content TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS alertas (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        tema TEXT,
        razon TEXT,
        nivel_riesgo TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS dependencias (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        nivel TEXT,
        reporte TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS perfil_emocional (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        analisis TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    execute_query(sql)
    logger.info("Base de datos de Supabase verificada/creada.")

def guardar_usuario(user_id, username, first_name, last_name):
    """Guarda el usuario inicial si no existe."""
    sql = """
    INSERT INTO usuarios (user_id, username) 
    VALUES (%s, %s) 
    ON CONFLICT (user_id) DO NOTHING;
    """
    execute_query(sql, (user_id, username))

def completar_registro(user_id, nombre, matricula, correo, telefono):
    """Actualiza los datos del alumno tras el flujo de registro."""
    sql = """
    UPDATE usuarios 
    SET nombre_completo=%s, matricula=%s, correo=%s, telefono=%s, registrado=TRUE 
    WHERE user_id=%s
    """
    execute_query(sql, (nombre, matricula, correo, telefono, user_id))

def usuario_registrado(user_id):
    """Devuelve True si el usuario ya completó su registro de datos."""
    sql = "SELECT registrado FROM usuarios WHERE user_id=%s"
    res = execute_query(sql, (user_id,), fetch=True)
    if res and res[0][0] is True:
        return True
    return False

def obtener_datos_usuario(user_id):
    """Devuelve un diccionario con los datos del usuario para el reporte."""
    sql = "SELECT user_id, username, nombre_completo, matricula, correo, telefono, facultad FROM usuarios WHERE user_id=%s"
    res = execute_query(sql, (user_id,), fetch=True)
    if res:
        row = res[0]
        return {
            "id": row[0],
            "username": row[1],
            "nombre_completo": row[2] or "No registrado",
            "matricula": row[3] or "No registrado",
            "correo": row[4] or "No registrado",
            "telefono": row[5] or "No registrado",
            "facultad": row[6] or "No asignada"
        }
    return {}

def guardar_mensaje(user_id, role, content):
    """Guarda un mensaje en el historial del chat."""
    sql = "INSERT INTO conversaciones (user_id, role, content) VALUES (%s, %s, %s)"
    execute_query(sql, (user_id, role, content))

def obtener_historial(user_id, limite=10):
    """Obtiene los últimos N mensajes para darle contexto a la IA."""
    sql = "SELECT role, content FROM conversaciones WHERE user_id=%s ORDER BY timestamp DESC LIMIT %s"
    res = execute_query(sql, (user_id, limite), fetch=True)
    
    # Invertimos la lista para que queden en orden cronológico correcto para la API
    historial = [{"role": row[0], "content": row[1]} for row in reversed(res)]
    return historial

def registrar_alerta(user_id, nivel_riesgo, tema, razon):
    """Guarda una alerta detectada por la IA."""
    sql = "INSERT INTO alertas (user_id, nivel_riesgo, tema, razon) VALUES (%s, %s, %s, %s)"
    execute_query(sql, (user_id, nivel_riesgo, tema, razon))