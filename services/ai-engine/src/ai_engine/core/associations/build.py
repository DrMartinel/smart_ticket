"""
Builds the entity graph from the KB pages and writes it to files and to `kb_article_associations`.
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
from sqlalchemy import delete, insert, select
from sqlalchemy.exc import SQLAlchemyError

from ai_engine.core.associations.extract import PairExtractor, ReplyCache
from ai_engine.core.associations.policy import EntityGraphPolicy
from ai_engine.core.associations.resolve import PageIndex, Resolution
from ai_engine.core.associations.sections import SectionSplitter
from ai_engine.core.config import settings
from ai_engine.core.db.client import db
from ai_engine.core.db.tables import KbArticle, KbArticleAssociation

type Embed = Callable[[list[str]], list[list[float]]]


@dataclass(frozen=True)
class Article:
    """One KB page."""

    id: uuid.UUID
    slug: str
    title: str
    body: str


class BuildFailed(Exception):
    """Some sections were not extracted. Nothing was exported."""


@dataclass(frozen=True)
class AssociationRow:
    """One edge of the entity graph."""

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
        """Builds the pair's sort key."""

        return (self.article_slug, self.symptom, self.remedy, self.page or "")


@dataclass(frozen=True)
class ResolutionRow:
    """One line of `entity_graph_resolutions.jsonl`."""

    source_slug: str
    name: str
    target_slug: str | None
    method: str
    similarity: float | None


class KbSnapshot:
    """The KB pages one build reads."""

    SAMPLE_SEED = 0

    def __init__(self, articles: list[Article]) -> None:
        self.articles = articles

    @classmethod
    def read(cls) -> KbSnapshot:
        """Reads every article from the database."""

        rows = db.all(
            select(KbArticle.id, KbArticle.slug, KbArticle.title, KbArticle.body).order_by(
                KbArticle.slug
            )
        )
        return cls([Article(id=i, slug=s, title=t, body=b) for i, s, t, b in rows])

    def sample(self, size: int, include: list[str]) -> KbSnapshot:
        """Samples random articles, plus the slugs in `include`."""

        wanted = set(include)
        chosen = {
            a.slug
            for a in random.Random(self.SAMPLE_SEED).sample(
                self.articles, min(size, len(self.articles))
            )
        }
        sampled = [a for a in self.articles if a.slug in chosen or a.slug in wanted]
        return KbSnapshot(sampled)

    def twins(self) -> dict[str, Article]:
        """Maps the slug of each article whose body repeats an earlier one's to that original."""

        first: dict[str, Article] = {}
        copies: dict[str, Article] = {}
        for a in sorted(self.articles, key=lambda a: a.slug):
            original = first.setdefault(a.body, a)
            if original is not a:
                copies[a.slug] = original
        return copies


class PageExtractor:
    """Gets every page's pairs from the model, a copy given its original's."""

    CACHE_FILE = "entity_graph_replies.jsonl"
    TOKENIZER = "o200k_base"

    def __init__(
        self,
        *,
        policy: EntityGraphPolicy,
        chat_model: BaseChatModel,
        retry_model: BaseChatModel | None,
        working_dir: Path,
    ) -> None:
        self._policy = policy
        self._chat_model = chat_model
        self._retry_model = retry_model
        self._working_dir = working_dir

    def extract(self, snapshot: KbSnapshot) -> tuple[list[PagePair], int]:
        """Gets every page's pairs."""

        import tiktoken

        self._working_dir.mkdir(parents=True, exist_ok=True)
        encoding = tiktoken.get_encoding(self.TOKENIZER)
        splitter = SectionSplitter(
            max_tokens=settings.entity_graph_section_tokens,
            count=lambda text: len(encoding.encode(text, disallowed_special=())),
            strip_links=self._policy.strip_links,
        )
        model = f"deepseek:{settings.cloud_model}"
        copies = snapshot.twins()
        keys_by_slug: dict[str, list[str]] = {}
        texts: dict[str, str] = {}
        for a in snapshot.articles:
            if a.slug in copies:
                continue
            keys = []
            for text in splitter.split(a.body):
                key = ReplyCache.key(
                    self._policy.version, model, settings.entity_graph_section_tokens, text
                )
                texts[key] = text
                keys.append(key)
            keys_by_slug[a.slug] = keys

        extractor = PairExtractor(
            policy=self._policy,
            chat_model=self._chat_model,
            cache=ReplyCache(self._working_dir / self.CACHE_FILE),
            max_async=settings.entity_graph_llm_max_async,
            retry_model=self._retry_model,
        )
        result = asyncio.run(extractor.extract(texts))
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

        pairs: set[PagePair] = set()
        for a in snapshot.articles:
            source = copies.get(a.slug, a)
            for key in keys_by_slug[source.slug]:
                for p in result.pairs[key]:
                    pairs.add(PagePair(a.slug, p.symptom, p.remedy, p.page))
        return sorted(pairs, key=PagePair.order), result.calls


class EdgeScorer:
    """Resolves the pages the pairs name and scores the edges between pages."""

    def __init__(self, *, policy: EntityGraphPolicy, embed: Embed) -> None:
        self._policy = policy
        self._embed = embed

    @staticmethod
    def provider_embed(texts: list[str]) -> list[list[float]]:
        """Embeds `texts` with the configured embedder."""

        from concurrent.futures import ThreadPoolExecutor

        from ai_engine.core.providers.embeddings import embedder

        with ThreadPoolExecutor(max_workers=settings.entity_graph_llm_max_async) as pool:
            return list(pool.map(embedder.embed, texts))

    def score(
        self, pairs: list[PagePair], snapshot: KbSnapshot
    ) -> tuple[list[AssociationRow], list[ResolutionRow]]:
        """Resolves the named pages and scores the edges between pages."""

        resolved = self._resolve(pairs, snapshot)
        evidence, by_embedding = self._evidence(pairs, resolved, snapshot)
        rows = self._rank(evidence, by_embedding, self._build_id(pairs))
        return rows, self._resolution_rows(resolved)

    def _resolve(
        self, pairs: list[PagePair], snapshot: KbSnapshot
    ) -> dict[tuple[str, str], Resolution]:
        index = PageIndex(
            snapshot.articles,
            aliases=self._policy.aliases,
            embed=self._embed,
            min_similarity=settings.entity_graph_resolve_min_similarity,
        )
        return index.resolve_all([(p.page, p.article_slug) for p in pairs if p.page is not None])

    @staticmethod
    def _evidence(
        pairs: list[PagePair],
        resolved: dict[tuple[str, str], Resolution],
        snapshot: KbSnapshot,
    ) -> tuple[dict[str, dict[str, set[str]]], set[tuple[str, str]]]:
        twin_pairs = {
            pair
            for copy, original in snapshot.twins().items()
            for pair in ((copy, original.slug), (original.slug, copy))
        }
        evidence: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        by_embedding: set[tuple[str, str]] = set()
        for p in pairs:
            if p.page is None:
                continue
            r = resolved[p.page, p.article_slug]
            if r.target is None or r.target == p.article_slug:
                continue
            if (p.article_slug, r.target) in twin_pairs:
                continue
            evidence[p.article_slug][r.target].add(f"{p.symptom} -> {p.remedy}")
            if r.method == "embedding":
                by_embedding.add((p.article_slug, r.target))
        return evidence, by_embedding

    def _build_id(self, pairs: list[PagePair]) -> str:
        contents = "".join(json.dumps(asdict(p), sort_keys=True) + "\n" for p in pairs)
        return ":".join(
            [
                "entity_graph",
                self._policy.version,
                f"pairs-{hashlib.sha256(contents.encode()).hexdigest()[:12]}",
                datetime.now(UTC).date().isoformat(),
            ]
        )

    @staticmethod
    def _rank(
        evidence: dict[str, dict[str, set[str]]],
        by_embedding: set[tuple[str, str]],
        build_id: str,
    ) -> list[AssociationRow]:
        rows = []
        for source in sorted(evidence):
            ranked = sorted(
                evidence[source].items(),
                key=lambda tf: (-len(tf[1]), (source, tf[0]) in by_embedding, tf[0]),
            )[: settings.association_per_article_cap]
            for target, found in ranked:
                rows.append(
                    AssociationRow(
                        source, target, float(len(found)), tuple(sorted(found)), build_id
                    )
                )
        return rows

    @staticmethod
    def _resolution_rows(resolved: dict[tuple[str, str], Resolution]) -> list[ResolutionRow]:
        return sorted(
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


class EntityGraphStore:
    """Writes the entity graph's rows to `kb_article_associations`."""

    SOURCE = "entity_graph"

    def replace(self, rows: list[AssociationRow], snapshot: KbSnapshot) -> tuple[int, int]:
        """Replaces the `entity_graph` rows with `rows`."""

        article_id = {a.slug: a.id for a in snapshot.articles}
        values = [
            {
                "id": uuid.uuid4(),
                "reviewed": False,
                "source_article_id": article_id[r.source_slug],
                "target_article_id": article_id[r.target_slug],
                "source": self.SOURCE,
                "score": r.score,
                "evidence": list(r.evidence),
                "build_id": r.build_id,
            }
            for r in rows
            if r.source_slug in article_id and r.target_slug in article_id
        ]
        db.write(
            [
                (
                    delete(KbArticleAssociation).where(KbArticleAssociation.source == self.SOURCE),
                    None,
                ),
                (insert(KbArticleAssociation), values),
            ]
        )
        return len(values), len(rows) - len(values)


class BuildFiles:
    """The build's output files in one directory."""

    PAIRS = "entity_graph_pairs.jsonl"
    RESOLUTIONS = "entity_graph_resolutions.jsonl"
    GRAPH = "entity_graph.jsonl"

    def __init__(self, out: Path) -> None:
        self.out = out
        out.mkdir(parents=True, exist_ok=True)

    def read_pairs(self) -> list[PagePair]:
        """Reads `entity_graph_pairs.jsonl`."""

        return [
            PagePair(**json.loads(line))
            for line in (self.out / self.PAIRS).read_text(encoding="utf-8").splitlines()
            if line
        ]

    def write(self, name: str, rows: list[Any]) -> None:
        """Writes `rows` to the file `name`, one JSON object per line."""

        path = self.out / name
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            "".join(json.dumps(asdict(r), ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
            encoding="utf-8",
        )
        os.replace(tmp, path)


class EntityGraphBuild:
    """Runs one entity-graph build from the command line's arguments."""

    def __init__(
        self,
        args: argparse.Namespace,
        *,
        chat_model: BaseChatModel | None = None,
        retry_model: BaseChatModel | None = None,
        embed: Embed | None = None,
    ) -> None:
        self._args = args
        self._chat_model = chat_model
        self._retry_model = retry_model
        self._embed = embed or EdgeScorer.provider_embed

    @staticmethod
    def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
        """Parses the command line."""

        parser = argparse.ArgumentParser(
            description=__doc__.strip().split("\n")[0] if __doc__ else None
        )
        parser.add_argument("--out", required=True, help="where the entity_graph*.jsonl files go")
        parser.add_argument("--working-dir", help="the reply cache")
        parser.add_argument(
            "--sample",
            type=int,
            help="extract this many random articles (the spike); writes files only, no row",
        )
        parser.add_argument(
            "--include", nargs="*", default=[], help="slugs always in the sample (with --sample)"
        )
        parser.add_argument(
            "--rescore-only",
            action="store_true",
            help="resolve, score and write the existing entity_graph_pairs.jsonl; no model call",
        )
        args = parser.parse_args(argv)
        if not args.rescore_only and not args.working_dir:
            parser.error("--working-dir is required unless --rescore-only")
        if args.rescore_only and args.sample is not None:
            parser.error("--rescore-only scores the existing pairs; it takes no --sample")
        if args.include and args.sample is None:
            parser.error("--include needs --sample")
        return args

    def run(self) -> int:
        """Runs the build."""

        args = self._args
        policy = EntityGraphPolicy.load(settings.entity_graph_policy_version)
        files = BuildFiles(Path(args.out))
        every_page = KbSnapshot.read()
        extracted = every_page
        started = time.monotonic()
        calls = 0

        if args.rescore_only:
            pairs = files.read_pairs()
        else:
            if args.sample is not None:
                extracted = every_page.sample(args.sample, args.include)
            try:
                pairs, calls = self._extractor(policy).extract(extracted)
            except BuildFailed as e:
                print(f"build failed: {e}", file=sys.stderr)
                return 1
            files.write(BuildFiles.PAIRS, pairs)

        scorer = EdgeScorer(policy=policy, embed=self._embed)
        rows, resolutions = scorer.score(pairs, every_page)
        files.write(BuildFiles.RESOLUTIONS, resolutions)
        files.write(BuildFiles.GRAPH, rows)
        written = skipped = 0
        if args.sample is None:
            try:
                written, skipped = EntityGraphStore().replace(rows, every_page)
            except SQLAlchemyError as e:
                print(f"build failed writing kb_article_associations: {e}", file=sys.stderr)
                return 1

        methods = Counter(r.method for r in resolutions)
        named = sum(p.page is not None for p in pairs)
        print(
            f"{len(extracted.articles)} articles, {len(pairs)} pairs ({named} naming another page), "
            f"resolutions {dict(methods)}, {len(rows)} pointer edges from "
            f"{len({r.source_slug for r in rows})} pages ({written} written, {skipped} skipped "
            f"for an unknown slug), {calls} model calls, "
            f"{time.monotonic() - started:.0f}s"
        )
        return 0

    def _extractor(self, policy: EntityGraphPolicy) -> PageExtractor:
        chat_model, retry_model = self._chat_model, self._retry_model
        if chat_model is None:
            from ai_engine.core.providers.clients import ChatClient

            chat_model = ChatClient.deepseek_model(json_mode=True, temperature=0)
            retry_model = ChatClient.deepseek_model(json_mode=True)
        return PageExtractor(
            policy=policy,
            chat_model=chat_model,
            retry_model=retry_model,
            working_dir=Path(self._args.working_dir),
        )


if __name__ == "__main__":
    sys.exit(EntityGraphBuild(EntityGraphBuild.parse_args()).run())
