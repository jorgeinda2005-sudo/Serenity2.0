"""
migrar_a_postgres.py
====================
Script para migrar los datos de SQLite a PostgreSQL en el proyecto Serenity.

PASO 1: Instala la dependencia
    pip install psycopg2-binary python-dotenv

PASO 2: Agrega en tu .env
    DATABASE_URL=postgresql://usuario:contraseña@host:5432/serenity_db

    Ejemplo con Supabase:
        DATABASE_URL=postgresql://postgres:tupassword@db.xxxx.supabase.co:5432/postgres
    
    Ejemplo con Railway:
        DATABASE_URL=postgresql://postgres:tupassword@containers-us-west-xxx.railway.app:5432/railway

PASO 3: Ejecuta este script UNA sola vez
    python migrar_a_postgres.py
"""

import sqlite3
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

# ── Rutas ─────────────────────────────────────────────────────────────────────
SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "serenity.db")
DATABASE_URL = os.getenv("DATABASE_URL", "")


def conectar_postgres():
    if not DATABASE_URL:
        raise ValueError(
            "No se encontró DATABASE_URL en el .env. "
            "Agrégala antes de correr la migración."
        )
    return psycopg2.connect(DATABASE_URL)


def crear_tablas_postgres(pg_conn):
    """Recrea las tablas en PostgreSQL con tipos de datos optimizados."""
    with pg_conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                user_id     BIGINT PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                last_name   TEXT,
                fecha_registro TIMESTAMPTZ
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversaciones (
                id          BIGSERIAL PRIMARY KEY,
                user_id     BIGINT,
                role        TEXT,
                content     TEXT,
                timestamp   TIMESTAMPTZ
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

        # Índices para consultas rápidas por usuario
        cur.execute("CREATE INDEX IF NOT EXISTS idx_conv_user ON conversaciones(user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_alertas_user ON alertas(user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_perfil_user ON perfil_emocional(user_id);")

    pg_conn.commit()
    print("✅ Tablas creadas en PostgreSQL")


def migrar_tabla(sqlite_conn, pg_conn, tabla, columnas):
    """Migra una tabla completa de SQLite a PostgreSQL."""
    sqlite_cur = sqlite_conn.cursor()
    sqlite_cur.execute(f"SELECT {', '.join(columnas)} FROM {tabla}")
    filas = sqlite_cur.fetchall()

    if not filas:
        print(f"   ⚠️  {tabla}: sin datos que migrar")
        return

    placeholders = ", ".join(["%s"] * len(columnas))
    cols = ", ".join(columnas)
    
    with pg_conn.cursor() as pg_cur:
        # ON CONFLICT DO NOTHING evita duplicados si se corre el script dos veces
        pg_cur.executemany(
            f"INSERT INTO {tabla} ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
            filas
        )
    pg_conn.commit()
    print(f"   ✅ {tabla}: {len(filas)} registros migrados")


def main():
    print("\n🚀 Iniciando migración Serenity: SQLite → PostgreSQL\n")

    # Verificar que exista el archivo SQLite
    if not os.path.exists(SQLITE_PATH):
        print(f"❌ No se encontró serenity.db en: {SQLITE_PATH}")
        return

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    pg_conn = conectar_postgres()

    try:
        print("📋 Creando estructura en PostgreSQL...")
        crear_tablas_postgres(pg_conn)

        print("\n📦 Migrando datos...\n")
        migrar_tabla(sqlite_conn, pg_conn, "usuarios",
                     ["user_id", "username", "first_name", "last_name", "fecha_registro"])
        
        migrar_tabla(sqlite_conn, pg_conn, "conversaciones",
                     ["id", "user_id", "role", "content", "timestamp"])
        
        migrar_tabla(sqlite_conn, pg_conn, "alertas",
                     ["id", "user_id", "nivel_riesgo", "tema", "razon", "timestamp"])
        
        migrar_tabla(sqlite_conn, pg_conn, "perfil_emocional",
                     ["id", "user_id", "timestamp", "analisis"])
        
        migrar_tabla(sqlite_conn, pg_conn, "dependencias",
                     ["id", "user_id", "facultad", "timestamp"])

        print("\n🎉 ¡Migración completada exitosamente!")
        print("   Ahora actualiza database.py con la nueva versión para PostgreSQL.\n")

    except Exception as e:
        pg_conn.rollback()
        print(f"\n❌ Error durante la migración: {e}")
        raise
    finally:
        sqlite_conn.close()
        pg_conn.close()


if __name__ == "__main__":
    main()
