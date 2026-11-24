# Build context is the repo root (see docker-compose.yml) because the
# uv workspace lockfile lives there.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /usr/local/bin/

WORKDIR /workspace

# Manifests only, before the sources below: dependency resolution depends on
# none of our code, so it gets its own layer and survives every source edit.
COPY pyproject.toml uv.lock* /workspace/
COPY services/cloud-sim/pyproject.toml /workspace/services/cloud-sim/

WORKDIR /workspace/services/cloud-sim
RUN uv sync --frozen --no-dev --no-install-workspace --package cloud-sim \
    || uv sync --no-dev --no-install-workspace --package cloud-sim

ENV PATH="/workspace/services/cloud-sim/.venv/bin:/workspace/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

COPY services/cloud-sim /workspace/services/cloud-sim
RUN uv sync --frozen --no-dev --package cloud-sim \
    || uv sync --no-dev --package cloud-sim

EXPOSE 8090
CMD ["uvicorn", "cloud_sim.main:served", "--factory", "--host", "0.0.0.0", "--port", "8090"]
