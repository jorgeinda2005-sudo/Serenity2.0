import sqlite3
from datetime import datetime
from config import db_file, logger

def crear_base_datos():
    """Crea las tablas necesarias si no existen."""
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        # Tabla de usuarios
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                fecha_registro DATETIME
            )
        ''')
        
        # Tabla de conversaciones (Historial para la IA)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                content TEXT,
                timestamp DATETIME
            )
        ''')

        # Tabla de alertas (Detección de riesgo)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alertas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                nivel_riesgo TEXT,
                tema TEXT,
                razon TEXT,
                timestamp DATETIME
            )
        ''')

        # Tabla de perfil emocional (Análisis a largo plazo)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS perfil_emocional (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                timestamp DATETIME,
                analisis TEXT
            )
        ''')

        # Tabla de dependencias (Consentimiento para compartir datos)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS dependencias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                facultad TEXT,
                timestamp DATETIME
            )
        ''')

        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error al crear la base de datos: {e}")

def guardar_usuario(user_id, username, first_name, last_name):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO usuarios (user_id, username, first_name, last_name, fecha_registro)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, last_name, datetime.now()))
    conn.commit()
    conn.close()

def guardar_mensaje(user_id, role, content):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO conversaciones (user_id, role, content, timestamp)
        VALUES (?, ?, ?, ?)
    ''', (user_id, role, content, datetime.now()))
    conn.commit()
    conn.close()

def obtener_historial(user_id, limite=10):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT role, content FROM conversaciones 
        WHERE user_id = ? 
        ORDER BY timestamp DESC LIMIT ?
    ''', (user_id, limite))
    rows = cursor.fetchall()
    conn.close()
    # Invertimos para que el orden sea cronológico (viejo -> nuevo)
    return [{"role": r, "content": c} for r, c in reversed(rows)]

def registrar_alerta(user_id, nivel, tema, razon):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO alertas (user_id, nivel_riesgo, tema, razon, timestamp)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, nivel, tema, razon, datetime.now()))
    conn.commit()
    conn.close()