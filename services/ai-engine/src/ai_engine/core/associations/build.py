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
from lightrag.kg.shared_storage import (
    commit_manual_retry_request,
    finalize_share_data,
    get_namespace_data,
    get_namespace_lock,
    get_pipeline_ingress,
)
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


def extraction_model() -> str:
    """The provider and model extracting, e.g. `deepseek:deepseek-flash`."""

    provider = settings.chat_client_provider
    return f"{provider}:{settings.chat_model if provider == 'vllm' else settings.cloud_model}"


def content_key(policy_version: str, body: str) -> str:
    """What an extraction depends on: the text, the model and the guidance
    it was given, how the text was chunked and how many gleaning passes ran.
    Any of them changing means extracting again."""

    extraction = (
        f"{policy_version}\nmodel={extraction_model()}"
        f"\nchunk={settings.lightrag_chunk_tokens}\ngleaning={settings.lightrag_max_gleaning}"
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


# The statuses LightRAG's queue picks up again on its own, as pending or as
# interrupted mid-flight (its `_AUTO_RESUME_DOC_STATUSES`). Failed is not one.
_RESUMED_BY_THE_QUEUE = frozenset(
    {DocStatus.PENDING, DocStatus.PROCESSING, DocStatus.PARSING, DocStatus.ANALYZING}
)


async def sync(
    rag: LightRAG, articles: list[Article], state: State, policy_version: str
) -> list[str]:
    """Brings LightRAG in line with `articles`. Returns the ids whose
    extraction failed (empty when everything is current)."""

    wanted = {str(a.id): content_key(policy_version, a.body) for a in articles}
    records = await rag.doc_status.get_docs_by_statuses(list(DocStatus))
    statuses = {doc_id: record.status for doc_id, record in records.items()}
    # A state entry LightRAG doesn't hold as processed is not done.
    state.documents = {
        doc_id: key
        for doc_id, key in state.documents.items()
        if statuses.get(doc_id) == DocStatus.PROCESSED
    }

    # A document still queued (pending) when a run stopped was never
    # extracted, so it has nothing in the graph to undo: if its queued text is
    # still the article's, LightRAG's queue picks it up. Deleting it instead
    # rewrites the whole graph file per document (~8 a minute on the full KB,
    # 2026-10-10), hours for an interrupted batch.
    # A document that failed before any chunk was written (the model or
    # embedder unreachable mid-batch: 140 when Docker restarted, 2026-10-10)
    # is the same: nothing to undo, so it is retried in place instead. So is
    # one a stopped run left mid-flight before writing a chunk (114 of 116
    # at the 2026-10-10 pause): LightRAG's queue resumes those statuses itself.
    body = {str(a.id): a.body for a in articles}
    retried = {
        doc_id
        for doc_id, record in records.items()
        if record.status == DocStatus.FAILED and not record.chunks_list
    }
    resumed = {
        doc_id
        for doc_id, record in records.items()
        if record.status in _RESUMED_BY_THE_QUEUE and not record.chunks_list
    }
    queued = {
        doc_id
        for doc_id in statuses
        if (doc_id in resumed or doc_id in retried)
        and doc_id in body
        and ((await rag.full_docs.get_by_id(doc_id)) or {}).get("content") == body[doc_id]
    }

    # Anything else LightRAG holds that isn't current goes first: gone,
    # changed, failed, interrupted, or a duplicate record. Re-inserting a
    # known id would only add a failed duplicate, so a retry is always delete,
    # then insert.
    for doc_id in statuses:
        if doc_id in queued:
            continue
        if doc_id not in wanted or state.documents.get(doc_id) != wanted[doc_id]:
            result = await rag.adelete_by_doc_id(doc_id)
            if result.status not in ("success", "not_found"):
                raise BuildFailed(f"could not delete {doc_id}: {result.message}")
            state.documents.pop(doc_id, None)
            state.save()

    if retried & queued:
        await _retry_failed_in_place(rag)
    stale = [a for a in articles if state.documents.get(str(a.id)) != wanted[str(a.id)]]
    todo = [a for a in stale if str(a.id) not in queued]
    if todo:
        # Processes the queue too: the queued documents go with these.
        await rag.ainsert(
            [a.body for a in todo],
            ids=[str(a.id) for a in todo],
            file_paths=[f"{FILE_PATH_PREFIX}{a.id}" for a in todo],
        )
    elif queued:
        await rag.apipeline_process_enqueue_documents()
    processed = await rag.doc_status.get_docs_by_statuses([DocStatus.PROCESSED])
    failed = []
    for a in stale:
        doc_id = str(a.id)
        if doc_id in processed:
            state.documents[doc_id] = wanted[doc_id]
        else:
            failed.append(doc_id)
    state.save()
    return failed


async def _retry_failed_in_place(rag: LightRAG) -> None:
    """Asks LightRAG's queue to put its failed documents back to pending and
    run them, from their stored text: what its server's
    `/documents/reprocess_failed` does. The next processing run serves it.
    `sync` calls it only once every failed document left is one it wants
    retried; the rest were deleted first."""

    workspace = rag.workspace
    refusal = await commit_manual_retry_request(
        await get_namespace_data("pipeline_status", workspace=workspace),
        get_namespace_lock("pipeline_status", workspace=workspace),
        await get_pipeline_ingress(workspace),
        uuid.uuid4().hex,
        {},
    )
    if refusal:
        raise BuildFailed(f"LightRAG refused to retry failed documents: {refusal}")


def twins(articles: list[Article]) -> dict[uuid.UUID, Article]:
    """Copy id -> original, for articles whose text is identical to an
    earlier one by slug: the same page under two URLs (15 pairs in the demo
    KB, iam_example_* / sts_example_*). LightRAG refuses the second as a
    duplicate, every run, so only the original is extracted and the copy is
    given its entities: same text, same entities."""

    first: dict[str, Article] = {}
    copies: dict[uuid.UUID, Article] = {}
    for a in sorted(articles, key=lambda a: a.slug):
        original = first.setdefault(a.body, a)
        if original is not a:
            copies[a.id] = original
    return copies


async def export_mentions(rag: LightRAG, articles: list[Article]) -> list[Mention]:
    """Every (entity, type, article) LightRAG extracted, a copy given its
    original's (`twins`). Read from its per-document entity lists, not from
    the graph's nodes: a node's `file_path` list is capped (75 by default),
    so a common entity would look rarer than it is and df would be wrong."""

    graph = rag.chunk_entity_relation_graph
    copies = twins(articles)
    mentions: set[Mention] = set()
    for a in articles:
        source = copies.get(a.id, a)
        row = await rag.full_entities.get_by_id(str(source.id))
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
            settings.association_scoring,
            f"mentions-{hashlib.sha256(contents.encode()).hexdigest()[:12]}",
            datetime.now(UTC).date().isoformat(),
        ]
    )
    # Twins share every entity, so each would be the other's strongest
    # association: an edge to the same text, wasting a slot.
    slug = {a.id: a.slug for a in articles}
    twin_pairs = {
        pair
        for copy_id, original in twins(articles).items()
        for pair in ((slug[copy_id], original.slug), (original.slug, slug[copy_id]))
    }
    return score_associations(
        apply_policy(mentions, policy.scoring),
        {a.slug for a in articles if a.is_active},
        hub_df_max=settings.association_hub_df_max,
        per_article_cap=settings.association_per_article_cap,
        build_id=build_id,
        method=settings.association_scoring,
        excluded_pairs=frozenset(twin_pairs),
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
    # The model is part of the scope: LightRAG caches replies by prompt text,
    # so another model in this directory would get this one's replies back.
    state = State(working_dir / STATE_FILE, f"{scope}:{extraction_model()}")
    calls = ModelCalls()
    rag = make_rag(
        working_dir, guidance=policy.guidance, calls=calls, limits=policy.limits, **rag_overrides
    )
    await rag.initialize_storages()
    try:
        copies = twins(articles)
        failed = await sync(rag, [a for a in articles if a.id not in copies], state, policy.version)
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
