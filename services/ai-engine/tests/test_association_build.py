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
        f"entity_graph:{settings.entity_policy_version}:{settings.association_scoring}:mentions-"
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


def test_on_deepseek_no_schema_is_sent(monkeypatch, tmp_path):
    """DeepSeek refuses a `json_schema` reply with a 400 (ADR-0019): every
    extraction would fail. LightRAG's own `json_object` request goes through."""
    from ai_engine.core.associations import adapter
    from ai_engine.core.associations.policy import load_entity_policy

    seen = {}
    monkeypatch.setattr(settings, "chat_client_provider", "deepseek")
    monkeypatch.setattr(
        adapter,
        "llm_func",
        lambda model, calls, limits=None: seen.update(limits=limits) or (lambda: None),
    )

    adapter.make_rag(
        tmp_path,
        guidance="g",
        calls=adapter.ModelCalls(),
        limits=load_entity_policy("kb_entities.v2").limits,
        chat_model=RecordingChat(),  # type: ignore[arg-type]
        embed=_embed,
    )

    assert seen == {"limits": None}


def test_another_model_never_reuses_a_working_dir(articles, tmp_path, monkeypatch, capsys):
    """LightRAG caches replies by prompt text, so a second model in the same
    directory would get the first one's replies back as its own."""
    monkeypatch.setattr(settings, "chat_client_provider", "vllm")
    assert _run(tmp_path, ScriptedChat()) == 0
    monkeypatch.setattr(settings, "chat_client_provider", "deepseek")
    monkeypatch.setattr(settings, "cloud_model", "deepseek-flash")

    assert _run(tmp_path, ScriptedChat()) == 1
    assert "deepseek:deepseek-flash" in capsys.readouterr().err


def test_a_resume_processes_queued_articles_instead_of_deleting_them(
    articles, tmp_path, monkeypatch
):
    """An aborted batch leaves its articles queued (pending), never extracted.
    Deleting them rewrites the whole graph file per article: on the full KB,
    about 8 a minute, hours for the 1,955 a dropped connection left queued
    (2026-10-10). Their queued text is current, so the queue runs them."""
    import asyncio

    from lightrag import LightRAG
    from lightrag.kg.shared_storage import finalize_share_data

    from ai_engine.core.associations.adapter import FILE_PATH_PREFIX, ModelCalls, make_rag

    monkeypatch.setattr(settings, "chat_client_provider", "vllm")
    working = tmp_path / "w"
    working.mkdir()

    async def queue_without_processing() -> None:
        rag = make_rag(
            working, guidance="g", calls=ModelCalls(), chat_model=ScriptedChat(), embed=_embed
        )  # type: ignore[arg-type]
        await rag.initialize_storages()
        try:
            await rag.apipeline_enqueue_documents(
                [body for _, _, body, _ in ARTICLES],
                ids=[str(i) for i, *_ in ARTICLES],
                file_paths=[f"{FILE_PATH_PREFIX}{i}" for i, *_ in ARTICLES],
            )
        finally:
            await rag.finalize_storages()
            finalize_share_data()

    asyncio.run(queue_without_processing())
    deleted: list[str] = []
    real_delete = LightRAG.adelete_by_doc_id

    async def recording_delete(self, doc_id, *args, **kwargs):
        deleted.append(doc_id)
        return await real_delete(self, doc_id, *args, **kwargs)

    monkeypatch.setattr(LightRAG, "adelete_by_doc_id", recording_delete)
    chat = ScriptedChat()

    assert _run(tmp_path, chat) == 0
    assert deleted == []
    assert chat.calls > 0
    graph = _lines(tmp_path / "out" / build.GRAPH_FILE)
    assert {(r["source_slug"], r["target_slug"]) for r in graph} == {
        ("ses.verify", "ses.prod"),
        ("ses.prod", "ses.verify"),
    }


def test_a_copy_with_identical_text_mirrors_its_original_without_linking_to_it(
    articles, tmp_path, monkeypatch
):
    """15 demo-KB pages exist under two URLs with the same text. LightRAG
    refuses the second as a duplicate on every run, so the build could never
    export. The copy takes the original's entities, and the twin edge, which
    would always rank first, is dropped."""
    monkeypatch.setattr(settings, "chat_client_provider", "vllm")
    verify_body = articles[0][2]
    articles.append((uuid.UUID(int=4), "ses.verify-copy", verify_body, True))

    assert _run(tmp_path, ScriptedChat()) == 0

    mentions = _lines(tmp_path / "out" / build.MENTIONS_FILE)
    graph = {
        (r["source_slug"], r["target_slug"]) for r in _lines(tmp_path / "out" / build.GRAPH_FILE)
    }
    assert {
        "entity": "SES Sandbox",
        "type": "restriction",
        "article_slug": "ses.verify-copy",
    } in mentions
    assert ("ses.verify-copy", "ses.prod") in graph
    assert ("ses.verify", "ses.verify-copy") not in graph
    assert ("ses.verify-copy", "ses.verify") not in graph
