-- infra/migrations/sql/0007_pii_access_log_lockdown.sql
--
-- pii_access_log is append-only (F5, BR-F5-06), like audit_log in 0004:
-- a REVOKE for every other role, and a trigger that refuses UPDATE and
-- DELETE for every role, the table's owner included.

REVOKE UPDATE, DELETE ON pii_access_log FROM PUBLIC;

CREATE OR REPLACE FUNCTION pii_access_log_deny_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'pii_access_log is append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_pii_access_log_append_only ON pii_access_log;
CREATE TRIGGER trg_pii_access_log_append_only
    BEFORE UPDATE OR DELETE ON pii_access_log
    FOR EACH ROW EXECUTE FUNCTION pii_access_log_deny_mutation();
