-- infra/migrations/sql/0006_association_grant.sql
--
-- ai_engine_ro reads kb_article_associations for link expansion (ADR-0018,
-- narrowing ADR-0004 by one table). SELECT only, as for the KB tables in
-- 0004: core-api writes every association, ai-engine none.
--
-- A file of its own, not an edit to 0004: 0004 has already been applied to
-- existing databases, and Django will not re-run a migration it has
-- recorded.

GRANT SELECT ON kb_article_associations TO ai_engine_ro;
