"""
database.py — Versión PostgreSQL para Serenity
================================================
Requiere en el .env:
    DATABASE_URL=postgresql://usuario:contraseña@host:5432/serenity_db
"""

import psycopg2
import psycopg2.pool
from datetime import datetime
from config import logger
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL no configurada en el .env")
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=20,
            dsn=DATABASE_URL
        )
    return _pool

def get_conn():
    return get_pool().getconn()

def release_conn(conn):
    get_pool().putconn(conn)


# ── Creación de tablas ─────────────────────────────────────────────────────────

def crear_base_datos():
    """Crea las tablas y los índices necesarios si no existen."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    user_id          BIGINT PRIMARY KEY,
                    username         TEXT,
                    first_name       TEXT,
                    last_name        TEXT,
                    nombre_completo  TEXT,
                    matricula        TEXT,
                    correo           TEXT,
                    telefono         TEXT,
                    registrado       BOOLEAN DEFAULT FALSE,
                    fecha_registro   TIMESTAMPTZ
                );
            """)

            # Migración: agregar columnas si ya existía la tabla sin ellas
            for col, tipo in [
                ("nombre_completo", "TEXT"),
                ("matricula",       "TEXT"),
                ("correo",          "TEXT"),
                ("telefono",        "TEXT"),
                ("registrado",      "BOOLEAN DEFAULT FALSE"),
            ]:
                cur.execute(f"""
                    ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS {col} {tipo};
                """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversaciones (
                    id        BIGSERIAL PRIMARY KEY,
                    user_id   BIGINT,
                    role      TEXT,
                    content   TEXT,
                    timestamp TIMESTAMPTZ
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS alertas (
                    id           BIGSERIAL PRIMARY KEY,
                    user_id      BIGINT,
                    nivel_riesgo TEXT,
                    tema         TEXT,
                    razon        TEXT,
                    timestamp    TIMESTAMPTZ
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS perfil_emocional (
                    id        BIGSERIAL PRIMARY KEY,
                    user_id   BIGINT,
                    timestamp TIMESTAMPTZ,
                    analisis  TEXT
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS dependencias (
                    id        BIGSERIAL PRIMARY KEY,
                    user_id   BIGINT,
                    facultad  TEXT,
                    timestamp TIMESTAMPTZ
                );
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_conv_user    ON conversaciones(user_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_alertas_user ON alertas(user_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_perfil_user  ON perfil_emocional(user_id);")

        conn.commit()
        logger.info("Base de datos PostgreSQL lista.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error al crear la base de datos: {e}")
    finally:
        release_conn(conn)


# ── Operaciones CRUD ───────────────────────────────────────────────────────────

def guardar_usuario(user_id, username, first_name, last_name):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO usuarios (user_id, username, first_name, last_name, fecha_registro)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING;
            """, (user_id, username, first_name, last_name, datetime.now()))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Error guardando usuario: {e}")
    finally:
        release_conn(conn)


def completar_registro(user_id, nombre_completo, matricula, correo, telefono):
    """Guarda los datos de registro del estudiante."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE usuarios
                SET nombre_completo = %s,
                    matricula       = %s,
                    correo          = %s,
                    telefono        = %s,
                    registrado      = TRUE
                WHERE user_id = %s;
            """, (nombre_completo, matricula, correo, telefono, user_id))
        conn.commit()
        logger.info(f"Registro completado para user_id {user_id}")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error completando registro: {e}")
    finally:
        release_conn(conn)


def usuario_registrado(user_id):
    """Verifica si el usuario ya completó el registro."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT registrado FROM usuarios WHERE user_id = %s;
            """, (user_id,))
            row = cur.fetchone()
            return bool(row and row[0])
    except Exception as e:
        logger.error(f"Error verificando registro: {e}")
        return False
    finally:
        release_conn(conn)


def obtener_datos_usuario(user_id):
    """Obtiene los datos completos del usuario para alertas."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, nombre_completo, matricula, correo, telefono
                FROM usuarios WHERE user_id = %s;
            """, (user_id,))
            row = cur.fetchone()
            if row:
                return {
                    "id": row[0],
                    "nombre_completo": row[1],
                    "matricula": row[2],
                    "correo": row[3],
                    "telefono": row[4],
                }
            return {}
    except Exception as e:
        logger.error(f"Error obteniendo datos de usuario: {e}")
        return {}
    finally:
        release_conn(conn)


def guardar_mensaje(user_id, role, content):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO conversaciones (user_id, role, content, timestamp)
                VALUES (%s, %s, %s, %s);
            """, (user_id, role, content, datetime.now()))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Error guardando mensaje: {e}")
    finally:
        release_conn(conn)


def obtener_historial(user_id, limite=10):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT role, content
                FROM conversaciones
                WHERE user_id = %s
                ORDER BY timestamp DESC
                LIMIT %s;
            """, (user_id, limite))
            rows = cur.fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]
    except Exception as e:
        logger.error(f"Error obteniendo historial: {e}")
        return []
    finally:
        release_conn(conn)


def registrar_alerta(user_id, nivel, tema, razon):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO alertas (user_id, nivel_riesgo, tema, razon, timestamp)
                VALUES (%s, %s, %s, %s, %s);
            """, (user_id, nivel, tema, razon, datetime.now()))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Error registrando alerta: {e}")
    finally:
        release_conn(conn)