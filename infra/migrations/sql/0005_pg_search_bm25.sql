-- infra/migrations/sql/0005_pg_search_bm25.sql
--
-- Real BM25 over kb_chunks via ParadeDB pg_search (ADR-0013), replacing the
-- `tsv` column, its trigger and its GIN index. Those served `ts_rank_cd`,
-- which has no IDF, under `plainto_tsquery`, which required every ticket
-- word in one chunk: the lexical channel matched nothing on the English
-- golden set.
--
-- Needs the smart-triage-db image (infra/db/Dockerfile), started with
-- shared_preload_libraries=pg_search. On a stock pgvector image the
-- CREATE EXTENSION below fails, and it should: a DB that cannot serve BM25
-- must not look migrated.

DROP TRIGGER IF EXISTS trg_kb_chunks_tsv ON kb_chunks;
DROP FUNCTION IF EXISTS kb_chunks_tsv_update();
DROP INDEX IF EXISTS idx_chunk_tsv;

CREATE EXTENSION IF NOT EXISTS pg_search;

-- The English stemmer ("passwords" matches "password") is a decision tied
-- to the English AWS demo KB. It keeps Vietnamese diacritics, so a
-- Vietnamese corpus needs its own tokenizer and a new decision (ADR-0013).
-- The index is maintained by pg_search on every write, so no trigger is
-- needed and every write path (ORM, raw SQL, psql) stays indexed.
CREATE INDEX IF NOT EXISTS idx_chunk_bm25 ON kb_chunks
    USING bm25 (
        id,
        (content::pdb.unicode_words('stemmer=english')),
        (section_title::pdb.unicode_words('stemmer=english'))
    )
    WITH (key_field = 'id');
