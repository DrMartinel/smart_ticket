"""
Scoring the `entity_graph` source (ADR-0018): mentions in, article pairs
out. Pure, so the whole Stage 3-5 path of the plan's worked example runs
here with no model. A scoring bug doesn't fail loudly: it changes which
pages link expansion pulls in, and only the eval would show it.
"""

from __future__ import annotations

import math

import pytest

from ai_engine.core.associations.policy import load_entity_policy
from ai_engine.core.associations.scoring import (
    EntityPolicy,
    Mention,
    apply_policy,
    df_histogram,
    score_associations,
)
from ai_engine.core.config import settings

A, B, C = "ses.verify-addresses-procedure", "ses.request-production-access", "ses.smtp-credentials"
N = 3542


def _filler(prefix: str, count: int) -> list[str]:
    return [f"{prefix}-{i}" for i in range(count)]


def _worked_example() -> tuple[list[Mention], set[str]]:
    """The plan's SES miss: A and B share only "SES Sandbox" (df 6); all
    three share "Amazon SES" (df 140, a hub)."""
    others = _filler("other", N - 3)
    mentions = [Mention("Amazon SES", "service", s) for s in [A, B, C, *others[:137]]]
    mentions += [Mention("SES Sandbox", "restriction", s) for s in [A, B, *others[137:141]]]
    mentions += [Mention("Verified Identity", "setting", s) for s in [A, *others[141:149]]]
    mentions += [Mention("SMTP Credentials", "setting", s) for s in [C, *others[149:159]]]
    return mentions, {A, B, C, *others}


def _score(mentions, active, *, hub_df_max=50, per_article_cap=20):
    return score_associations(
        mentions, active, hub_df_max=hub_df_max, per_article_cap=per_article_cap, build_id="b"
    )


def test_the_worked_example_links_a_and_b_through_the_sandbox_only():
    mentions, active = _worked_example()

    rows = {(r.source_slug, r.target_slug): r for r in _score(mentions, active)}

    assert rows[A, B].score == rows[B, A].score == round(math.log(N / 6), 4) == 6.3807
    assert rows[A, B].evidence == ("SES Sandbox",)
    assert (A, C) not in rows and (B, C) not in rows


def test_an_entity_above_hub_df_max_links_nothing():
    """ "Amazon SES" is on 140 pages. Linking all of them to each other would
    flood every seed's expansion with its own guide."""
    mentions, active = _worked_example()

    rows = _score(mentions, active)

    assert not any("Amazon SES" in r.evidence for r in rows)


def test_the_per_article_cap_keeps_the_highest_scores_in_a_stable_order():
    mentions = [Mention("rare", "service", s) for s in ("a", "b")]
    mentions += [Mention("common", "service", s) for s in ("a", "c", "d", "e")]
    active = set("abcdefghij")

    rows = [r for r in _score(mentions, active, per_article_cap=2) if r.source_slug == "a"]

    assert [r.target_slug for r in rows] == ["b", "c"]  # rare first; c before d on the slug
    assert rows == [r for r in _score(mentions, active, per_article_cap=2) if r.source_slug == "a"]


def test_inactive_articles_count_in_no_df_but_keep_their_rows():
    """The read hides inactive targets, so a reactivated page comes back
    without a rebuild. But df must describe the KB a ticket can reach."""
    mentions = [Mention("x", "service", s) for s in ("a", "b", "retired")]
    active = {"a", "b", "c", "d"}

    rows = {(r.source_slug, r.target_slug): r.score for r in _score(mentions, active)}

    assert rows["a", "retired"] == rows["a", "b"] == round(math.log(4 / 2), 4)
    assert ("retired", "a") in rows


def test_an_entity_only_inactive_articles_mention_links_nothing():
    mentions = [Mention("gone", "service", s) for s in ("old1", "old2")]

    assert _score(mentions, {"a"}) == []


def test_apply_policy_keeps_allowed_types_folds_aliases_and_drops_the_stoplist():
    policy = EntityPolicy(
        allowed_types=frozenset({"service", "restriction"}),
        aliases={"amazon ses sandbox": "SES Sandbox"},
        stoplist=frozenset({"aws"}),
    )
    mentions = [
        Mention("Amazon SES Sandbox", "Restriction", "a"),
        Mention("SES Sandbox", "restriction", "b"),
        Mention("AWS", "service", "a"),
        Mention("Jane Doe", "person", "a"),
    ]

    assert apply_policy(mentions, policy) == [
        Mention("SES Sandbox", "Restriction", "a"),
        Mention("SES Sandbox", "restriction", "b"),
    ]


def test_names_that_differ_only_in_case_are_one_entity():
    """Split apart, "AWS accounts" on one page and "AWS Accounts" on another
    each look like a rarer entity, and the two pages are not linked."""
    policy = EntityPolicy(allowed_types=frozenset({"service"}), aliases={}, stoplist=frozenset())
    mentions = [Mention("AWS accounts", "service", "a"), Mention("AWS Accounts", "service", "b")]

    folded = apply_policy(mentions, policy)

    assert {m.entity for m in folded} == {"AWS Accounts"}  # the spelling that sorts first
    assert {(r.source_slug, r.target_slug) for r in _score(folded, {"a", "b", "c"})} == {
        ("a", "b"),
        ("b", "a"),
    }


def test_cosine_lets_the_answering_page_outrank_a_catalogue_page():
    """The 2026-10-08 probe: GuardDuty catalogue pages listing dozens of
    finding types shared many entities with each other (scores 95-199), and
    the remediation page, sharing a few, ranked 8th (24). Summed IDF rewards
    sharing many entities; cosine rewards sharing a large part of both."""
    findings = [f"Finding:{i}" for i in range(12)]
    mentions = [Mention(f, "symptom", "seed") for f in findings + ["Malware"]]
    mentions += [
        Mention(f, "symptom", "catalogue") for f in findings + [f"Other:{i}" for i in range(300)]
    ]
    mentions += [Mention("Malware", "symptom", "remediation")]
    active = {"seed", "catalogue", "remediation"} | {f"filler{i}" for i in range(50)}

    def order(method):
        rows = score_associations(
            mentions, active, hub_df_max=50, per_article_cap=5, build_id="b", method=method
        )
        return [r.target_slug for r in rows if r.source_slug == "seed"]

    assert order("idf_sum") == ["catalogue", "remediation"]
    assert order("idf_cosine") == ["remediation", "catalogue"]


def test_df_histogram_counts_active_articles_per_entity():
    mentions = [
        Mention("x", "service", "a"),
        Mention("x", "service", "b"),
        Mention("y", "service", "a"),
    ]

    assert df_histogram(mentions, {"a", "b"}) == {1: 1, 2: 1}


def test_the_shipped_policy_loads():
    policy = load_entity_policy(settings.entity_policy_version)

    assert policy.guidance
    assert policy.scoring.allowed_types


@pytest.mark.parametrize("version", ["../config", "kb_entities.v0"])
def test_a_bad_policy_version_fails_before_any_extraction(version):
    with pytest.raises((ValueError, FileNotFoundError)):
        load_entity_policy(version)
