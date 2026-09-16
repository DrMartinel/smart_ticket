# Build context is the repo root (see infra/docker-compose.yml) because
# this service depends on the sibling packages/contracts workspace member.
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /usr/local/bin/

WORKDIR /workspace

# Which reranker checkpoint gets baked in. Must match RERANKER_MODEL /
# RERANKER_REVISION at runtime: the image contains exactly one checkpoint and
# HF_HUB_OFFLINE=1 below makes loading any other one an error rather than a
# silent 2.3GB download mid-ticket.
#
# Pin RERANKER_REVISION to a commit sha. Left at "main" it resolves to whatever
# BAAI last pushed on build day, and a new upstream commit changes the score
# distribution `retrieval.floor` is calibrated against without failing loudly
# (ADR-0005).
ARG RERANKER_MODEL=BAAI/bge-reranker-v2-m3
ARG RERANKER_REVISION=main

# One cache path shared by the build-time bake and the runtime load. Single
# stage, so this ENV persists into the final image and the two agree by
# construction; if this ever becomes multi-stage, COPY the directory (which
# preserves the blobs/ -> snapshots/ symlinks) rather than tar/cp'ing it.
ENV HF_HOME=/opt/hf

# Manifests only, before the sources below: dependency resolution and the model
# bake are expensive (sentence-transformers pulls torch) and depend on none of
# our code, so they get their own layers and survive every source edit.
# Reversing this makes a one-line change in a node re-download the weights.
COPY pyproject.toml uv.lock* /workspace/
COPY packages/contracts/pyproject.toml /workspace/packages/contracts/
COPY services/ai-engine/pyproject.toml /workspace/services/ai-engine/

WORKDIR /workspace/services/ai-engine
RUN uv sync --frozen --no-dev --no-install-workspace --package ai-engine \
    || uv sync --no-dev --no-install-workspace --package ai-engine

ENV PATH="/workspace/services/ai-engine/.venv/bin:/workspace/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Pull the weights into an image layer. The RAM copy this builds is discarded
# when the layer exits — the point is the populated cache underneath, so that no
# container start and no ticket ever touches the network for it. Deliberately
# above HF_HUB_OFFLINE: this is the one step that is *supposed* to hit the hub.
RUN python -c "import sys; from sentence_transformers import CrossEncoder; CrossEncoder(sys.argv[1], revision=sys.argv[2])" \
      "$RERANKER_MODEL" "$RERANKER_REVISION"

# Everything past here is baked, so reaching for the hub at runtime means
# something disagrees — a RERANKER_MODEL/RERANKER_REVISION the image was not
# built with, a volume mounted over HF_HOME, a changed HOME. Offline turns each
# of those into LocalEntryNotFoundError at startup instead of a slow surprise
# download, and closes the ADR-0005 hole where `main` moving upstream swaps the
# checkpoint under a floor calibrated against the old one.
ENV HF_HUB_OFFLINE=1

# Sources last: this is the layer that actually changes between builds.
COPY packages/contracts /workspace/packages/contracts
COPY services/ai-engine /workspace/services/ai-engine
RUN uv sync --frozen --no-dev --package ai-engine || uv sync --no-dev --package ai-engine

EXPOSE 8001
CMD ["uvicorn", "ai_engine.main:app", "--host", "0.0.0.0", "--port", "8001"]
