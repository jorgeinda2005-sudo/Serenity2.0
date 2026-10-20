-- Serenity 2.0: identidades de Messenger y deduplicacion de webhooks.
-- Requiere que public.usuarios(user_id) exista como BIGINT PRIMARY KEY.
-- No elimina ni modifica conversaciones, alertas ni usuarios existentes.

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.usuarios') IS NULL THEN
        RAISE EXCEPTION
            'No existe public.usuarios. Ejecuta primero la migracion base de Serenity.';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'usuarios'
          AND column_name = 'user_id'
          AND data_type = 'bigint'
    ) THEN
        RAISE EXCEPTION
            'public.usuarios.user_id debe existir y ser BIGINT para esta migracion.';
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS public.serenity_channel_identities (
    channel     TEXT        NOT NULL,
    external_id TEXT        NOT NULL,
    user_id     BIGINT      NOT NULL
                            REFERENCES public.usuarios(user_id)
                            ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT serenity_channel_identities_pk
        PRIMARY KEY (channel, external_id),
    CONSTRAINT serenity_channel_identities_channel_user_uk
        UNIQUE (channel, user_id),
    CONSTRAINT serenity_channel_identities_channel_ck
        CHECK (channel IN ('telegram', 'messenger'))
);

CREATE TABLE IF NOT EXISTS public.serenity_processed_events (
    channel      TEXT        NOT NULL,
    event_id     TEXT        NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT serenity_processed_events_pk
        PRIMARY KEY (channel, event_id),
    CONSTRAINT serenity_processed_events_channel_ck
        CHECK (channel IN ('telegram', 'messenger'))
);

CREATE INDEX IF NOT EXISTS serenity_channel_identities_user_idx
    ON public.serenity_channel_identities(user_id);

-- Estas tablas contienen identificadores de plataforma y actividad de usuarios.
-- El backend se conecta directamente a PostgreSQL; el acceso por la API REST
-- queda cerrado para anon/authenticated mientras no se definan politicas.
ALTER TABLE public.serenity_channel_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.serenity_processed_events ENABLE ROW LEVEL SECURITY;

COMMIT;
