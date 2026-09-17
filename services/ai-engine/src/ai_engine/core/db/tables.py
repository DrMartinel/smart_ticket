"""
Partial query descriptions of the three tables `ai_engine_ro` may read
(ADR-0004, ADR-0008). NOT the schema: core-api owns that, and only the columns
ai-engine uses are declared.

- Never call `create_all()` / `drop_all()`: these are not full definitions.
- Never instantiate these classes or `session.add()` them: ai-engine has no
  write authority.
- Never add a table outside 0004_grants_and_audit_lockdown.sql's SELECT grant.

`tests/test_db_tables.py` pins the table set and the absence of DDL/write
calls; "never instantiated" is on review.
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
