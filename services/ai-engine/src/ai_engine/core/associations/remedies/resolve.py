"""
A page name as the text writes it ("Remediating a potentially compromised
Amazon EC2 instance") resolved to one KB page, deterministically:

1. exact: the normalized name equals a page title, then an H1/H2 heading,
   or an alias's canonical title (the policy's `aliases`);
2. embedding: otherwise, the page title nearest the name by cosine, if at
   least `REMEDY_RESOLVE_MIN_SIMILARITY`;
3. otherwise unresolved: dropped and counted, never guessed.

Several exact matches prefer the source page's own guide; still several is
ambiguous and dropped. Every resolution records how it was made, so the
spike can check each kind.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np

_HEADING = re.compile(r"^#{1,2} +(.+?)\s*$", re.MULTILINE)
_NOT_WORD = re.compile(r"[^0-9a-z]+")

Method = Literal["exact", "embedding", "unresolved", "ambiguous"]


@dataclass(frozen=True)
class Page:
    slug: str
    title: str
    body: str


@dataclass(frozen=True)
class Resolution:
    target: str | None
    method: Method
    similarity: float | None = None


def normalize(name: str) -> str:
    """Case, accents, Markdown escapes and punctuation folded away:
    "Backdoor:EC2/C&CActivity.B\\!DNS" and "backdoor ec2 c cactivity b dns"
    compare equal."""

    folded = unicodedata.normalize("NFKD", name.replace("\\", "")).casefold()
    return _NOT_WORD.sub(" ", folded).strip()


def guide(slug: str) -> str:
    return slug.partition(".")[0]


class PageIndex:
    def __init__(
        self,
        pages: list[Page],
        *,
        aliases: dict[str, str],
        embed: Callable[[list[str]], list[list[float]]],
        min_similarity: float,
    ) -> None:
        self._titles: dict[str, list[str]] = defaultdict(list)
        self._headings: dict[str, list[str]] = defaultdict(list)
        for p in pages:
            self._titles[normalize(p.title)].append(p.slug)
            for heading in _HEADING.findall(p.body):
                key = normalize(heading)
                if p.slug not in self._headings[key]:
                    self._headings[key].append(p.slug)
        self._aliases = {normalize(a): normalize(t) for a, t in aliases.items()}
        self._embed = embed
        self._min_similarity = min_similarity
        self._slugs = [p.slug for p in pages]
        self._title_vectors: np.ndarray | None = None
        self._pages = pages

    def resolve_all(self, requests: list[tuple[str, str]]) -> dict[tuple[str, str], Resolution]:
        """Resolutions for `(name, source_slug)` pairs. Names no title or
        heading matches are embedded in one batch, with the titles."""

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
        key = normalize(name)
        key = self._aliases.get(key, key)
        for table in (self._titles, self._headings):
            matches = table.get(key)
            if not matches:
                continue
            if len(matches) > 1:
                same_guide = [s for s in matches if guide(s) == guide(source)]
                matches = same_guide or matches
            if len(matches) == 1:
                return Resolution(matches[0], "exact")
            return Resolution(None, "ambiguous")
        return None

    def _nearest(self, names: list[str]) -> dict[str, tuple[str, float]]:
        if self._title_vectors is None:
            self._title_vectors = _unit(self._embed([p.title for p in self._pages]))
        vectors = _unit(self._embed(names))
        similarities = vectors @ self._title_vectors.T
        best = similarities.argmax(axis=1)
        return {
            name: (self._slugs[int(j)], float(similarities[i, j]))
            for i, (name, j) in enumerate(zip(names, best, strict=True))
        }


def _unit(vectors: list[list[float]]) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if (norms == 0).any():
        raise ValueError("the embedder returned a zero vector")
    return matrix / norms
