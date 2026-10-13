-- infra/migrations/sql/0006_association_grant.sql
--
-- Grants ai_engine_ro SELECT, INSERT and DELETE on kb_article_associations.

GRANT SELECT, INSERT, DELETE ON kb_article_associations TO ai_engine_ro;
