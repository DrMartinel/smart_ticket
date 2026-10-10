"""
The offline `remedy_pointer` build (ADR-0018 amendment). Run from the host,
after `uv sync --all-packages --group build`, with `CHAT_CLIENT_PROVIDER`
naming the extraction model (DeepSeek, ADR-0019):

    uv run python -m ai_engine.core.associations.remedies.build --working-dir DIR --out demo_kb/associations
    uv run python -m ai_engine.core.associations.remedies.build --sample 150 --working-dir DIR --out DIR
    uv run python -m ai_engine.core.associations.remedies.build --rescore-only --out demo_kb/associations

1. Reads every article through `ai_engine_ro` and cuts each into sections
   (`sections.py`), links stripped to their text when the policy says so.
2. Asks the model for each section's (symptom, remedy, where) pairs,
   from the reply cache where it has them (`extract.py`). A page whose text
   is identical to another's is not sent: it is given its original's pairs.
3. Fails resumably: any failed section lists its pages, writes no file and
   exits 1; a re-run asks only for what is missing.
4. Exports `remedy_pairs.jsonl` (every pair, by page), resolves each named
   page (`resolve.py`, every resolution in `remedy_resolutions.jsonl` for
   the hand check), and writes `remedy_pointers.jsonl` for core-api's
   `load_associations --source remedy_pointer`.

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
import random
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from sqlalchemy import select

from ai_engine.core.associations.build import (
    SAMPLE_SEED,
    Article,
    BuildFailed,
    twins,
    write_jsonl,
)
from ai_engine.core.associations.remedies.extract import ReplyCache, extract, section_key
from ai_engine.core.associations.remedies.policy import RemedyPolicy, load_remedy_policy
from ai_engine.core.associations.remedies.resolve import Page, PageIndex, Resolution
from ai_engine.core.associations.remedies.sections import split_sections, strip_links
from ai_engine.core.associations.scoring import AssociationRow
from ai_engine.core.config import settings
from ai_engine.core.db.client import db
from ai_engine.core.db.tables import KbArticle

PAIRS_FILE = "remedy_pairs.jsonl"
RESOLUTIONS_FILE = "remedy_resolutions.jsonl"
POINTERS_FILE = "remedy_pointers.jsonl"
CACHE_FILE = "remedy_replies.jsonl"
# The tokenizer sections are measured with. DeepSeek's own differs a little;
# the budget is a size, not a hard limit of the model.
TOKENIZER = "o200k_base"


@dataclass(frozen=True, order=True)
class PagePair:
    """One line of `remedy_pairs.jsonl`: a pair found on one page."""

    article_slug: str
    symptom: str
    remedy: str
    page: str | None


@dataclass(frozen=True)
class ResolutionRow:
    """One line of `remedy_resolutions.jsonl`."""

    source_slug: str
    name: str
    target_slug: str | None
    method: str
    similarity: float | None


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


def sections_of(body: str, policy: RemedyPolicy, count: Callable[[str], int]) -> list[str]:
    text = strip_links(body) if policy.strip_links else body
    return split_sections(text, max_tokens=settings.remedy_section_tokens, count=count)


def extract_pairs(
    articles: list[Article],
    working_dir: Path,
    policy: RemedyPolicy,
    chat_model: BaseChatModel,
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
            key = section_key(policy.version, model, settings.remedy_section_tokens, text)
            texts[key] = text
            keys.append(key)
        keys_by_slug[a.slug] = keys

    result = asyncio.run(
        extract(
            texts,
            policy=policy,
            chat_model=chat_model,
            cache=ReplyCache(working_dir / CACHE_FILE),
            max_async=settings.remedy_llm_max_async,
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
    return sorted(pairs), result.calls


def default_embed(texts: list[str]) -> list[list[float]]:
    from concurrent.futures import ThreadPoolExecutor

    from ai_engine.core.providers.embeddings import embedder

    with ThreadPoolExecutor(max_workers=settings.remedy_llm_max_async) as pool:
        return list(pool.map(embedder.embed, texts))


def pointers(
    pairs: list[PagePair],
    articles: list[Article],
    titles: dict[str, str],
    policy: RemedyPolicy,
    embed: Callable[[list[str]], list[list[float]]],
) -> tuple[list[AssociationRow], list[ResolutionRow]]:
    """Resolve every named page and score the edges, at most
    `ASSOCIATION_PER_ARTICLE_CAP` targets per page."""

    index = PageIndex(
        [Page(a.slug, titles[a.slug], a.body) for a in articles],
        aliases=policy.aliases,
        embed=embed,
        min_similarity=settings.remedy_resolve_min_similarity,
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
            "remedy_pointer",
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
    embed: Callable[[list[str]], list[list[float]]] | None = None,
) -> int:
    policy = load_remedy_policy(settings.remedy_policy_version)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    articles, titles = read_pages()
    started = time.monotonic()
    calls = 0

    if args.rescore_only:
        pairs = read_pairs(out / PAIRS_FILE)
    else:
        if args.sample is not None:
            articles = sample(articles, args.sample, args.include)
        if chat_model is None:
            from ai_engine.core.providers.clients import deepseek_model

            chat_model = deepseek_model(json_mode=True, temperature=0)
        try:
            pairs, calls = extract_pairs(articles, Path(args.working_dir), policy, chat_model)
        except BuildFailed as e:
            print(f"build failed: {e}", file=sys.stderr)
            return 1
        write_jsonl(out / PAIRS_FILE, pairs)

    rows, resolutions = pointers(pairs, articles, titles, policy, embed or default_embed)
    write_jsonl(out / RESOLUTIONS_FILE, resolutions)
    write_jsonl(out / POINTERS_FILE, rows)

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
    parser.add_argument("--out", required=True, help="where the remedy_*.jsonl files go")
    parser.add_argument("--working-dir", help="the reply cache")
    parser.add_argument("--sample", type=int, help="extract this many random articles (the spike)")
    parser.add_argument(
        "--include", nargs="*", default=[], help="slugs always in the sample (with --sample)"
    )
    parser.add_argument(
        "--rescore-only",
        action="store_true",
        help="resolve and score the existing remedy_pairs.jsonl; no model call",
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
