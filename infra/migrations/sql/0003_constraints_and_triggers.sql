-- infra/migrations/sql/0003_constraints_and_triggers.sql
--
-- Business rules the database itself enforces, so they hold even if
-- application code has a bug: auto-reply can't be authorized without an
-- identifiable approver (ADR-0002), a few-shot example can't enter the
-- pool without explicit user confirmation, and kb_chunks.tsv stays in
-- sync with kb_chunks.content for BM25 (ts_rank_cd) without relying on
-- every write path remembering to update it by hand.

ALTER TABLE kb_articles DROP CONSTRAINT IF EXISTS chk_autoreply_approved;
ALTER TABLE kb_articles ADD CONSTRAINT chk_autoreply_approved
    CHECK (auto_reply_allowed = false OR approved_by IS NOT NULL);

ALTER TABLE fewshot_examples DROP CONSTRAINT IF EXISTS chk_fewshot_confirmed;
ALTER TABLE fewshot_examples ADD CONSTRAINT chk_fewshot_confirmed
    CHECK (user_confirmed = true);

CREATE OR REPLACE FUNCTION kb_chunks_tsv_update() RETURNS trigger AS $$
BEGIN
    -- 'simple' rather than a language-specific config: content is a mix
    -- of Vietnamese and English (spec §0), and Postgres ships no Vietnamese
    -- text search config, so stemming would silently misbehave on VI text.
    NEW.tsv := to_tsvector('simple', coalesce(NEW.content, '') || ' ' || coalesce(NEW.section_title, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_kb_chunks_tsv ON kb_chunks;
CREATE TRIGGER trg_kb_chunks_tsv
    BEFORE INSERT OR UPDATE OF content, section_title ON kb_chunks
    FOR EACH ROW EXECUTE FUNCTION kb_chunks_tsv_update();

-- Backfill any rows that existed before the trigger did.
UPDATE kb_chunks SET tsv = to_tsvector('simple', coalesce(content, '') || ' ' || coalesce(section_title, ''));
