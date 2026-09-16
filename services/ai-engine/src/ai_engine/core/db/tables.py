"""
Query-building descriptions of the three tables `ai_engine_ro` may read
(ADR-0004, ADR-0008). NOT the schema.

The schema is owned by core-api — its Django models plus
infra/migrations/sql/ — and these classes are deliberately partial: they
declare only the columns ai-engine selects or filters on, so an unused column
changing in core-api needs no edit here. Three rules follow from that:

- Never call `Base.metadata.create_all()` (or `drop_all`). These are not
  full table definitions; the SELECT-only role would reject the DDL anyway,
  but it must not be attempted.
- Never instantiate these classes or `session.add()` them. ai-engine has no
  write authority; queries select columns and get plain rows back.
- Never add a table here that isn't in 0004_grants_and_audit_lockdown.sql's
  SELECT grant. A business table appearing in this module is the ADR-0004
  boundary eroding in code before it fails at the database.

`tests/test_db_tables.py` pins the table set and the absence of DDL/write
calls; nothing can pin "never instantiated", so that one is on review.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ai_engine.core.providers.embeddings import EMBED_DIM


class Base(DeclarativeBase):
    """ai-engine's own metadata: exactly the tables `ai_engine_ro` may read,
    and nothing else."""


class KbArticle(Base):
    __tablename__ = "kb_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str]
    # Read for the log-only `TrustSignals.policy` block. The authoritative
    # auto-reply check is core-api's (ADR-0002), never this read.
    auto_reply_allowed: Mapped[bool]
    risk_tier: Mapped[str]
    is_active: Mapped[bool]


class KbChunk(Base):
    __tablename__ = "kb_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("kb_articles.id"))
    content: Mapped[str]
    embedding: Mapped[Any] = mapped_column(VECTOR(EMBED_DIM), nullable=True)
    # Maintained by a Postgres trigger (0003_constraints_and_triggers.sql).
    tsv: Mapped[Any] = mapped_column(TSVECTOR, nullable=True)


class FewshotExample(Base):
    __tablename__ = "fewshot_examples"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str]
    input_text: Mapped[str]
    output_json: Mapped[Any] = mapped_column(JSONB)
    embedding: Mapped[Any] = mapped_column(VECTOR(EMBED_DIM), nullable=True)
    expires_at: Mapped[datetime]
    retracted_at: Mapped[datetime | None]
