# Build context is the repo root (see infra/docker-compose.yml) because
# this service depends on the sibling packages/contracts workspace member.
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /usr/local/bin/

WORKDIR /workspace

# No model weights live in this image: every model is served by vLLM
# (ADR-0009).

# Manifests only, before the sources below: dependency resolution depends on
# none of our code, so it gets its own layer and survives every source edit.
COPY pyproject.toml uv.lock* /workspace/
COPY packages/contracts/pyproject.toml /workspace/packages/contracts/
COPY services/ai-engine/pyproject.toml /workspace/services/ai-engine/

WORKDIR /workspace/services/ai-engine
RUN uv sync --frozen --no-dev --no-install-workspace --package ai-engine \
    || uv sync --no-dev --no-install-workspace --package ai-engine

ENV PATH="/workspace/services/ai-engine/.venv/bin:/workspace/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Sources last: this is the layer that actually changes between builds.
COPY packages/contracts /workspace/packages/contracts
COPY services/ai-engine /workspace/services/ai-engine
RUN uv sync --frozen --no-dev --package ai-engine || uv sync --no-dev --package ai-engine

EXPOSE 8001
CMD ["uvicorn", "ai_engine.main:app", "--host", "0.0.0.0", "--port", "8001"]
