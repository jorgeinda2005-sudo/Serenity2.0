import os
import json
import psycopg2
import psycopg2.pool
from .config import logger

DATABASE_URL = os.getenv("DATABASE_URL")

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            logger.error("❌ ERROR CRÍTICO: DATABASE_URL está vacía.")
            return None
        try:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=DATABASE_URL,
                connect_timeout=10,
                # ── Keepalives TCP: evitan que Supabase cierre conexiones idle ──
                keepalives=1,
                keepalives_idle=30,    # enviar probe tras 30 s idle
                keepalives_interval=5, # reintentar cada 5 s
                keepalives_count=3,    # 3 fallos = conexión muerta
            )
            logger.info("✅ Pool de Supabase creado correctamente.")
        except Exception as e:
            logger.error(f"❌ FALLO AL CREAR EL POOL: {e}")
            return None
    return _pool


def get_conn():
    """Obtiene una conexión del pool y la verifica antes de devolverla."""
    p = get_pool()
    if not p:
        return None

    conn = None
    try:
        conn = p.getconn()
        if conn is None:
            return None

        # Ping rápido: detecta conexiones que Supabase cerró por idle timeout
        with conn.cursor() as cur:       # FIX 1: cursor cerrado correctamente
            cur.execute("SELECT 1")
        return conn

    except Exception:
        # La conexión estaba muerta; la descartamos y pedimos una nueva
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            try:
                p.putconn(conn)
            except Exception:
                pass

        # Segundo intento con conexión recién creada
        try:
            conn = p.getconn()
            with conn.cursor() as cur:   # FIX 1: idem segundo intento
                cur.execute("SELECT 1")
            return conn
        except Exception as e2:
            logger.error(f"No se pudo obtener una conexión válida: {e2}")
            if conn is not None:
                try:                     # FIX 2: close y putconn separados
                    conn.close()
                except Exception:
                    pass
                try:
                    p.putconn(conn)
                except Exception:
                    pass
            return None


def release_conn(conn):
    """Devuelve la conexión al pool (psycopg2 descarta las cerradas automáticamente)."""
    p = get_pool()
    if p and conn:
        try:
            p.putconn(conn)
        except Exception:
            pass


def execute_query(sql, params=(), fetch=False):
    conn = get_conn()
    if not conn:
        logger.warning("⚠️ Sin conexión disponible para ejecutar la consulta.")
        return [] if fetch else None

    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            result = cur.fetchall() if fetch else None
        conn.commit()
        return result

    except Exception as e:
        logger.error(f"🔥 ERROR DB: {e} | SQL: {sql[:80]}")
        # ── FIX: rollback envuelto en try/except propio ──────────────────────
        # Si rollback() lanza (conexión rota), cerramos la conexión para que
        # el pool la descarte y no quede "envenenado".
        try:
            conn.rollback()
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
        return [] if fetch else None

    finally:
        release_conn(conn)


# ─────────────────────────────────────────────────────────────────────────────
# Funciones CRUD
# ─────────────────────────────────────────────────────────────────────────────

def crear_base_datos():
    res = execute_query("SELECT 1;", fetch=True)
    if res is not None:
        logger.info("SERENITY: Conexion con Supabase verificada.")
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS correos_enviados (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT,
                psicologo_id BIGINT,
                destinatario TEXT NOT NULL,
                facultad TEXT,
                asunto TEXT,
                motivo TEXT,
                estado TEXT NOT NULL,
                error TEXT,
                timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS alertas_contexto (
                id BIGSERIAL PRIMARY KEY,
                alerta_id BIGINT UNIQUE NOT NULL,
                user_id BIGINT NOT NULL,
                mensaje_detonante TEXT,
                mensajes_previos_json JSONB,
                timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
    else:
        logger.error("SERENITY: No se pudo verificar la conexion inicial.")


def guardar_usuario(user_id, username, first_name, last_name):
    """Inserta el usuario si no existe. Safe to call multiple times."""
    execute_query(
        "INSERT INTO usuarios (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING;",
        (user_id, username or ""),
    )


def completar_registro(user_id, nombre, matricula, correo, telefono):
    execute_query(
        "UPDATE usuarios SET nombre_completo=%s, matricula=%s, correo=%s, telefono=%s, registrado=TRUE WHERE user_id=%s",
        (nombre, matricula, correo, telefono, user_id),
    )


def usuario_registrado(user_id):
    res = execute_query("SELECT registrado FROM usuarios WHERE user_id=%s", (user_id,), fetch=True)
    return bool(res and res[0][0])


def obtener_datos_usuario(user_id):
    res = execute_query(
        "SELECT user_id, username, nombre_completo, matricula, correo, telefono, facultad FROM usuarios WHERE user_id=%s",
        (user_id,),
        fetch=True,
    )
    if res:
        r = res[0]
        return {
            "id": r[0], "username": r[1], "nombre_completo": r[2],
            "matricula": r[3], "correo": r[4], "telefono": r[5], "facultad": r[6],
        }
    return {}


def guardar_mensaje(user_id, role, content):
    """Guarda un turno de conversación. Garantiza que el usuario exista antes."""
    # Upsert defensivo: si el usuario escribe sin haber hecho /start,
    # lo creamos para evitar FK violation en conversaciones.
    execute_query(
        "INSERT INTO usuarios (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING;",
        (user_id, ""),
    )
    execute_query(
        "INSERT INTO conversaciones (user_id, role, content) VALUES (%s, %s, %s)",
        (user_id, role, content),
    )


def obtener_historial(user_id, limite=10):
    res = execute_query(
        "SELECT role, content FROM conversaciones WHERE user_id=%s ORDER BY timestamp DESC LIMIT %s",
        (user_id, limite),
        fetch=True,
    )
    return [{"role": r[0], "content": r[1]} for r in reversed(res or [])]


def registrar_alerta(user_id, nivel_riesgo, tema, razon):
    res = execute_query(
        "INSERT INTO alertas (user_id, nivel_riesgo, tema, razon) VALUES (%s, %s, %s, %s) RETURNING id",
        (user_id, nivel_riesgo, tema, razon),
        fetch=True,
    )
    return res[0][0] if res else None


def contar_mensajes_usuario(user_id):
    res = execute_query(
        "SELECT COUNT(*) FROM conversaciones WHERE user_id=%s AND role='user'",
        (user_id,),
        fetch=True,
    )
    return res[0][0] if res else 0


def registrar_dependencia(user_id, nivel, reporte):
    execute_query(
        "INSERT INTO dependencias (user_id, nivel, reporte, timestamp) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
        (user_id, nivel, reporte),
    )


def registrar_perfil_emocional(user_id, analisis):
    execute_query(
        "INSERT INTO perfil_emocional (user_id, analisis, timestamp) VALUES (%s, %s, CURRENT_TIMESTAMP)",
        (user_id, analisis),
    )


def obtener_psicologos_por_facultad(facultad):
    res = execute_query(
        """
        SELECT p.id, p.nombre, p.correo
        FROM psicologos p
        JOIN psicologos_facultades pf ON pf.psicologo_id = p.id
        WHERE p.activo=TRUE
          AND COALESCE(NULLIF(p.correo, ''), '') <> ''
          AND pf.facultad=%s
        """,
        (facultad,),
        fetch=True,
    )
    return [{"id": r[0], "nombre": r[1], "correo": r[2]} for r in (res or [])]


def registrar_correo_enviado(user_id, psicologo_id, destinatario, facultad, asunto, motivo, estado, error=None):
    execute_query(
        """
        INSERT INTO correos_enviados
        (user_id, psicologo_id, destinatario, facultad, asunto, motivo, estado, error, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        """,
        (user_id, psicologo_id, destinatario, facultad, asunto, motivo, estado, error),
    )


def registrar_contexto_alerta(alerta_id, user_id):
    res = execute_query(
        """
        SELECT id, content, TO_CHAR(timestamp AT TIME ZONE 'America/Mexico_City', 'DD/MM/YYYY HH24:MI') AS ts
        FROM conversaciones
        WHERE user_id=%s AND role='user'
        ORDER BY timestamp DESC
        LIMIT 6
        """,
        (user_id,),
        fetch=True,
    )
    if not res:
        return

    detonante = res[0][1]

    def _respuesta_serenity(user_msg_id):
        ans = execute_query(
            """
            SELECT content
            FROM conversaciones
            WHERE user_id=%s
              AND role='assistant'
              AND id > %s
            ORDER BY id ASC
            LIMIT 1
            """,
            (user_id, user_msg_id),
            fetch=True,
        )
        return ans[0][0] if ans else ""

    previos = []
    for r in res[1:]:
        previos.append({
            "mensaje": r[1],
            "fecha": r[2],
            "respuesta_serenity": _respuesta_serenity(r[0]),
        })

    execute_query(
        """
        INSERT INTO alertas_contexto (alerta_id, user_id, mensaje_detonante, mensajes_previos_json, timestamp)
        VALUES (%s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
        ON CONFLICT (alerta_id) DO UPDATE
        SET mensaje_detonante=EXCLUDED.mensaje_detonante,
            mensajes_previos_json=EXCLUDED.mensajes_previos_json
        """,
        (alerta_id, user_id, detonante, json.dumps(previos, ensure_ascii=False)),
    )
