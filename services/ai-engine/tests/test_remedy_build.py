"""
The offline `remedy_pointer` build (ADR-0018 amendment): sections in, one
model call per section, (symptom, remedy, where) pairs out, named pages
resolved to KB pages, pointer edges scored. The model, the database and the
embedder are fakes. What these pin, failure paths first: a failed section
exports nothing and is the only thing a re-run asks for; a reply outside
the policy's bounds is never partly used; a name that resolves to no page,
to several, or to the page itself makes no edge; and an embedding match
counts only above its bar, after exact matches.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from ai_engine.core.associations.remedies import build
from ai_engine.core.associations.remedies.extract import Pair, parse_reply
from ai_engine.core.associations.remedies.policy import ReplyLimits, load_remedy_policy
from ai_engine.core.associations.remedies.resolve import Page, PageIndex, normalize
from ai_engine.core.associations.remedies.sections import split_sections, strip_links
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

    assert strip_links(text) == "To fix it, see Remediating an instance. diagram"


def test_sections_keep_headings_together_and_never_exceed_the_budget():
    text = "# A\none two\n## B\nthree four\n## C\n" + " ".join(["w"] * 25)

    sections = split_sections(text, max_tokens=10, count=_words)

    assert sections[0] == "# A\none two\n\n## B\nthree four\n"
    assert all(_words(s) <= 10 for s in sections)
    assert " ".join(" ".join(sections).split()) == " ".join(text.split())


# --- replies -------------------------------------------------------------------


def test_a_reply_over_the_pair_limit_fails_rather_than_being_cut():
    """Keeping the first N pairs would drop pointers silently, with the
    section counted as done."""

    reply = {"pairs": [{"symptom": "s", "remedy": "r", "remedy_location": "this_page"}] * 4}

    with pytest.raises(ValueError, match="unusable reply"):
        parse_reply(json.dumps(reply), LIMITS)


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
        parse_reply(reply, LIMITS)


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

    assert parse_reply(json.dumps(reply), LIMITS) == [
        Pair("bounce", "verify", None),
        Pair("sandbox", "request", "Request access"),
    ]


# --- resolution ----------------------------------------------------------------


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
    assert normalize("Backdoor:EC2/C&CActivity.B\\!DNS") == normalize(
        "backdoor ec2 c cactivity b dns"
    )


# --- the build, end to end -----------------------------------------------------

FINDINGS, FIX, SANDBOX, COPY = (uuid.UUID(int=i) for i in (1, 2, 3, 4))
ROWS = [
    # (id, slug, title, body, is_active)
    (
        FINDINGS,
        "gd.findings",
        "EC2 finding types",
        "# EC2 finding types\nBackdoor found. To remediate, see [Fixing instances](fix.md).",
        True,
    ),
    (FIX, "gd.fix", "Fixing instances", "# Fixing instances\nIsolate the instance.", True),
    (SANDBOX, "ses.sandbox", "Sandbox", "# Sandbox\nSending fails. See Sandbox.", True),
    (
        COPY,
        "gd.findings-copy",
        "EC2 finding types",
        "# EC2 finding types\nBackdoor found. To remediate, see [Fixing instances](fix.md).",
        True,
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
    monkeypatch.setattr(build, "db", fake_db(lambda sql, params: list(ROWS)))


def _run(tmp_path, chat, *extra):
    args = build.parse_args(
        ["--working-dir", str(tmp_path / "w"), "--out", str(tmp_path / "out"), *extra]
    )
    return build.run(args, chat_model=chat, embed=_no_match)


def _lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_failed_section_exports_nothing_and_a_rerun_asks_only_for_it(kb, tmp_path, capsys):
    """An exported graph missing pages would look complete. The reply
    cache keeps the sections that worked, so the re-run costs one call."""

    assert _run(tmp_path, ScriptedChat(failing=("Sending fails",))) == 1
    assert "ses.sandbox" in capsys.readouterr().err
    assert not (tmp_path / "out" / build.POINTERS_FILE).exists()
    assert not (tmp_path / "out" / build.PAIRS_FILE).exists()

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
        for r in _lines(tmp_path / "out" / build.POINTERS_FILE)
    }
    assert set(edges) == {("gd.findings", "gd.fix"), ("gd.findings-copy", "gd.fix")}
    assert edges["gd.findings", "gd.fix"]["evidence"] == ["backdoor finding -> isolate"]
    assert edges["gd.findings", "gd.fix"]["build_id"].startswith(
        f"remedy_pointer:{settings.remedy_policy_version}:pairs-"
    )
    assert sum("Backdoor" in s for s in chat.sections) == 1

    resolutions = {
        (r["source_slug"], r["name"]): r for r in _lines(tmp_path / "out" / build.RESOLUTIONS_FILE)
    }
    assert resolutions["ses.sandbox", "Sandbox"]["target_slug"] == "ses.sandbox"
    assert resolutions["ses.sandbox", "Quota increase form"]["method"] == "unresolved"


def test_rescore_only_needs_no_model(kb, tmp_path, monkeypatch):
    assert _run(tmp_path, ScriptedChat()) == 0
    args = build.parse_args(["--rescore-only", "--out", str(tmp_path / "out")])

    assert build.run(args, chat_model=None, embed=_no_match) == 0


def test_the_shipped_policy_loads():
    policy = load_remedy_policy(settings.remedy_policy_version)

    assert policy.strip_links is True
    assert policy.limits.max_pairs_per_section > 0
