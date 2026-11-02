-- infra/migrations/sql/0009_graph_feature_grants.sql
--
-- Grants ai_engine_ro SELECT on kb_association_overrides, and SELECT plus
-- UPDATE of state, done_at and build_id on kb_graph_rebuild_requests (ADR-0037).

GRANT SELECT ON kb_association_overrides TO ai_engine_ro;
GRANT SELECT ON kb_graph_rebuild_requests TO ai_engine_ro;
GRANT UPDATE (state, done_at, build_id) ON kb_graph_rebuild_requests TO ai_engine_ro;
