"""
Definitions only: settings, graph state, node base classes and provider
base classes. Nothing in `core` does I/O or holds business logic —
implementations (nodes, providers, retrieval, the LLM client, graph wiring)
and the data models they produce live outside it and import from here,
never the other way round.
"""
