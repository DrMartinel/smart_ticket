"""
Checks the offline `entity_graph` build (ADR-0018, ADR-0025): sections,
replies, page resolution, edge ranking and the write, with the model, the
database and the embedder faked.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from ai_engine.core.associations import build
from ai_engine.core.associations.extract import Pair, ReplyCache, ReplyParser
from ai_engine.core.associations.policy import EntityGraphPolicy, ReplyLimits
from ai_engine.core.associations.resolve import PageIndex
from ai_engine.core.associations.sections import SectionSplitter
from ai_engine.core.config import settings
from ai_engine.core.providers.clients import ChatClient

LIMITS = ReplyLimits(
    max_pairs_per_section=3, symptom_max_chars=50, remedy_max_chars=50, page_max_chars=60
)


def _words(text: str) -> int:
    return len(text.split())


# --- sections ------------------------------------------------------------------


def test_links_are_stripped_to_their_text():
    text = "To fix it, see [Remediating an instance](compromised-ec2.md). ![diagram](a.png)"

    assert SectionSplitter.strip_links(text) == "To fix it, see Remediating an instance. diagram"


def test_sections_keep_headings_together_and_never_exceed_the_budget():
    text = "# A\none two\n## B\nthree four\n## C\n" + " ".join(["w"] * 25)

    sections = SectionSplitter(max_tokens=10, count=_words).split(text)

    assert sections[0] == "# A\none two\n\n## B\nthree four\n"
    assert all(_words(s) <= 10 for s in sections)
    assert " ".join(" ".join(sections).split()) == " ".join(text.split())


# --- replies -------------------------------------------------------------------


def test_a_reply_over_the_pair_limit_fails_rather_than_being_cut():
    reply = {"pairs": [{"symptom": "s", "remedy": "r", "remedy_location": "this_page"}] * 4}

    with pytest.raises(ValueError, match="unusable reply"):
        ReplyParser(LIMITS).parse(json.dumps(reply))


@pytest.mark.parametrize(
    "reply",
    [
        "not json",
        '{"pairs": [{"symptom": "s", "remedy": "r"}]}',
        '{"pairs": [{"symptom": "s", "remedy": "r", "remedy_location": "elsewhere"}]}',
        '{"pairs": [], "note": "extra"}',
        '{"pairs": [{"symptom": "s", "remedy": "r", "remedy_location": {"page": "  "}}]}',
    ],
)
def test_a_malformed_reply_fails(reply):
    with pytest.raises(ValueError, match="unusable reply"):
        ReplyParser(LIMITS).parse(reply)


def test_this_page_has_no_target_and_a_named_page_is_kept_as_written():
    reply = {
        "pairs": [
            {"symptom": "bounce", "remedy": "verify", "remedy_location": "this_page"},
            {
                "symptom": "sandbox",
                "remedy": "request",
                "remedy_location": {"page": " Request access "},
            },
        ]
    }

    assert ReplyParser(LIMITS).parse(json.dumps(reply)) == [
        Pair("bounce", "verify", None),
        Pair("sandbox", "request", "Request access"),
    ]


def test_the_cache_key_is_unchanged():
    expected = hashlib.sha256(b"kb_entity_graph.v1\nmodel=deepseek:m\nsection_tokens=3000\ntext")

    assert ReplyCache.key("kb_entity_graph.v1", "deepseek:m", 3000, "text") == expected.hexdigest()


# --- resolution ----------------------------------------------------------------


@dataclass(frozen=True)
class Page:
    slug: str
    title: str
    body: str


class TextEmbedder:
    """Embeds each text with `vectors`, a function from texts to vectors."""

    def __init__(self, vectors) -> None:
        self._vectors = vectors

    def embed(self, text: str) -> list[float]:
        return self._vectors([text])[0]


def _no_embed(texts):
    raise AssertionError("an exact match must not need the embedder")


@pytest.fixture
def index(use_embedder):
    def build_index(pages, embed=_no_embed, aliases=None, bar=0.9):
        use_embedder(TextEmbedder(embed))
        return PageIndex(pages, aliases=aliases or {}, min_similarity=bar)

    return build_index


PAGES = [
    Page(
        "guardduty.compromised-ec2",
        "Remediating a potentially compromised Amazon EC2 instance",
        "# x",
    ),
    Page("guardduty.troubleshoot", "Troubleshooting", "# Troubleshooting\n## Findings not shown"),
    Page("ses.troubleshoot", "Troubleshooting", "# Troubleshooting"),
]


def test_an_exact_title_or_heading_resolves_without_the_embedder(index):
    index = index(PAGES)

    r = index.resolve_all(
        [
            ("remediating a potentially-compromised Amazon EC2 instance", "guardduty.x"),
            ("Findings not shown", "ses.y"),
        ]
    )

    assert r["remediating a potentially-compromised Amazon EC2 instance", "guardduty.x"].target == (
        "guardduty.compromised-ec2"
    )
    assert r["Findings not shown", "ses.y"].target == "guardduty.troubleshoot"


def test_a_shared_title_prefers_the_source_guide_and_is_otherwise_ambiguous(index):
    index = index(PAGES)

    r = index.resolve_all([("Troubleshooting", "ses.page"), ("Troubleshooting", "iam.page")])

    assert r["Troubleshooting", "ses.page"].target == "ses.troubleshoot"
    assert r["Troubleshooting", "iam.page"].method == "ambiguous"
    assert r["Troubleshooting", "iam.page"].target is None


def test_an_embedding_match_counts_only_at_or_above_the_bar(index):
    vectors = {
        PAGES[0].title: [1.0, 0.0],
        PAGES[1].title: [0.0, 1.0],
        "fixing a hacked EC2 server": [0.95, 0.31],
        "something unrelated": [0.6, 0.8],
    }
    index = index(PAGES, embed=lambda texts: [vectors[t] for t in texts], bar=0.9)

    r = index.resolve_all([("fixing a hacked EC2 server", "a.b"), ("something unrelated", "a.b")])

    assert r["fixing a hacked EC2 server", "a.b"].target == "guardduty.compromised-ec2"
    assert r["fixing a hacked EC2 server", "a.b"].method == "embedding"
    assert r["something unrelated", "a.b"].target is None
    assert r["something unrelated", "a.b"].method == "unresolved"


def test_an_alias_resolves_exactly(index):
    index = index(PAGES, aliases={"compromised instance guide": PAGES[0].title})

    r = index.resolve_all([("Compromised instance guide", "a.b")])

    assert r["Compromised instance guide", "a.b"].target == "guardduty.compromised-ec2"


def test_normalize_folds_escapes_case_and_punctuation():
    assert PageIndex.normalize("Backdoor:EC2/C&CActivity.B\\!DNS") == PageIndex.normalize(
        "backdoor ec2 c cactivity b dns"
    )


# --- the build, end to end -----------------------------------------------------

FINDINGS, FIX, SANDBOX, COPY = (uuid.UUID(int=i) for i in (1, 2, 3, 4))
ROWS = [
    # (id, slug, title, body)
    (
        FINDINGS,
        "gd.findings",
        "EC2 finding types",
        "# EC2 finding types\nBackdoor found. To remediate, see [Fixing instances](fix.md).",
    ),
    (FIX, "gd.fix", "Fixing instances", "# Fixing instances\nIsolate the instance."),
    (SANDBOX, "ses.sandbox", "Sandbox", "# Sandbox\nSending fails. See Sandbox."),
    (
        COPY,
        "gd.findings-copy",
        "EC2 finding types",
        "# EC2 finding types\nBackdoor found. To remediate, see [Fixing instances](fix.md).",
    ),
]


class ScriptedChat:
    """Answers by the section's text. Raises for text in `failing`."""

    def __init__(self, failing: tuple[str, ...] = ()) -> None:
        self.failing = failing
        self.sections: list[str] = []

    async def ainvoke(self, messages: list[Any], **_: Any) -> SimpleNamespace:
        text = str(messages[-1].content)
        self.sections.append(text)
        if any(f in text for f in self.failing):
            raise RuntimeError("model down")
        if "Backdoor" in text:
            pairs = [
                {
                    "symptom": "backdoor finding",
                    "remedy": "isolate",
                    "remedy_location": {"page": "Fixing instances"},
                }
            ]
        elif "Sending fails" in text:
            pairs = [
                {
                    "symptom": "sending fails",
                    "remedy": "leave sandbox",
                    "remedy_location": {"page": "Sandbox"},
                },
                {
                    "symptom": "quota",
                    "remedy": "ask",
                    "remedy_location": {"page": "Quota increase form"},
                },
            ]
        else:
            pairs = [
                {"symptom": "compromised", "remedy": "isolate", "remedy_location": "this_page"}
            ]
        return SimpleNamespace(content=json.dumps({"pairs": pairs}))


def _no_match(texts):
    return [[1.0, 0.0] if t != "Quota increase form" else [0.0, 1.0] for t in texts]


@pytest.fixture
def kb(fake_db, monkeypatch):
    fake = fake_db(lambda sql, params: list(ROWS))
    monkeypatch.setattr(build, "db", fake)
    return fake


@pytest.fixture
def run(monkeypatch, use_embedder, tmp_path):
    """Runs the build with `chat` as DeepSeek and `retry` as its retry model;
    with no `chat`, building a model fails the test."""

    def run_build(chat, *extra, retry=None):
        def deepseek_model(*, json_mode, temperature=None):
            if chat is None:
                raise AssertionError("this build must not build a model")
            return chat if temperature == 0 else retry

        monkeypatch.setattr(ChatClient, "deepseek_model", staticmethod(deepseek_model))
        use_embedder(TextEmbedder(_no_match))
        args = build.EntityGraphBuild.parse_args(
            ["--working-dir", str(tmp_path / "w"), "--out", str(tmp_path / "out"), *extra]
        )
        return build.EntityGraphBuild(args).run()

    return run_build


def _lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_failed_section_exports_nothing_and_a_rerun_asks_only_for_it(kb, tmp_path, capsys, run):
    assert run(ScriptedChat(failing=("Sending fails",))) == 1
    assert "ses.sandbox" in capsys.readouterr().err
    assert not (tmp_path / "out" / build.BuildFiles.GRAPH).exists()
    assert not (tmp_path / "out" / build.BuildFiles.PAIRS).exists()
    assert kb.writes == []

    retry = ScriptedChat()
    assert run(retry) == 0
    assert len(retry.sections) == 1 and "Sending fails" in retry.sections[0]


def test_an_unchanged_rebuild_makes_no_model_call(kb, run):
    assert run(ScriptedChat()) == 0
    again = ScriptedChat()
    assert run(again) == 0
    assert again.sections == []


def test_the_model_never_sees_a_link_target(kb, run):
    chat = ScriptedChat()
    run(chat)

    assert all("fix.md" not in s for s in chat.sections)


def test_pointer_edges_link_the_problem_page_to_the_fix_page(kb, tmp_path, run):
    chat = ScriptedChat()
    assert run(chat) == 0

    edges = {
        (r["source_slug"], r["target_slug"]): r
        for r in _lines(tmp_path / "out" / build.BuildFiles.GRAPH)
    }
    assert set(edges) == {("gd.findings", "gd.fix"), ("gd.findings-copy", "gd.fix")}
    assert edges["gd.findings", "gd.fix"]["evidence"] == ["backdoor finding -> isolate"]
    assert edges["gd.findings", "gd.fix"]["build_id"].startswith(
        f"entity_graph:{settings.entity_graph_policy_version}:pairs-"
    )
    assert sum("Backdoor" in s for s in chat.sections) == 1

    resolutions = {
        (r["source_slug"], r["name"]): r
        for r in _lines(tmp_path / "out" / build.BuildFiles.RESOLUTIONS)
    }
    assert resolutions["ses.sandbox", "Sandbox"]["target_slug"] == "ses.sandbox"
    assert resolutions["ses.sandbox", "Quota increase form"]["method"] == "unresolved"


def _inserted(write):
    """Collects the edges one write inserted."""

    return {(r["source_article_id"], r["target_article_id"]) for r in write[1][1]}


def test_the_edges_replace_every_entity_graph_row_in_one_transaction(kb, run):
    assert run(ScriptedChat()) == 0

    assert len(kb.writes) == 1
    (clear_sql, clear_rows), (insert_sql, rows) = kb.writes[0]
    assert clear_sql.startswith("DELETE FROM kb_article_associations")
    assert "WHERE kb_article_associations.source = " in clear_sql and clear_rows is None
    assert insert_sql.startswith("INSERT INTO kb_article_associations")
    assert _inserted(kb.writes[0]) == {(FINDINGS, FIX), (COPY, FIX)}
    assert {r["source"] for r in rows} == {"entity_graph"}
    assert all(r["reviewed"] is False and r["id"] for r in rows)


def test_a_failed_write_exits_1(fake_db, monkeypatch, capsys, run):
    from sqlalchemy.exc import ProgrammingError

    denied = ProgrammingError("INSERT", {}, Exception("permission denied"))
    monkeypatch.setattr(build, "db", fake_db(lambda sql, params: list(ROWS), write_error=denied))

    assert run(ScriptedChat()) == 1
    assert "permission denied" in capsys.readouterr().err


def test_a_sample_writes_no_row(kb, monkeypatch, run):
    monkeypatch.setattr(
        build.KbSnapshot,
        "sample",
        lambda self, size, include: build.KbSnapshot(self.articles[:1]),
    )

    assert run(ScriptedChat(), "--sample", "1") == 0
    assert kb.writes == []


def test_rescore_only_writes_and_skips_a_page_no_longer_in_the_kb(kb, tmp_path, capsys, run):
    out = tmp_path / "out"
    out.mkdir()
    gone = build.PagePair("gd.deleted", "backdoor", "isolate", "Fixing instances")
    kept = build.PagePair("gd.findings", "backdoor", "isolate", "Fixing instances")
    build.BuildFiles(out).write(build.BuildFiles.PAIRS, [gone, kept])

    assert run(None, "--rescore-only") == 0

    assert _inserted(kb.writes[0]) == {(FINDINGS, FIX)}
    assert "1 written, 1 skipped" in capsys.readouterr().out


def test_rescore_only_needs_no_model(kb, run):
    assert run(ScriptedChat()) == 0

    assert run(None, "--rescore-only") == 0


def test_the_shipped_policy_loads():
    policy = EntityGraphPolicy.load(settings.entity_graph_policy_version)

    assert policy.strip_links is True
    assert policy.limits.max_pairs_per_section > 0


def test_a_sampled_page_can_point_to_a_page_outside_the_sample(kb, tmp_path, monkeypatch, run):
    monkeypatch.setattr(
        build.KbSnapshot,
        "sample",
        lambda self, size, include: build.KbSnapshot(self.articles[:1]),
    )

    assert run(ScriptedChat(), "--sample", "1") == 0

    edges = _lines(tmp_path / "out" / build.BuildFiles.GRAPH)
    assert [(r["source_slug"], r["target_slug"]) for r in edges] == [("gd.findings", "gd.fix")]


class OnceBroken(ScriptedChat):
    """Replies with malformed JSON every time."""

    async def ainvoke(self, messages, **kw):
        self.sections.append(str(messages[-1].content))
        return SimpleNamespace(content='{"pairs": [{bad json')


def test_an_unusable_reply_is_asked_once_more_of_the_retry_model(kb, run):
    retry = ScriptedChat()

    assert run(OnceBroken(), retry=retry) == 0
    assert len(retry.sections) == 3


def test_a_second_unusable_reply_still_fails_the_section(kb, tmp_path, run):
    assert run(OnceBroken(), retry=OnceBroken()) == 1
    assert not (tmp_path / "out" / build.BuildFiles.GRAPH).exists()


def test_the_same_pair_both_here_and_on_another_page_exports(kb, run):
    class BothPlaces(ScriptedChat):
        async def ainvoke(self, messages, **kw):
            pairs = [
                {"symptom": "s", "remedy": "r", "remedy_location": "this_page"},
                {"symptom": "s", "remedy": "r", "remedy_location": {"page": "Fixing instances"}},
            ]
            return SimpleNamespace(content=json.dumps({"pairs": pairs}))

    assert run(BothPlaces()) == 0


# --- edge ranking --------------------------------------------------------------

RANKED = [
    build.Article(uuid.UUID(int=10), "a.src", "Src", "a.src body"),
    build.Article(uuid.UUID(int=11), "b.two", "Two", "b.two body"),
    build.Article(uuid.UUID(int=12), "c.one", "One", "c.one body"),
    build.Article(uuid.UUID(int=13), "d.one", "Other one", "d.one body"),
    build.Article(uuid.UUID(int=14), "a.emb", "Embedded", "a.emb body"),
]
RANKED_PAIRS = [
    build.PagePair("a.src", "s1", "r", "Two"),
    build.PagePair("a.src", "s2", "r", "Two"),
    build.PagePair("a.src", "s3", "r", "One"),
    build.PagePair("a.src", "s4", "r", "Other one"),
    build.PagePair("a.src", "s5", "r", "Something embedded"),
]


def _one_hot(texts):
    order = ["Src", "Two", "One", "Other one", "Embedded"]
    return [[1.0 if (t if t in order else "Embedded") == o else 0.0 for o in order] for t in texts]


def _ranked(monkeypatch, use_embedder, cap):
    monkeypatch.setattr(settings, "association_per_article_cap", cap)
    use_embedder(TextEmbedder(_one_hot))
    policy = EntityGraphPolicy.load(settings.entity_graph_policy_version)
    scorer = build.EdgeScorer(policy=policy)
    rows, _ = scorer.score(RANKED_PAIRS, build.KbSnapshot(RANKED))
    return rows


def test_targets_rank_by_pairs_then_exact_before_embedding_then_slug(monkeypatch, use_embedder):
    rows = _ranked(monkeypatch, use_embedder, cap=10)

    assert [(r.target_slug, r.score) for r in rows] == [
        ("b.two", 2.0),
        ("c.one", 1.0),
        ("d.one", 1.0),
        ("a.emb", 1.0),
    ]


def test_the_cap_keeps_the_top_ranked_targets(monkeypatch, use_embedder):
    rows = _ranked(monkeypatch, use_embedder, cap=3)

    assert [r.target_slug for r in rows] == ["b.two", "c.one", "d.one"]


def test_the_build_id_names_the_policy_and_the_pairs(monkeypatch, use_embedder):
    rows = _ranked(monkeypatch, use_embedder, cap=10)

    assert re.fullmatch(
        rf"entity_graph:{re.escape(settings.entity_graph_policy_version)}"
        r":pairs-[0-9a-f]{12}:\d{4}-\d{2}-\d{2}",
        rows[0].build_id,
    )
