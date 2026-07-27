-- infra/migrations/sql/0004_grants_and_audit_lockdown.sql
--
-- Two structural guarantees, both enforced by Postgres rather than by
-- convention:
--
-- 1. ai_engine_ro can SELECT the KB/few-shot tables it needs for
--    retrieval and CANNOT write to any business table — this is what
--    makes ADR-0004's "ai-engine has no DB credentials to write business
--    tables" literally true rather than an aspiration.
-- 2. audit_log is append-only: no application role, including the one
--    core-api itself connects as, can UPDATE or DELETE a row once
--    written.

GRANT SELECT ON kb_articles, kb_chunks, fewshot_examples TO ai_engine_ro;

-- Explicitly nothing else: no INSERT/UPDATE/DELETE, and no grant at all
-- on tickets, routing_decisions, ai_runs, review_items, audit_log, or any
-- other business table. This absence is the point of this file.

REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;

-- REVOKE alone is NOT sufficient here: the role that ran the migrations
-- (app_user) is audit_log's OWNER, and table owners bypass ACL checks in
-- Postgres — a REVOKE against your own table's owner is a no-op. The
-- owning Django migration (apps/dbextras/migrations/0002_finalize.py)
-- still issues that REVOKE, as defense-in-depth and as documentation of
-- intent for any *other* role, but the guarantee that actually holds
-- against app_user itself is this trigger: it rejects UPDATE/DELETE
-- unconditionally, regardless of who is connected or what they own.
CREATE OR REPLACE FUNCTION audit_log_deny_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_log_append_only ON audit_log;
CREATE TRIGGER trg_audit_log_append_only
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_deny_mutation();
