"""
The offline `entity_graph` build (ADR-0018, ADR-0025).

- `policy.py`: `EntityGraphPolicy`, the versioned prompt and its bounds.
- `sections.py`: `SectionSplitter`, a page cut into sections.
- `extract.py`: `PairExtractor`, each section's pairs from the model or the cache.
- `resolve.py`: `PageIndex`, a named page resolved to one KB page.
- `build.py`: `EntityGraphBuild`, the CLI that extracts, scores and writes the graph.
"""
