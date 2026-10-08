"""
The offline `entity_graph` build (ADR-0018). Run from the host, after
`uv sync --all-packages --group build`:

    uv run python -m ai_engine.core.associations.build --working-dir DIR --out demo_kb/associations
    uv run python -m ai_engine.core.associations.build --sample 100 --working-dir DIR --out DIR
    uv run python -m ai_engine.core.associations.build --rescore-only --out demo_kb/associations

1. Reads every article, active or not, through `ai_engine_ro`. The graph
   keeps inactive articles, so deactivating or reactivating one never costs
   a model call; scoring decides what counts.
2. Syncs LightRAG's working directory with them: a new article is
   extracted; a changed one (or one extracted under another policy version)
   is deleted and extracted again; a hard-deleted one is deleted, which
   rebuilds shared entities from LightRAG's cache with no model call.
3. Fails resumably. If any article's extraction failed, it lists them,
   writes no file and exits 1: an exported graph silently missing articles
   would look complete. The state file records only articles that were
   extracted, so a re-run retries just the rest.
4. Exports `mentions.jsonl` (the extractor-neutral contract) and scores it
   into `entity_graph.jsonl` (`scoring.py`), for core-api's
   `load_associations`.

Writes no database row (ADR-0004): core-api loads the file.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lightrag import LightRAG
from lightrag.base import DocStatus
from lightrag.kg.shared_storage import finalize_share_data
from sqlalchemy import select

from ai_engine.core.associations.adapter import FILE_PATH_PREFIX, ModelCalls, make_rag
from ai_engine.core.associations.policy import LoadedPolicy, load_entity_policy
from ai_engine.core.associations.scoring import (
    AssociationRow,
    Mention,
    apply_policy,
    df_histogram,
    score_associations,
)
from ai_engine.core.config import settings
from ai_engine.core.db.client import db
from ai_engine.core.db.tables import KbArticle

STATE_FILE = "kb_state.json"
MENTIONS_FILE = "mentions.jsonl"
GRAPH_FILE = "entity_graph.jsonl"
# The spike check's sample is drawn with a fixed seed, so a re-run extracts
# the same articles (and resumes instead of starting over).
SAMPLE_SEED = 0


@dataclass(frozen=True)
class Article:
    id: uuid.UUID
    slug: str
    body: str
    is_active: bool


class BuildFailed(Exception):
    """Some articles were not extracted. Nothing was exported."""


def read_articles() -> list[Article]:
    rows = db.all(
        select(KbArticle.id, KbArticle.slug, KbArticle.body, KbArticle.is_active).order_by(
            KbArticle.slug
        )
    )
    return [Article(id=i, slug=s, body=b, is_active=a) for i, s, b, a in rows]


def content_key(policy_version: str, body: str) -> str:
    """What an extraction depends on: the text, the guidance the model was
    given, how the text was chunked and how many gleaning passes ran. Any of
    them changing means extracting again."""

    extraction = (
        f"{policy_version}\nchunk={settings.lightrag_chunk_tokens}"
        f"\ngleaning={settings.lightrag_max_gleaning}"
    )
    return hashlib.sha256(f"{extraction}\n{body}".encode()).hexdigest()


class State:
    """`{article_id: content_key}` for the articles LightRAG extracted, in
    the working directory beside its storages. `scope` stops a sample and a
    full build from sharing a directory: syncing one would delete the
    other's articles."""

    def __init__(self, path: Path, scope: str) -> None:
        self.path = path
        raw: dict[str, Any] = (
            json.loads(path.read_text()) if path.exists() else {"scope": scope, "documents": {}}
        )
        if raw["scope"] != scope:
            raise BuildFailed(
                f"{path.parent} holds a {raw['scope']!r} build, not {scope!r}: use another --working-dir"
            )
        self.scope = scope
        self.documents: dict[str, str] = raw["documents"]

    def save(self) -> None:
        _write_atomically(self.path, json.dumps({"scope": self.scope, "documents": self.documents}))


async def sync(
    rag: LightRAG, articles: list[Article], state: State, policy_version: str
) -> list[str]:
    """Brings LightRAG in line with `articles`. Returns the ids whose
    extraction failed (empty when everything is current)."""

    wanted = {str(a.id): content_key(policy_version, a.body) for a in articles}
    statuses = {
        doc_id: status.status
        for doc_id, status in (await rag.doc_status.get_docs_by_statuses(list(DocStatus))).items()
    }
    # A state entry LightRAG doesn't hold as processed is not done.
    state.documents = {
        doc_id: key
        for doc_id, key in state.documents.items()
        if statuses.get(doc_id) == DocStatus.PROCESSED
    }

    # Anything LightRAG holds that isn't current goes first: gone, changed,
    # failed, or a duplicate record. Re-inserting a known id would only add
    # a failed duplicate, so a retry is always delete, then insert.
    for doc_id in statuses:
        if doc_id not in wanted or state.documents.get(doc_id) != wanted[doc_id]:
            result = await rag.adelete_by_doc_id(doc_id)
            if result.status not in ("success", "not_found"):
                raise BuildFailed(f"could not delete {doc_id}: {result.message}")
            state.documents.pop(doc_id, None)
            state.save()

    todo = [a for a in articles if state.documents.get(str(a.id)) != wanted[str(a.id)]]
    if todo:
        await rag.ainsert(
            [a.body for a in todo],
            ids=[str(a.id) for a in todo],
            file_paths=[f"{FILE_PATH_PREFIX}{a.id}" for a in todo],
        )
    processed = await rag.doc_status.get_docs_by_statuses([DocStatus.PROCESSED])
    failed = []
    for a in todo:
        doc_id = str(a.id)
        if doc_id in processed:
            state.documents[doc_id] = wanted[doc_id]
        else:
            failed.append(doc_id)
    state.save()
    return failed


async def export_mentions(rag: LightRAG, articles: list[Article]) -> list[Mention]:
    """Every (entity, type, article) LightRAG extracted. Read from its
    per-document entity lists, not from the graph's nodes: a node's
    `file_path` list is capped (75 by default), so a common entity would
    look rarer than it is and df would be wrong."""

    graph = rag.chunk_entity_relation_graph
    mentions: set[Mention] = set()
    for a in articles:
        row = await rag.full_entities.get_by_id(str(a.id))
        for name in (row or {}).get("entity_names", []):
            node = await graph.get_node(name)
            entity_type = (node or {}).get("entity_type") or "unknown"
            mentions.add(Mention(entity=name, type=entity_type, article_slug=a.slug))
    return sorted(mentions)


def score(
    mentions: list[Mention], articles: list[Article], policy: LoadedPolicy
) -> list[AssociationRow]:
    contents = "".join(json.dumps(asdict(m), sort_keys=True) + "\n" for m in mentions)
    build_id = ":".join(
        [
            "entity_graph",
            policy.version,
            f"mentions-{hashlib.sha256(contents.encode()).hexdigest()[:12]}",
            datetime.now(UTC).date().isoformat(),
        ]
    )
    return score_associations(
        apply_policy(mentions, policy.scoring),
        {a.slug for a in articles if a.is_active},
        hub_df_max=settings.association_hub_df_max,
        per_article_cap=settings.association_per_article_cap,
        build_id=build_id,
    )


def _write_atomically(path: Path, text: str) -> None:
    """Never a half-written file where a reader (or core-api) would find it."""

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_jsonl(path: Path, rows: list[Any]) -> None:
    _write_atomically(
        path,
        "".join(json.dumps(asdict(r), ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
    )


def read_mentions(path: Path) -> list[Mention]:
    return [
        Mention(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


async def extract(
    articles: list[Article],
    working_dir: Path,
    scope: str,
    policy: LoadedPolicy,
    **rag_overrides: Any,
) -> tuple[list[Mention], ModelCalls]:
    working_dir.mkdir(parents=True, exist_ok=True)
    state = State(working_dir / STATE_FILE, scope)
    calls = ModelCalls()
    rag = make_rag(working_dir, guidance=policy.guidance, calls=calls, **rag_overrides)
    await rag.initialize_storages()
    try:
        failed = await sync(rag, articles, state, policy.version)
        if failed:
            raise BuildFailed(
                f"{len(failed)} of {len(articles)} articles failed extraction: {', '.join(failed)}. "
                "Nothing was exported; re-run to retry them."
            )
        return await export_mentions(rag, articles), calls
    finally:
        await rag.finalize_storages()
        # LightRAG keeps its storages' data process-global, keyed by
        # namespace and workspace, not by working directory: a second
        # extraction in this process would otherwise see this one's.
        finalize_share_data()


def run(args: argparse.Namespace, **rag_overrides: Any) -> int:
    policy = load_entity_policy(settings.entity_policy_version)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    articles = read_articles()
    started = time.monotonic()

    if args.rescore_only:
        mentions = read_mentions(out / MENTIONS_FILE)
        calls = ModelCalls()
    else:
        scope = "full"
        if args.sample is not None:
            articles = sorted(
                random.Random(SAMPLE_SEED).sample(articles, min(args.sample, len(articles))),
                key=lambda a: a.slug,
            )
            scope = f"sample:{args.sample}"
        try:
            mentions, calls = asyncio.run(
                extract(articles, Path(args.working_dir), scope, policy, **rag_overrides)
            )
        except BuildFailed as e:
            print(f"build failed: {e}", file=sys.stderr)
            return 1
        write_jsonl(out / MENTIONS_FILE, mentions)

    rows = score(mentions, articles, policy)
    write_jsonl(out / GRAPH_FILE, rows)

    active = {a.slug for a in articles if a.is_active}
    print(
        f"{len(articles)} articles ({len(active)} active), {len(mentions)} mentions of "
        f"{len({m.entity for m in mentions})} entities, {len(rows)} associations, "
        f"{calls.llm} model calls, {time.monotonic() - started:.0f}s"
    )
    if args.sample is not None:
        print(
            f"df histogram (active articles per entity: entities): {df_histogram(mentions, active)}"
        )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument(
        "--out", required=True, help="where mentions.jsonl and entity_graph.jsonl go"
    )
    parser.add_argument("--working-dir", help="LightRAG's storages and the build state")
    parser.add_argument(
        "--sample", type=int, help="extract this many random articles (the spike check)"
    )
    parser.add_argument(
        "--rescore-only",
        action="store_true",
        help="score the existing mentions.jsonl; no model call",
    )
    args = parser.parse_args(argv)
    if not args.rescore_only and not args.working_dir:
        parser.error("--working-dir is required unless --rescore-only")
    if args.rescore_only and args.sample is not None:
        parser.error("--rescore-only scores the existing mentions; it takes no --sample")
    return args


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
