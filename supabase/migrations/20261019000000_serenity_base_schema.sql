-- Esquema base de Serenity para una instancia PostgreSQL/Supabase nueva.
-- Crea solo tablas e indices; no crea cuentas ni inserta datos personales.

BEGIN;

CREATE TABLE IF NOT EXISTS public.usuarios (
    user_id         BIGINT PRIMARY KEY,
    username        TEXT NOT NULL DEFAULT '',
    first_name      TEXT,
    last_name       TEXT,
    nombre_completo TEXT,
    matricula       TEXT,
    correo          TEXT,
    telefono        TEXT,
    facultad        TEXT,
    registrado      BOOLEAN NOT NULL DEFAULT FALSE,
    fecha_registro  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.conversaciones (
    id        BIGSERIAL PRIMARY KEY,
    user_id   BIGINT NOT NULL REFERENCES public.usuarios(user_id) ON DELETE CASCADE,
    role      TEXT NOT NULL,
    content   TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.alertas (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES public.usuarios(user_id) ON DELETE CASCADE,
    nivel_riesgo TEXT NOT NULL,
    tema         TEXT NOT NULL,
    razon        TEXT NOT NULL DEFAULT '',
    timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.perfil_emocional (
    id        BIGSERIAL PRIMARY KEY,
    user_id   BIGINT NOT NULL REFERENCES public.usuarios(user_id) ON DELETE CASCADE,
    analisis  TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.dependencias (
    id        BIGSERIAL PRIMARY KEY,
    user_id   BIGINT NOT NULL REFERENCES public.usuarios(user_id) ON DELETE CASCADE,
    nivel     TEXT NOT NULL,
    reporte   TEXT NOT NULL DEFAULT '',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.psicologos (
    id              BIGSERIAL PRIMARY KEY,
    nombre          TEXT NOT NULL,
    usuario         TEXT NOT NULL UNIQUE,
    password_hash   TEXT,
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    rol             TEXT NOT NULL DEFAULT 'psicologo',
    primer_acceso   BOOLEAN NOT NULL DEFAULT TRUE,
    codigo_temporal TEXT,
    correo          TEXT
);

CREATE TABLE IF NOT EXISTS public.psicologos_facultades (
    id            BIGSERIAL PRIMARY KEY,
    psicologo_id  BIGINT NOT NULL REFERENCES public.psicologos(id) ON DELETE CASCADE,
    facultad      TEXT NOT NULL,
    UNIQUE (psicologo_id, facultad)
);

CREATE TABLE IF NOT EXISTS public.correos_enviados (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT,
    psicologo_id  BIGINT,
    destinatario  TEXT NOT NULL,
    facultad      TEXT,
    asunto        TEXT,
    motivo        TEXT,
    estado        TEXT NOT NULL,
    error         TEXT,
    timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.alertas_contexto (
    id                    BIGSERIAL PRIMARY KEY,
    alerta_id             BIGINT NOT NULL UNIQUE REFERENCES public.alertas(id) ON DELETE CASCADE,
    user_id               BIGINT NOT NULL REFERENCES public.usuarios(user_id) ON DELETE CASCADE,
    mensaje_detonante     TEXT,
    mensajes_previos_json JSONB,
    timestamp             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conversaciones_user_timestamp
    ON public.conversaciones(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_alertas_user_timestamp
    ON public.alertas(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_perfil_emocional_user_timestamp
    ON public.perfil_emocional(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_dependencias_user_timestamp
    ON public.dependencias(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_psicologos_facultades_facultad
    ON public.psicologos_facultades(facultad);

-- Los datos emocionales y de acceso no se exponen por la API REST de Supabase.
-- El backend usa DATABASE_URL con un rol de servidor/propietario.
ALTER TABLE public.usuarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alertas ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.perfil_emocional ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dependencias ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.psicologos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.psicologos_facultades ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.correos_enviados ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alertas_contexto ENABLE ROW LEVEL SECURITY;

COMMIT;
