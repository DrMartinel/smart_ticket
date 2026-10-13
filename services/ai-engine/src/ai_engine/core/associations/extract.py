"""
Asks the model for each section's (symptom, remedy, where) pairs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from ai_engine.core.associations.policy import EntityGraphPolicy, ReplyLimits


class PageRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: str


@dataclass(frozen=True)
class Pair:
    """One problem a section helps solve, and the page with its remedy (None: this page)."""

    symptom: str
    remedy: str
    page: str | None


class ReplyParser:
    """Parses a model reply into pairs within the policy's bounds."""

    def __init__(self, limits: ReplyLimits) -> None:
        self._limits = limits
        self._reply = self._reply_model(limits)

    @staticmethod
    def _reply_model(limits: ReplyLimits) -> type[BaseModel]:
        pair = create_model(
            "PairReply",
            __config__=ConfigDict(extra="forbid"),
            symptom=(str, Field(min_length=1, max_length=limits.symptom_max_chars)),
            remedy=(str, Field(min_length=1, max_length=limits.remedy_max_chars)),
            remedy_location=(Literal["this_page"] | PageRef, ...),
        )
        return create_model(
            "Reply",
            __config__=ConfigDict(extra="forbid"),
            pairs=(list[pair], Field(max_length=limits.max_pairs_per_section)),  # type: ignore[valid-type]
        )

    def parse(self, text: str) -> list[Pair]:
        """Parses a reply into pairs."""

        try:
            reply = self._reply.model_validate_json(text)
        except ValidationError as e:
            raise ValueError(
                f"unusable reply: {e.error_count()} problem(s): {e.errors()[0]['msg']}"
            ) from e
        pairs = []
        for p in reply.pairs:  # type: ignore[attr-defined]
            page = None if p.remedy_location == "this_page" else p.remedy_location.page.strip()
            if page is not None and not (0 < len(page) <= self._limits.page_max_chars):
                raise ValueError(f"unusable reply: page name of {len(page)} characters")
            pairs.append(Pair(symptom=p.symptom.strip(), remedy=p.remedy.strip(), page=page))
        return pairs


class ReplyCache:
    """The model's pairs by section key, loaded from and appended to one JSONL."""

    def __init__(self, path: Path, replies: dict[str, list[Pair]]) -> None:
        self.path = path
        self.replies = replies

    @classmethod
    def load(cls, path: Path) -> ReplyCache:
        """Reads the cache from `path`, empty if the file doesn't exist yet."""

        replies: dict[str, list[Pair]] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    replies[row["key"]] = [Pair(**p) for p in row["pairs"]]
        return cls(path, replies)

    @staticmethod
    def key(policy_version: str, model: str, section_tokens: int, text: str) -> str:
        """Builds the cache key of one section."""

        spec = f"{policy_version}\nmodel={model}\nsection_tokens={section_tokens}\n{text}"
        return hashlib.sha256(spec.encode()).hexdigest()

    def add(self, key: str, pairs: list[Pair]) -> None:
        """Stores one section's pairs."""

        self.replies[key] = pairs
        with self.path.open("a", encoding="utf-8") as f:
            row = {"key": key, "pairs": [p.__dict__ for p in pairs]}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


@dataclass
class Extraction:
    """Each section's pairs by key, the keys that failed and the number of model calls."""

    pairs: dict[str, list[Pair]] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)
    calls: int = 0


class PairExtractor:
    """Gets each section's pairs from the cache or the model."""

    def __init__(
        self,
        *,
        policy: EntityGraphPolicy,
        chat_model: BaseChatModel,
        cache: ReplyCache,
        max_async: int,
        retry_model: BaseChatModel | None = None,
    ) -> None:
        self._policy = policy
        self._chat_model = chat_model
        self._retry_model = retry_model
        self._cache = cache
        self._max_async = max_async
        self._parser = ReplyParser(policy.limits)

    async def extract(self, sections: dict[str, str]) -> Extraction:
        """Gets the pairs of every section in `sections` (key -> text)."""

        result = Extraction()
        limit = asyncio.Semaphore(self._max_async)

        async def one(key: str, text: str) -> None:
            async with limit:
                try:
                    try:
                        pairs = await self._ask(self._chat_model, text, result)
                    except ValueError:
                        if self._retry_model is None:
                            raise
                        pairs = await self._ask(self._retry_model, text, result)
                except Exception as e:  # noqa: BLE001
                    result.failed[key] = f"{type(e).__name__}: {e}"[:300]
                    return
            self._cache.add(key, pairs)
            result.pairs[key] = pairs

        todo = []
        for key, text in sections.items():
            if key in self._cache.replies:
                result.pairs[key] = self._cache.replies[key]
            else:
                todo.append(one(key, text))
        await asyncio.gather(*todo)
        return result

    async def _ask(self, model: BaseChatModel, text: str, result: Extraction) -> list[Pair]:
        result.calls += 1
        reply = await model.ainvoke(
            [SystemMessage(content=self._policy.instructions), HumanMessage(content=text)]
        )
        return self._parser.parse(self._text(reply.content))

    @staticmethod
    def _text(content: Any) -> str:
        if isinstance(content, str):
            return content
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
