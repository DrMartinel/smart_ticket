"""
The offline `remedy_pointer` build (ADR-0018 amendment, 2026-10-10): per
page section, DeepSeek names each problem the section helps solve, its
remedy, and where the remedy is written. A remedy written on another page
the text names is a pointer; resolved to a KB page, it is an edge from the
page that names the problem to the page that fixes it. No LightRAG: one
JSON call per section, cached by content.
"""
