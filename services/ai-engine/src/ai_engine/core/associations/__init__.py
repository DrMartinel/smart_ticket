"""
The offline `entity_graph` build (ADR-0018). Run from the host, never on
the request path:

- `adapter.py`: LightRAG wired to ai-engine's own chat settings and embedder.
- `policy.py`: the versioned entity policy, `core/prompts/kb_entities.v*.yaml`.
- `scoring.py`: mentions -> article-to-article rows, pure.
- `build.py`: the CLI that syncs, extracts, exports and scores.

Nothing here writes to the database: the build hands core-api a file, and
`manage.py load_associations` loads it (ADR-0004).
"""
