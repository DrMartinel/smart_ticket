"""
The offline `entity_graph` build (ADR-0018). Run from the host, never on
the request path. Per page section, DeepSeek names each problem the section
helps solve, its remedy, and where the remedy is written; a remedy written
on another page the text names is a pointer, and resolved to a KB page it
is an edge from the page with the problem to the page with the fix.

- `policy.py`: the versioned prompt, `core/prompts/kb_entity_graph.v*.yaml`.
- `sections.py`: a page cut into sections, links stripped to their text.
- `extract.py`: one JSON call per section, replies cached by content.
- `resolve.py`: a named page resolved to one KB page, or dropped.
- `build.py`: the CLI that extracts, resolves, scores and exports.

Nothing here writes to the database: the build hands core-api a file, and
`manage.py load_associations` loads it (ADR-0004).
"""
