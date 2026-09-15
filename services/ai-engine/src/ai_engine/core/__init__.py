"""
Everything the graph's nodes are built on: settings, graph state, node base
classes, and the providers, retrieval and LLM client the nodes call — both
their definitions (`providers/base.py`) and their implementations.

Outside `core` is only the graph itself (`graph/`: nodes, builder, wiring)
and the FastAPI app (`main.py`). They import from `core`; nothing in `core`
imports from them.
"""
