"""
The offline `entity_graph` build (ADR-0018), end to end through a real
LightRAG with a scripted chat model and embedder: no GPU, no network. What
matters most is the failure path. A build that exported a graph silently
missing the articles whose extraction failed would look complete, and
expansion would quietly skip their pages; so a failure must mean no file,
exit 1, and a re-run that retries only what failed.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

pytest.importorskip("lightrag", reason="the build group: uv sync --all-packages --group build")

from ai_engine.core.associations import build  # noqa: E402
from ai_engine.core.config import settings  # noqa: E402
from ai_engine.core.db.tables import EMBED_DIM  # noqa: E402

VERIFY, PROD, SMTP = (uuid.UUID(int=i) for i in (1, 2, 3))
ARTICLES = [
    (VERIFY, "ses.verify", "In the SES Sandbox you can only send to verified addresses.", True),
    (PROD, "ses.prod", "Request production access to leave the SES Sandbox.", True),
    (SMTP, "ses.smtp", "Create SMTP credentials to send through the SMTP interface.", True),
]


class ScriptedChat:
    """Answers LightRAG's JSON extraction by the article in the prompt (its
    own boilerplate mentions neither phrase): "SES Sandbox" for the two
    sandbox pages, "SMTP Credentials" otherwise. Raises for text in
    `failing`."""

    def __init__(self, failing: tuple[str, ...] = ()) -> None:
        self.failing = failing
        self.calls = 0

    async def ainvoke(self, messages: list[Any], **_: Any) -> SimpleNamespace:
        self.calls += 1
        # The whole conversation: a gleaning call's last message asks for
        # missed entities without repeating the article.
        prompt = "\n".join(str(m.content) for m in messages)
        if any(text in prompt for text in self.failing):
            raise RuntimeError("model down")
        sandbox = "verified addresses" in prompt or "leave the SES" in prompt
        name, kind = ("SES Sandbox", "restriction") if sandbox else ("SMTP Credentials", "setting")
        reply = {
            "entities": [{"name": name, "type": kind, "description": "d"}],
            "relationships": [],
        }
        return SimpleNamespace(content=json.dumps(reply))


async def _embed(texts: list[str], **_: Any) -> np.ndarray:
    return np.ones((len(texts), EMBED_DIM), dtype=np.float32)


@pytest.fixture
def articles(fake_db, monkeypatch):
    rows = list(ARTICLES)
    monkeypatch.setattr(build, "db", fake_db(lambda sql, params: rows))
    return rows


def _run(tmp_path: Path, chat: ScriptedChat, *extra: str) -> int:
    args = build.parse_args(
        ["--working-dir", str(tmp_path / "w"), "--out", str(tmp_path / "out"), *extra]
    )
    return build.run(args, chat_model=chat, embed=_embed)


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_build_exports_mentions_and_the_scored_graph(articles, tmp_path):
    assert _run(tmp_path, ScriptedChat()) == 0

    mentions = _lines(tmp_path / "out" / build.MENTIONS_FILE)
    graph = _lines(tmp_path / "out" / build.GRAPH_FILE)
    assert {
        "entity": "SES Sandbox",
        "type": "restriction",
        "article_slug": "ses.verify",
    } in mentions
    assert {(r["source_slug"], r["target_slug"]) for r in graph} == {
        ("ses.verify", "ses.prod"),
        ("ses.prod", "ses.verify"),
    }
    assert graph[0]["evidence"] == ["SES Sandbox"]
    assert graph[0]["build_id"].startswith(
        f"entity_graph:{settings.entity_policy_version}:mentions-"
    )


def test_a_failed_article_means_no_file_exit_1_and_a_rerun_retries_only_it(
    articles, tmp_path, capsys
):
    assert _run(tmp_path, ScriptedChat(failing=("SMTP interface",))) == 1
    assert str(SMTP) in capsys.readouterr().err
    assert not (tmp_path / "out" / build.GRAPH_FILE).exists()
    assert not (tmp_path / "out" / build.MENTIONS_FILE).exists()

    retry = ScriptedChat()
    assert _run(tmp_path, retry) == 0
    # Only the SMTP article went back to the model; the other two were done.
    assert 0 < retry.calls <= 2
    assert (tmp_path / "out" / build.GRAPH_FILE).exists()


def test_an_unchanged_rebuild_makes_no_model_call(articles, tmp_path):
    assert _run(tmp_path, ScriptedChat()) == 0
    again = ScriptedChat()

    assert _run(tmp_path, again) == 0
    assert again.calls == 0


def test_a_changed_article_is_extracted_again_and_a_deleted_one_leaves_the_graph(
    articles, tmp_path
):
    assert _run(tmp_path, ScriptedChat()) == 0
    articles[1] = (PROD, "ses.prod", "Production access now means SMTP Credentials.", True)
    del articles[0]

    assert _run(tmp_path, ScriptedChat()) == 0

    mentions = _lines(tmp_path / "out" / build.MENTIONS_FILE)
    assert {m["article_slug"] for m in mentions} == {"ses.prod", "ses.smtp"}
    assert {"entity": "SMTP Credentials", "type": "setting", "article_slug": "ses.prod"} in mentions


def test_rescore_only_needs_no_working_dir_and_no_model(articles, tmp_path, monkeypatch):
    """After a policy change or deactivations: re-score the committed
    mentions. It must not construct LightRAG at all."""
    assert _run(tmp_path, ScriptedChat()) == 0
    monkeypatch.setattr(build, "make_rag", None)  # any call would raise

    args = build.parse_args(["--rescore-only", "--out", str(tmp_path / "out")])
    assert build.run(args) == 0


def test_a_sample_and_a_full_build_never_share_a_working_dir(articles, tmp_path, capsys):
    """Syncing one would delete the other's extracted articles."""
    assert _run(tmp_path, ScriptedChat(), "--sample", "2") == 0

    assert _run(tmp_path, ScriptedChat()) == 1
    assert "sample:2" in capsys.readouterr().err


class RecordingChat:
    def __init__(self) -> None:
        self.kwargs: list[dict[str, Any]] = []

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> SimpleNamespace:
        self.kwargs.append(kwargs)
        return SimpleNamespace(content='{"entities": [], "relationships": []}')


def test_a_json_request_is_decoded_against_the_policys_bounded_schema():
    """Asking Qwen for terse replies did not work: 13% of the spike's
    articles still overflowed the context mid-reply. The bound is enforced
    by guided decoding instead, from the versioned policy."""
    import asyncio

    from ai_engine.core.associations.adapter import ModelCalls, llm_func
    from ai_engine.core.associations.policy import load_entity_policy

    limits = load_entity_policy("kb_entities.v2").limits
    assert limits is not None
    chat = RecordingChat()
    complete = llm_func(chat, ModelCalls(), limits)  # type: ignore[arg-type]

    asyncio.run(complete("extract", response_format={"type": "json_object"}))
    asyncio.run(complete("summarize these descriptions"))

    schema = chat.kwargs[0]["response_format"]["json_schema"]["schema"]["properties"]
    assert schema["relationships"]["maxItems"] == 0
    assert schema["entities"]["maxItems"] == limits.max_entities_per_chunk
    assert schema["entities"]["items"]["properties"]["description"]["maxLength"] == (
        limits.description_max_chars
    )
    assert chat.kwargs[1] == {}  # a plain-text call is left alone
