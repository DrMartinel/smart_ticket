"""
The offline `entity_graph` build (ADR-0018): sections in, one
model call per section, (symptom, remedy, where) pairs out, named pages
resolved to KB pages, pointer edges scored. The model, the database and the
embedder are fakes. What these pin, failure paths first: a failed section
exports nothing and is the only thing a re-run asks for; a reply outside
the policy's bounds is never partly used; a name that resolves to no page,
to several, or to the page itself makes no edge; and an embedding match
counts only above its bar, after exact matches.
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

LIMITS = ReplyLimits(
    max_pairs_per_section=3, symptom_max_chars=50, remedy_max_chars=50, page_max_chars=60
)


def _words(text: str) -> int:
    return len(text.split())


# --- sections ------------------------------------------------------------------


def test_links_are_stripped_to_their_text():
    """A URL must never reach the model: the graph would copy the authored
    links instead of reading the prose."""

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
    """Keeping the first N pairs would drop pointers silently, with the
    section counted as done."""

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


def _index(pages, embed=None, aliases=None, bar=0.9):
    def no_embed(texts):
        raise AssertionError("an exact match must not need the embedder")

    return PageIndex(pages, aliases=aliases or {}, embed=embed or no_embed, min_similarity=bar)


PAGES = [
    Page(
        "guardduty.compromised-ec2",
        "Remediating a potentially compromised Amazon EC2 instance",
        "# x",
    ),
    Page("guardduty.troubleshoot", "Troubleshooting", "# Troubleshooting\n## Findings not shown"),
    Page("ses.troubleshoot", "Troubleshooting", "# Troubleshooting"),
]


def test_an_exact_title_or_heading_resolves_without_the_embedder():
    index = _index(PAGES)

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


def test_a_shared_title_prefers_the_source_guide_and_is_otherwise_ambiguous():
    """Two guides both have "Troubleshooting": from an SES page it means
    SES's; from a third guide it means nothing, and is dropped."""

    index = _index(PAGES)

    r = index.resolve_all([("Troubleshooting", "ses.page"), ("Troubleshooting", "iam.page")])

    assert r["Troubleshooting", "ses.page"].target == "ses.troubleshoot"
    assert r["Troubleshooting", "iam.page"].method == "ambiguous"
    assert r["Troubleshooting", "iam.page"].target is None


def test_an_embedding_match_counts_only_at_or_above_the_bar():
    """Below the bar the nearest title is a guess: unresolved, not linked."""

    vectors = {
        PAGES[0].title: [1.0, 0.0],
        PAGES[1].title: [0.0, 1.0],
        "fixing a hacked EC2 server": [0.95, 0.31],
        "something unrelated": [0.6, 0.8],
    }
    index = _index(PAGES, embed=lambda texts: [vectors[t] for t in texts], bar=0.9)

    r = index.resolve_all([("fixing a hacked EC2 server", "a.b"), ("something unrelated", "a.b")])

    assert r["fixing a hacked EC2 server", "a.b"].target == "guardduty.compromised-ec2"
    assert r["fixing a hacked EC2 server", "a.b"].method == "embedding"
    assert r["something unrelated", "a.b"].target is None
    assert r["something unrelated", "a.b"].method == "unresolved"


def test_an_alias_resolves_exactly():
    index = _index(PAGES, aliases={"compromised instance guide": PAGES[0].title})

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


def _run(tmp_path, chat, *extra):
    args = build.EntityGraphBuild.parse_args(
        ["--working-dir", str(tmp_path / "w"), "--out", str(tmp_path / "out"), *extra]
    )
    return build.EntityGraphBuild(args, chat_model=chat, embed=_no_match).run()


def _lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_failed_section_exports_nothing_and_a_rerun_asks_only_for_it(kb, tmp_path, capsys):
    """An exported graph missing pages would look complete. The reply
    cache keeps the sections that worked, so the re-run costs one call."""

    assert _run(tmp_path, ScriptedChat(failing=("Sending fails",))) == 1
    assert "ses.sandbox" in capsys.readouterr().err
    assert not (tmp_path / "out" / build.BuildFiles.GRAPH).exists()
    assert not (tmp_path / "out" / build.BuildFiles.PAIRS).exists()
    assert kb.writes == []

    retry = ScriptedChat()
    assert _run(tmp_path, retry) == 0
    assert len(retry.sections) == 1 and "Sending fails" in retry.sections[0]


def test_an_unchanged_rebuild_makes_no_model_call(kb, tmp_path):
    assert _run(tmp_path, ScriptedChat()) == 0
    again = ScriptedChat()
    assert _run(tmp_path, again) == 0
    assert again.sections == []


def test_the_model_never_sees_a_link_target(kb, tmp_path):
    chat = ScriptedChat()
    _run(tmp_path, chat)

    assert all("fix.md" not in s for s in chat.sections)


def test_pointer_edges_link_the_problem_page_to_the_fix_page(kb, tmp_path):
    """this_page pairs, a page naming itself, and a name resolving to no
    page make no edge; a copy of a page gets its original's edges without
    being sent to the model, and never an edge to its twin."""

    chat = ScriptedChat()
    assert _run(tmp_path, chat) == 0

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


def test_the_edges_replace_every_entity_graph_row_in_one_transaction(kb, tmp_path):
    assert _run(tmp_path, ScriptedChat()) == 0

    assert len(kb.writes) == 1
    (clear_sql, clear_rows), (insert_sql, rows) = kb.writes[0]
    assert clear_sql.startswith("DELETE FROM kb_article_associations")
    assert "WHERE kb_article_associations.source = " in clear_sql and clear_rows is None
    assert insert_sql.startswith("INSERT INTO kb_article_associations")
    assert _inserted(kb.writes[0]) == {(FINDINGS, FIX), (COPY, FIX)}
    assert {r["source"] for r in rows} == {"entity_graph"}
    assert all(r["reviewed"] is False and r["id"] for r in rows)


def test_a_failed_write_exits_1(fake_db, monkeypatch, tmp_path, capsys):
    from sqlalchemy.exc import ProgrammingError

    denied = ProgrammingError("INSERT", {}, Exception("permission denied"))
    monkeypatch.setattr(build, "db", fake_db(lambda sql, params: list(ROWS), write_error=denied))

    assert _run(tmp_path, ScriptedChat()) == 1
    assert "permission denied" in capsys.readouterr().err


def test_a_sample_writes_no_row(kb, tmp_path, monkeypatch):
    monkeypatch.setattr(
        build.KbSnapshot,
        "sample",
        lambda self, size, include: build.KbSnapshot(self.articles[:1]),
    )

    assert _run(tmp_path, ScriptedChat(), "--sample", "1") == 0
    assert kb.writes == []


def test_rescore_only_writes_and_skips_a_page_no_longer_in_the_kb(kb, tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    gone = build.PagePair("gd.deleted", "backdoor", "isolate", "Fixing instances")
    kept = build.PagePair("gd.findings", "backdoor", "isolate", "Fixing instances")
    build.BuildFiles(out).write(build.BuildFiles.PAIRS, [gone, kept])

    args = build.EntityGraphBuild.parse_args(["--rescore-only", "--out", str(out)])
    assert build.EntityGraphBuild(args, chat_model=None, embed=_no_match).run() == 0

    assert _inserted(kb.writes[0]) == {(FINDINGS, FIX)}
    assert "1 written, 1 skipped" in capsys.readouterr().out


def test_rescore_only_needs_no_model(kb, tmp_path, monkeypatch):
    assert _run(tmp_path, ScriptedChat()) == 0
    args = build.EntityGraphBuild.parse_args(["--rescore-only", "--out", str(tmp_path / "out")])

    assert build.EntityGraphBuild(args, chat_model=None, embed=_no_match).run() == 0


def test_the_shipped_policy_loads():
    policy = EntityGraphPolicy.load(settings.entity_graph_policy_version)

    assert policy.strip_links is True
    assert policy.limits.max_pairs_per_section > 0


def test_a_sampled_page_can_point_to_a_page_outside_the_sample(kb, tmp_path, monkeypatch):
    """The spike extracts a sample, but a pointer's target can be any KB
    page: resolving against the sample alone drops real pointers as
    unresolved."""

    monkeypatch.setattr(
        build.KbSnapshot,
        "sample",
        lambda self, size, include: build.KbSnapshot(self.articles[:1]),
    )

    assert _run(tmp_path, ScriptedChat(), "--sample", "1") == 0

    edges = _lines(tmp_path / "out" / build.BuildFiles.GRAPH)
    assert [(r["source_slug"], r["target_slug"]) for r in edges] == [("gd.findings", "gd.fix")]


class OnceBroken(ScriptedChat):
    """Replies with malformed JSON, as DeepSeek did for one section at
    temperature 0, every time it was asked."""

    async def ainvoke(self, messages, **kw):
        self.sections.append(str(messages[-1].content))
        return SimpleNamespace(content='{"pairs": [{bad json')


def test_an_unusable_reply_is_asked_once_more_of_the_retry_model(kb, tmp_path):
    """Temperature 0 replays the same broken reply on every run, so the
    section could never be built; the retry model's reply is used."""

    args = build.EntityGraphBuild.parse_args(
        ["--working-dir", str(tmp_path / "w"), "--out", str(tmp_path / "out")]
    )
    retry = ScriptedChat()

    assert (
        build.EntityGraphBuild(
            args, chat_model=OnceBroken(), retry_model=retry, embed=_no_match
        ).run()
        == 0
    )
    assert len(retry.sections) == 3


def test_a_second_unusable_reply_still_fails_the_section(kb, tmp_path):
    args = build.EntityGraphBuild.parse_args(
        ["--working-dir", str(tmp_path / "w"), "--out", str(tmp_path / "out")]
    )

    assert (
        build.EntityGraphBuild(
            args, chat_model=OnceBroken(), retry_model=OnceBroken(), embed=_no_match
        ).run()
        == 1
    )
    assert not (tmp_path / "out" / build.BuildFiles.GRAPH).exists()


def test_the_same_pair_both_here_and_on_another_page_exports(kb, tmp_path):
    """A page can give a remedy and also name another page for it; the two
    pairs differ only in where. Sorting them must not compare None with a
    name (the full build's export crashed on it)."""

    class BothPlaces(ScriptedChat):
        async def ainvoke(self, messages, **kw):
            pairs = [
                {"symptom": "s", "remedy": "r", "remedy_location": "this_page"},
                {"symptom": "s", "remedy": "r", "remedy_location": {"page": "Fixing instances"}},
            ]
            return SimpleNamespace(content=json.dumps({"pairs": pairs}))

    assert _run(tmp_path, BothPlaces()) == 0


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


def _ranked(monkeypatch, cap):
    monkeypatch.setattr(settings, "association_per_article_cap", cap)
    policy = EntityGraphPolicy.load(settings.entity_graph_policy_version)
    scorer = build.EdgeScorer(policy=policy, embed=_one_hot)
    rows, _ = scorer.score(RANKED_PAIRS, build.KbSnapshot(RANKED))
    return rows


def test_targets_rank_by_pairs_then_exact_before_embedding_then_slug(monkeypatch):
    rows = _ranked(monkeypatch, cap=10)

    assert [(r.target_slug, r.score) for r in rows] == [
        ("b.two", 2.0),
        ("c.one", 1.0),
        ("d.one", 1.0),
        ("a.emb", 1.0),
    ]


def test_the_cap_keeps_the_top_ranked_targets(monkeypatch):
    rows = _ranked(monkeypatch, cap=3)

    assert [r.target_slug for r in rows] == ["b.two", "c.one", "d.one"]


def test_the_build_id_names_the_policy_and_the_pairs(monkeypatch):
    rows = _ranked(monkeypatch, cap=10)

    assert re.fullmatch(
        rf"entity_graph:{re.escape(settings.entity_graph_policy_version)}"
        r":pairs-[0-9a-f]{12}:\d{4}-\d{2}-\d{2}",
        rows[0].build_id,
    )
