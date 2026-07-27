-- infra/migrations/sql/0002_indexes.sql
--
-- Applied once the tables below exist (Django's initial migrations run
-- first). HNSW indexes, the partial pending-review index, and the audit
-- trace index — everything the ORM's Meta.indexes could express less
-- precisely or not at all (partial HNSW in particular).

CREATE INDEX IF NOT EXISTS idx_tickets_status_created
    ON tickets (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tickets_incident
    ON tickets (incident_id) WHERE incident_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ticket_emb
    ON ticket_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_quarantine_expiry
    ON pii_quarantine (expires_at);

CREATE INDEX IF NOT EXISTS idx_chunk_emb
    ON kb_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_chunk_tsv
    ON kb_chunks USING gin (tsv);

CREATE INDEX IF NOT EXISTS idx_ai_runs_ticket
    ON ai_runs (ticket_id, created_at DESC);

-- Only current, un-retracted few-shot examples are ever selected — the
-- partial predicate keeps the index small and keeps retracted examples
-- structurally unreachable rather than merely "filtered out by a WHERE
-- clause someone might forget to add".
CREATE INDEX IF NOT EXISTS idx_fewshot_active
    ON fewshot_examples USING hnsw (embedding vector_cosine_ops)
    WHERE retracted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_review_pending
    ON review_items (queue, priority, created_at)
    WHERE state = 'pending';

CREATE INDEX IF NOT EXISTS idx_audit_ticket
    ON audit_log (ticket_id, occurred_at);

CREATE INDEX IF NOT EXISTS idx_audit_trace
    ON audit_log (trace_id);
