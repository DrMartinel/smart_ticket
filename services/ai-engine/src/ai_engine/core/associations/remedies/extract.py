"""
One DeepSeek call per section, its reply parsed against the policy's
bounds. Replies are cached in an append-only JSONL keyed by what the reply
depends on (policy version, model, section budget and the section's text),
so a re-run, a resumed run or a sample sharing the directory calls the
model only for sections it has never answered. A failed section is not
cached: the next run asks again.
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

from ai_engine.core.associations.remedies.policy import RemedyPolicy, ReplyLimits


class PageRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: str


@dataclass(frozen=True)
class Pair:
    """One problem a section helps solve. `page`: the page the text names
    as where the remedy is written, or None when it is this page."""

    symptom: str
    remedy: str
    page: str | None


def reply_model(limits: ReplyLimits) -> type[BaseModel]:
    """The reply's shape with the policy's bounds. A reply over them fails
    validation: never silently cut short."""

    pair = create_model(
        "RemedyPairReply",
        __config__=ConfigDict(extra="forbid"),
        symptom=(str, Field(min_length=1, max_length=limits.symptom_max_chars)),
        remedy=(str, Field(min_length=1, max_length=limits.remedy_max_chars)),
        remedy_location=(Literal["this_page"] | PageRef, ...),
    )
    return create_model(
        "RemedyReply",
        __config__=ConfigDict(extra="forbid"),
        pairs=(list[pair], Field(max_length=limits.max_pairs_per_section)),  # type: ignore[valid-type]
    )


def parse_reply(text: str, limits: ReplyLimits) -> list[Pair]:
    """Raises ValueError on anything but a reply within the bounds, and on a
    page name longer than the policy allows."""

    try:
        reply = reply_model(limits).model_validate_json(text)
    except ValidationError as e:
        raise ValueError(
            f"unusable reply: {e.error_count()} problem(s): {e.errors()[0]['msg']}"
        ) from e
    pairs = []
    for p in reply.pairs:  # type: ignore[attr-defined]
        page = None if p.remedy_location == "this_page" else p.remedy_location.page.strip()
        if page is not None and not (0 < len(page) <= limits.page_max_chars):
            raise ValueError(f"unusable reply: page name of {len(page)} characters")
        pairs.append(Pair(symptom=p.symptom.strip(), remedy=p.remedy.strip(), page=page))
    return pairs


def section_key(policy_version: str, model: str, section_tokens: int, text: str) -> str:
    spec = f"{policy_version}\nmodel={model}\nsection_tokens={section_tokens}\n{text}"
    return hashlib.sha256(spec.encode()).hexdigest()


class ReplyCache:
    """`{key: [pair, ...]}`, loaded from and appended to one JSONL. Lines
    are written as replies arrive, so an interrupted run keeps its work."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.replies: dict[str, list[Pair]] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.replies[row["key"]] = [Pair(**p) for p in row["pairs"]]

    def add(self, key: str, pairs: list[Pair]) -> None:
        self.replies[key] = pairs
        with self.path.open("a", encoding="utf-8") as f:
            row = {"key": key, "pairs": [p.__dict__ for p in pairs]}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


@dataclass
class Extraction:
    """Every requested section's pairs by key, the keys that failed (with
    why), and how many model calls were made."""

    pairs: dict[str, list[Pair]] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)
    calls: int = 0


async def extract(
    sections: dict[str, str],
    *,
    policy: RemedyPolicy,
    chat_model: BaseChatModel,
    cache: ReplyCache,
    max_async: int,
    retry_model: BaseChatModel | None = None,
) -> Extraction:
    """Pairs for every section (`{key: text}`), from the cache where it has
    them. A section whose call or reply fails is listed in `failed` and not
    cached; the caller exports nothing while any remain.

    A reply that fails validation is asked once more of `retry_model`
    (the same model at its default temperature): at temperature 0 the model
    replays the same malformed reply on every run, as it did for one
    section of the full build (2026-10-10), so a re-run alone never fixes
    it. A second unusable reply fails the section."""

    result = Extraction()
    limit = asyncio.Semaphore(max_async)
    messages = lambda text: [SystemMessage(content=policy.instructions), HumanMessage(content=text)]  # noqa: E731

    async def ask(model: BaseChatModel, text: str) -> list[Pair]:
        result.calls += 1
        reply = await model.ainvoke(messages(text))
        return parse_reply(_text(reply.content), policy.limits)

    async def one(key: str, text: str) -> None:
        async with limit:
            try:
                try:
                    pairs = await ask(chat_model, text)
                except ValueError:
                    if retry_model is None:
                        raise
                    pairs = await ask(retry_model, text)
            except Exception as e:  # noqa: BLE001 - recorded, retried on the next run
                result.failed[key] = f"{type(e).__name__}: {e}"[:300]
                return
        cache.add(key, pairs)
        result.pairs[key] = pairs

    todo = []
    for key, text in sections.items():
        if key in cache.replies:
            result.pairs[key] = cache.replies[key]
        else:
            todo.append(one(key, text))
    await asyncio.gather(*todo)
    return result


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(
        part.get("text", "") if isinstance(part, dict) else str(part) for part in content
    )
