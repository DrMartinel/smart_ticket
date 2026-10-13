"""
Resolves a page name, as the text writes it, to one KB page.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np

from ai_engine.core.config import settings
from ai_engine.core.providers.embeddings import embedder

_HEADING = re.compile(r"^#{1,2} +(.+?)\s*$", re.MULTILINE)
_NOT_WORD = re.compile(r"[^0-9a-z]+")

Method = Literal["exact", "embedding", "unresolved", "ambiguous"]


class Page(Protocol):
    """A KB page that names are resolved against."""

    @property
    def slug(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def body(self) -> str: ...


@dataclass(frozen=True)
class Resolution:
    target: str | None
    method: Method
    similarity: float | None = None


class PageIndex:
    """Resolves page names to KB page slugs by title, heading, alias or embedding."""

    def __init__(
        self,
        pages: Sequence[Page],
        *,
        aliases: dict[str, str],
        min_similarity: float,
    ) -> None:
        self._titles: dict[str, list[str]] = defaultdict(list)
        self._headings: dict[str, list[str]] = defaultdict(list)
        for p in pages:
            self._titles[self.normalize(p.title)].append(p.slug)
            for heading in _HEADING.findall(p.body):
                key = self.normalize(heading)
                if p.slug not in self._headings[key]:
                    self._headings[key].append(p.slug)
        self._aliases = {self.normalize(a): self.normalize(t) for a, t in aliases.items()}
        self._min_similarity = min_similarity
        self._title_vectors: np.ndarray | None = None
        self._pages = pages

    def resolve_all(self, requests: list[tuple[str, str]]) -> dict[tuple[str, str], Resolution]:
        """Resolves each `(name, source_slug)` pair."""

        out: dict[tuple[str, str], Resolution] = {}
        pending: list[tuple[str, str]] = []
        for name, source in dict.fromkeys(requests):
            exact = self._exact(name, source)
            if exact is None:
                pending.append((name, source))
            else:
                out[name, source] = exact
        if pending:
            names = list(dict.fromkeys(n for n, _ in pending))
            nearest = self._nearest(names)
            for name, source in pending:
                slug, similarity = nearest[name]
                out[name, source] = (
                    Resolution(slug, "embedding", similarity)
                    if similarity >= self._min_similarity
                    else Resolution(None, "unresolved", similarity)
                )
        return out

    def _exact(self, name: str, source: str) -> Resolution | None:
        key = self.normalize(name)
        key = self._aliases.get(key, key)
        for table in (self._titles, self._headings):
            matches = table.get(key)
            if not matches:
                continue
            if len(matches) > 1:
                same_guide = [s for s in matches if self._guide(s) == self._guide(source)]
                matches = same_guide or matches
            if len(matches) == 1:
                return Resolution(matches[0], "exact")
            return Resolution(None, "ambiguous")
        return None

    def _nearest(self, names: list[str]) -> dict[str, tuple[str, float]]:
        if self._title_vectors is None:
            self._title_vectors = self._unit(self._embed([p.title for p in self._pages]))
        vectors = self._unit(self._embed(names))
        similarities = vectors @ self._title_vectors.T
        best = similarities.argmax(axis=1)
        return {
            name: (self._pages[int(j)].slug, float(similarities[i, j]))
            for i, (name, j) in enumerate(zip(names, best, strict=True))
        }

    @staticmethod
    def _embed(texts: list[str]) -> list[list[float]]:
        with ThreadPoolExecutor(max_workers=settings.entity_graph_llm_max_async) as pool:
            return list(pool.map(embedder.embed, texts))

    @staticmethod
    def normalize(name: str) -> str:
        """Folds case, accents, Markdown escapes and punctuation out of a name."""

        folded = unicodedata.normalize("NFKD", name.replace("\\", "")).casefold()
        return _NOT_WORD.sub(" ", folded).strip()

    @staticmethod
    def _guide(slug: str) -> str:
        return slug.partition(".")[0]

    @staticmethod
    def _unit(vectors: list[list[float]]) -> np.ndarray:
        matrix = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if (norms == 0).any():
            raise ValueError("the embedder returned a zero vector")
        return matrix / norms
