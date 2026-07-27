-- infra/migrations/sql/0001_extensions_and_roles.sql
--
-- Extensions + the read-only role that makes ADR-0004's permission
-- boundary real. This file intentionally does NOT set a password for
-- ai_engine_ro — the owning Django migration (apps/tickets, first
-- migration) does that via a parameterized RunPython step so the
-- password never appears in a file that gets committed to git.
--
-- Applied via Django's migrations.RunSQL so `manage.py migrate` remains
-- the single entry point (spec §2 rule 1 / rule 3 discipline extended to
-- infra).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- fuzzy quote matching (validator, §6.4)

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_engine_ro') THEN
        CREATE ROLE ai_engine_ro NOLOGIN;
    END IF;
END
$$;

-- CONNECT is granted to PUBLIC by default in Postgres, so ai_engine_ro can
-- connect once the owning migration ALTERs it to LOGIN with a password.
-- No database-name literal is hardcoded here on purpose — POSTGRES_DB is
-- an env-configurable value (see infra/.env.example).
