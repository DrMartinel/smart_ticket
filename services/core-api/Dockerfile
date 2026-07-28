# Build context is the repo root (see infra/docker-compose.yml) because
# this service depends on the sibling packages/contracts workspace member.
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /usr/local/bin/

WORKDIR /workspace

COPY pyproject.toml uv.lock* /workspace/
COPY packages/contracts /workspace/packages/contracts
COPY services/core-api /workspace/services/core-api
# apps/dbextras/migrations/0002_finalize.py reads raw SQL from here at
# migrate time (spec §2: infra/migrations/sql/ is the canonical location
# for what the ORM can't express — partial indexes, CHECK constraints,
# triggers, role grants).
COPY infra/migrations/sql /workspace/infra/migrations/sql

WORKDIR /workspace/services/core-api
RUN uv sync --frozen --no-dev --package core-api || uv sync --no-dev --package core-api

ENV PATH="/workspace/services/core-api/.venv/bin:/workspace/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

RUN chmod +x docker-entrypoint.sh

EXPOSE 8000
CMD ["./docker-entrypoint.sh"]
