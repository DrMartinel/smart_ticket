"""
Partial query descriptions of the four tables `ai_engine_ro` may read
(ADR-0004, ADR-0008, ADR-0018). NOT the schema: core-api owns that, and only the columns
ai-engine uses are declared.

- Never call `create_all()` / `drop_all()`: these are not full definitions.
- Never instantiate these classes or `session.add()` them: ai-engine has no
  write authority.
- Never add a table outside the SELECT grants in
  0004_grants_and_audit_lockdown.sql and 0006_association_grant.sql.

`tests/test_db_tables.py` pins the table set and the absence of DDL/write
calls; "never instantiated" is on review.
"""

from __future__ import annotations

import uuid

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# The width of every vector column, and so of every embedding: a property of
# bge-m3 AND of the pgvector schema, so changing it needs a migration. The
# embedder checks each vector against it.
EMBED_DIM = 1024


class Base(DeclarativeBase):
    """ai-engine's own metadata: exactly the tables `ai_engine_ro` may read,
    and nothing else."""


class KbArticle(Base):
    __tablename__ = "kb_articles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    slug: Mapped[str]
    # Read by link expansion: links in chunk text resolve against
    # `source_url`, and Jev sees the title with each passage (ADR-0015).
    title: Mapped[str]
    source_url: Mapped[str | None]
    is_active: Mapped[bool]


class KbChunk(Base):
    __tablename__ = "kb_chunks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_articles.id"))
    # Document order, so link expansion follows an article's links in the
    # order its author wrote them.
    chunk_index: Mapped[int]
    content: Mapped[str]
    section_title: Mapped[str | None]
    embedding: Mapped[Any] = mapped_column(VECTOR(EMBED_DIM), nullable=True)


class KbArticleAssociation(Base):
    """Which articles link expansion follows from a seed (ADR-0018). core-api
    writes every row; `score` only orders one seed's targets within one
    source, and is never compared with a threshold."""

    __tablename__ = "kb_article_associations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    source_article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_articles.id"))
    target_article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_articles.id"))
    source: Mapped[str]
    score: Mapped[float]


class FewshotExample(Base):
    __tablename__ = "fewshot_examples"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    category: Mapped[str]
    input_text: Mapped[str]
    output_json: Mapped[Any] = mapped_column(JSONB)
    embedding: Mapped[Any] = mapped_column(VECTOR(EMBED_DIM), nullable=True)
    expires_at: Mapped[datetime]
    retracted_at: Mapped[datetime | None]
