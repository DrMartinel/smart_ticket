# syntax=docker/dockerfile:1.7
#
# Postgres 17 + pgvector (the stock base) + ParadeDB pg_search for real BM25
# over kb_chunks (ADR-0013). Pinned to an exact release AND its checksum:
# pg_search changes often, and an unpinned upgrade could change how the
# lexical channel ranks without any code change here.
#
# pg_search must be in shared_preload_libraries. That is a server start
# flag, so it is set by the compose `command`, not here: a flag works on an
# existing data volume, where an edited postgresql.conf.sample would not.
#
# License: pg_search is AGPL-3.0 (see ADR-0013, Consequences).

FROM pgvector/pgvector:pg17

ARG PG_SEARCH_VERSION=0.25.10
ADD --checksum=sha256:84bd2ad8615b0b3f539234dde5bf67e48240ad1fab8df2228ac6023a67501471 \
    https://github.com/paradedb/paradedb/releases/download/v${PG_SEARCH_VERSION}/postgresql-17-pg-search_${PG_SEARCH_VERSION}-1PARADEDB-bookworm_amd64.deb \
    /tmp/pg_search.deb

# The base image ships without apt lists, and the .deb depends on
# libopenblas0 from Debian main.
RUN apt-get update \
    && apt-get install -y --no-install-recommends /tmp/pg_search.deb \
    && rm -rf /var/lib/apt/lists/* /tmp/pg_search.deb
