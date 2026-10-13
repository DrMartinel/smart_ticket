"""
The offline `entity_graph` build (ADR-0018). Run from the host, after
`uv sync --all-packages --group build`, with `CLOUD_*` naming DeepSeek
(ADR-0019):

    uv run python -m ai_engine.core.associations.build --working-dir DIR --out demo_kb/associations
    uv run python -m ai_engine.core.associations.build --sample 150 --working-dir DIR --out DIR
    uv run python -m ai_engine.core.associations.build --rescore-only --out demo_kb/associations

1. Reads every article through `ai_engine_ro` and cuts each into sections
   (`sections.py`), links stripped to their text when the policy says so.
2. Asks the model for each section's (symptom, remedy, where) pairs,
   from the reply cache where it has them (`extract.py`). A page whose text
   is identical to another's is not sent: it is given its original's pairs.
3. Fails resumably: any failed section lists its pages, writes no file and
   exits 1; a re-run asks only for what is missing.
4. Exports `entity_graph_pairs.jsonl` (every pair, by page), resolves each
   named page (`resolve.py`, every resolution in
   `entity_graph_resolutions.jsonl` for the hand check), and writes
   `entity_graph.jsonl` for core-api's `load_associations`.

An edge A -> B: page A names a problem whose remedy, the text says, is on
page B. Its score is the number of distinct (symptom, remedy) pairs
pointing from A to B; it only orders A's targets (ADR-0005).

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
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from sqlalchemy import select

from ai_engine.core.associations.extract import ReplyCache, extract, section_key
from ai_engine.core.associations.policy import EntityGraphPolicy, load_policy
from ai_engine.core.associations.resolve import Page, PageIndex, Resolution
from ai_engine.core.associations.sections import split_sections, strip_links
from ai_engine.core.config import settings
from ai_engine.core.db.client import db
from ai_engine.core.db.tables import KbArticle

PAIRS_FILE = "entity_graph_pairs.jsonl"
RESOLUTIONS_FILE = "entity_graph_resolutions.jsonl"
GRAPH_FILE = "entity_graph.jsonl"
CACHE_FILE = "entity_graph_replies.jsonl"
# The spike's sample is drawn with a fixed seed, so a re-run extracts the
# same articles (and is served from the cache).
SAMPLE_SEED = 0
# The tokenizer sections are measured with. DeepSeek's own differs a little;
# the budget is a size, not a hard limit of the model.
TOKENIZER = "o200k_base"


@dataclass(frozen=True)
class Article:
    id: uuid.UUID
    slug: str
    body: str
    is_active: bool


class BuildFailed(Exception):
    """Some sections were not extracted. Nothing was exported."""


@dataclass(frozen=True)
class AssociationRow:
    """One line of `entity_graph.jsonl`: one direction of one pair, the
    shape core-api's `load_associations` reads."""

    source_slug: str
    target_slug: str
    score: float
    evidence: tuple[str, ...]
    build_id: str


@dataclass(frozen=True)
class PagePair:
    """One line of `entity_graph_pairs.jsonl`: a pair found on one page."""

    article_slug: str
    symptom: str
    remedy: str
    page: str | None

    def order(self) -> tuple[str, str, str, str]:
        # "This page" (None) sorts first; None and str don't compare.
        return (self.article_slug, self.symptom, self.remedy, self.page or "")


@dataclass(frozen=True)
class ResolutionRow:
    """One line of `entity_graph_resolutions.jsonl`."""

    source_slug: str
    name: str
    target_slug: str | None
    method: str
    similarity: float | None


def twins(articles: list[Article]) -> dict[uuid.UUID, Article]:
    """Copy id -> original, for articles whose text is identical to an
    earlier one by slug: the same page under two URLs (15 pairs in the demo
    KB, iam_example_* / sts_example_*). Only the original is sent to the
    model; the copy is given its pairs: same text, same pairs."""

    first: dict[str, Article] = {}
    copies: dict[uuid.UUID, Article] = {}
    for a in sorted(articles, key=lambda a: a.slug):
        original = first.setdefault(a.body, a)
        if original is not a:
            copies[a.id] = original
    return copies


def write_jsonl(path: Path, rows: list[Any]) -> None:
    """Never a half-written file where a reader (or core-api) would find it."""

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "".join(json.dumps(asdict(r), ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def model_id() -> str:
    """The model extracting, part of every cached reply's key. Always
    DeepSeek (ADR-0019): the build builds its own client, whatever
    CHAT_CLIENT_PROVIDER serves triage."""

    return f"deepseek:{settings.cloud_model}"


def read_pages() -> tuple[list[Article], dict[str, str]]:
    rows = db.all(
        select(
            KbArticle.id, KbArticle.slug, KbArticle.title, KbArticle.body, KbArticle.is_active
        ).order_by(KbArticle.slug)
    )
    articles = [Article(id=i, slug=s, body=b, is_active=a) for i, s, _, b, a in rows]
    return articles, {s: t for _, s, t, _, _ in rows}


def token_counter() -> Callable[[str], int]:
    import tiktoken

    encoding = tiktoken.get_encoding(TOKENIZER)
    return lambda text: len(encoding.encode(text, disallowed_special=()))


def sections_of(body: str, policy: EntityGraphPolicy, count: Callable[[str], int]) -> list[str]:
    text = strip_links(body) if policy.strip_links else body
    return split_sections(text, max_tokens=settings.entity_graph_section_tokens, count=count)


def extract_pairs(
    articles: list[Article],
    working_dir: Path,
    policy: EntityGraphPolicy,
    chat_model: BaseChatModel,
    retry_model: BaseChatModel | None = None,
) -> tuple[list[PagePair], int]:
    """Every page's pairs, a copy given its original's. Raises BuildFailed
    naming the pages with a failed section."""

    working_dir.mkdir(parents=True, exist_ok=True)
    count = token_counter()
    model = model_id()
    copies = twins(articles)
    keys_by_slug: dict[str, list[str]] = {}
    texts: dict[str, str] = {}
    for a in articles:
        if a.id in copies:
            continue
        keys = []
        for text in sections_of(a.body, policy, count):
            key = section_key(policy.version, model, settings.entity_graph_section_tokens, text)
            texts[key] = text
            keys.append(key)
        keys_by_slug[a.slug] = keys

    result = asyncio.run(
        extract(
            texts,
            policy=policy,
            chat_model=chat_model,
            cache=ReplyCache(working_dir / CACHE_FILE),
            max_async=settings.entity_graph_llm_max_async,
            retry_model=retry_model,
        )
    )
    if result.failed:
        pages = sorted(
            s for s, keys in keys_by_slug.items() if any(k in result.failed for k in keys)
        )
        reasons = Counter(why.split(":")[0] for why in result.failed.values())
        raise BuildFailed(
            f"{len(result.failed)} of {len(texts)} sections failed ({dict(reasons)}), on "
            f"{len(pages)} pages: {', '.join(pages[:20])}{' ...' if len(pages) > 20 else ''}. "
            "Nothing was exported; re-run to retry them."
        )

    slug_of = {a.id: a.slug for a in articles}
    pairs: set[PagePair] = set()
    for a in articles:
        source = copies.get(a.id, a)
        for key in keys_by_slug[slug_of[source.id]]:
            for p in result.pairs[key]:
                pairs.add(PagePair(a.slug, p.symptom, p.remedy, p.page))
    return sorted(pairs, key=PagePair.order), result.calls


def default_embed(texts: list[str]) -> list[list[float]]:
    from concurrent.futures import ThreadPoolExecutor

    from ai_engine.core.providers.embeddings import embedder

    with ThreadPoolExecutor(max_workers=settings.entity_graph_llm_max_async) as pool:
        return list(pool.map(embedder.embed, texts))


def pointers(
    pairs: list[PagePair],
    articles: list[Article],
    titles: dict[str, str],
    policy: EntityGraphPolicy,
    embed: Callable[[list[str]], list[list[float]]],
) -> tuple[list[AssociationRow], list[ResolutionRow]]:
    """Resolve every named page against `articles` (the whole KB) and score
    the edges, at most `ASSOCIATION_PER_ARTICLE_CAP` targets per page."""

    index = PageIndex(
        [Page(a.slug, titles[a.slug], a.body) for a in articles],
        aliases=policy.aliases,
        embed=embed,
        min_similarity=settings.entity_graph_resolve_min_similarity,
    )
    named = [(p.page, p.article_slug) for p in pairs if p.page is not None]
    resolved: dict[tuple[str, str], Resolution] = index.resolve_all(named)

    slug = {a.id: a.slug for a in articles}
    twin_pairs = {
        pair
        for copy_id, original in twins(articles).items()
        for pair in ((slug[copy_id], original.slug), (original.slug, slug[copy_id]))
    }
    evidence: dict[tuple[str, str], set[str]] = defaultdict(set)
    by_embedding: set[tuple[str, str]] = set()
    for p in pairs:
        if p.page is None:
            continue
        r = resolved[p.page, p.article_slug]
        if r.target is None or r.target == p.article_slug:
            continue
        if (p.article_slug, r.target) in twin_pairs:
            continue
        evidence[p.article_slug, r.target].add(f"{p.symptom} -> {p.remedy}")
        if r.method == "embedding":
            by_embedding.add((p.article_slug, r.target))

    contents = "".join(json.dumps(asdict(p), sort_keys=True) + "\n" for p in pairs)
    build_id = ":".join(
        [
            "entity_graph",
            policy.version,
            f"pairs-{hashlib.sha256(contents.encode()).hexdigest()[:12]}",
            datetime.now(UTC).date().isoformat(),
        ]
    )
    targets: dict[str, list[tuple[str, set[str]]]] = defaultdict(list)
    for (source, target), found in evidence.items():
        targets[source].append((target, found))
    rows = []
    for source in sorted(targets):
        # More distinct pairs first; an exact resolution before an embedding
        # one; the slug breaks ties, so a rebuild writes the same file.
        ranked = sorted(
            targets[source],
            key=lambda tf: (-len(tf[1]), (source, tf[0]) in by_embedding, tf[0]),
        )[: settings.association_per_article_cap]
        for target, found in ranked:
            rows.append(
                AssociationRow(source, target, float(len(found)), tuple(sorted(found)), build_id)
            )

    resolutions = sorted(
        (
            ResolutionRow(
                source,
                name,
                r.target,
                r.method,
                None if r.similarity is None else round(r.similarity, 4),
            )
            for (name, source), r in resolved.items()
        ),
        key=lambda r: (r.source_slug, r.name),
    )
    return rows, resolutions


def read_pairs(path: Path) -> list[PagePair]:
    return [
        PagePair(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def run(
    args: argparse.Namespace,
    *,
    chat_model: BaseChatModel | None = None,
    retry_model: BaseChatModel | None = None,
    embed: Callable[[list[str]], list[list[float]]] | None = None,
) -> int:
    policy = load_policy(settings.entity_graph_policy_version)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    articles, titles = read_pages()
    # Every page is a possible target, sampled or not: a sampled page may
    # point anywhere in the KB.
    every_page = articles
    started = time.monotonic()
    calls = 0

    if args.rescore_only:
        pairs = read_pairs(out / PAIRS_FILE)
    else:
        if args.sample is not None:
            articles = sample(articles, args.sample, args.include)
        if chat_model is None:
            from ai_engine.core.providers.clients import ChatClient

            chat_model = ChatClient.deepseek_model(json_mode=True, temperature=0)
            retry_model = ChatClient.deepseek_model(json_mode=True)
        try:
            pairs, calls = extract_pairs(
                articles, Path(args.working_dir), policy, chat_model, retry_model
            )
        except BuildFailed as e:
            print(f"build failed: {e}", file=sys.stderr)
            return 1
        write_jsonl(out / PAIRS_FILE, pairs)

    rows, resolutions = pointers(pairs, every_page, titles, policy, embed or default_embed)
    write_jsonl(out / RESOLUTIONS_FILE, resolutions)
    write_jsonl(out / GRAPH_FILE, rows)

    methods = Counter(r.method for r in resolutions)
    named = sum(p.page is not None for p in pairs)
    print(
        f"{len(articles)} articles, {len(pairs)} pairs ({named} naming another page), "
        f"resolutions {dict(methods)}, {len(rows)} pointer edges from "
        f"{len({r.source_slug for r in rows})} pages, {calls} model calls, "
        f"{time.monotonic() - started:.0f}s"
    )
    return 0


def sample(articles: list[Article], size: int, include: list[str]) -> list[Article]:
    """`size` random articles (fixed seed, so a re-run resumes), plus every
    slug in `include`: the spike needs the pages the stage check is about."""

    wanted = set(include)
    chosen = {a.slug for a in random.Random(SAMPLE_SEED).sample(articles, min(size, len(articles)))}
    return [a for a in articles if a.slug in chosen or a.slug in wanted]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--out", required=True, help="where the entity_graph*.jsonl files go")
    parser.add_argument("--working-dir", help="the reply cache")
    parser.add_argument("--sample", type=int, help="extract this many random articles (the spike)")
    parser.add_argument(
        "--include", nargs="*", default=[], help="slugs always in the sample (with --sample)"
    )
    parser.add_argument(
        "--rescore-only",
        action="store_true",
        help="resolve and score the existing entity_graph_pairs.jsonl; no model call",
    )
    args = parser.parse_args(argv)
    if not args.rescore_only and not args.working_dir:
        parser.error("--working-dir is required unless --rescore-only")
    if args.rescore_only and args.sample is not None:
        parser.error("--rescore-only scores the existing pairs; it takes no --sample")
    if args.include and args.sample is None:
        parser.error("--include needs --sample")
    return args


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
