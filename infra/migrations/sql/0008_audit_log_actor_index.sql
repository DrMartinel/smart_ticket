-- infra/migrations/sql/0008_audit_log_actor_index.sql
--
-- Finds a person's recent audit rows of one kind, as the access_denied
-- throttle (PRE-1) and the hourly security alerts (F5) ask for on every
-- refused or limited request.

CREATE INDEX IF NOT EXISTS idx_audit_actor_event
    ON audit_log (actor_id, event, occurred_at);
