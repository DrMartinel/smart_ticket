"""
Validator tests — spec §6.4. The negation check gets the most coverage: fuzzy
matching alone scores "được cấp quyền" vs "không được cấp quyền" at ~0.96
despite opposite meanings.
"""

from uuid import UUID

import pytest

from ai_engine.schemas import AutoReplyProposal, LLMProposalEnvelope, RouteProposal, TicketCategory
from ai_engine.graph.state import RankedChunk

from ai_engine.graph.nodes.validate import validate


def chunk(chunk_id: int, content: str) -> RankedChunk:
    return RankedChunk(
        chunk_id=UUID(int=chunk_id),
        article_id=UUID(int=1),
        article_slug="ec2.TroubleshootingInstancesConnecting",
        content=content,
        shortlist_score=0.9,
    )


def auto_reply(quote: str, kb_slug="ec2.TroubleshootingInstancesConnecting") -> LLMProposalEnvelope:
    return LLMProposalEnvelope(
        root=AutoReplyProposal(
            proposed_intent="auto_reply",
            kb_slug=kb_slug,
            verbatim_quote=quote,
            answer_draft="x",
            self_confidence=90,
        )
    )


def test_no_proposal_is_schema_invalid(make_state):
    state = make_state(proposal=None, reranked=[])
    out = validate(state)
    assert out["schema_valid"] is False


def test_route_proposal_skips_quote_check(make_state):
    proposal = LLMProposalEnvelope(
        root=RouteProposal(
            proposed_intent="route_to_team",
            proposed_category=TicketCategory.NETWORK,
            rationale="r",
            self_confidence=90,
        )
    )
    state = make_state(proposal=proposal, reranked=[chunk(1, "some content")])
    out = validate(state)
    assert out["schema_valid"] is True
    assert out["quote_applicable"] is False


def test_exact_substring_match(make_state):
    source = "Kiểm tra phím Caps Lock có đang bật không. Sau đó khởi động lại máy."
    quote = "Kiểm tra phím Caps Lock có đang bật không."
    state = make_state(proposal=auto_reply(quote), reranked=[chunk(1, source)])
    out = validate(state)
    assert out["quote_match_ratio"] == 1.0
    assert out["quote_source_in_topk"] is True


def test_quote_not_found_anywhere_fails_source_check(make_state):
    state = make_state(
        proposal=auto_reply("Câu này hoàn toàn không có trong bất kỳ nguồn nào cả."),
        reranked=[chunk(1, "Nội dung hoàn toàn khác không liên quan.")],
    )
    out = validate(state)
    assert out["quote_source_in_topk"] is False


def test_quote_found_verbatim_in_a_later_chunk_is_in_topk(make_state):
    # Quote is verbatim-correct text, but only chunk 2 has it — if the
    # LLM claims a different source, quote_source_in_topk still needs to
    # find SOME chunk containing it. This confirms the search covers all
    # of `reranked`, not just the first entry.
    state = make_state(
        proposal=auto_reply("Liên hệ IT Helpdesk để được hỗ trợ thêm."),
        reranked=[
            chunk(1, "Nội dung không liên quan."),
            chunk(2, "Nếu vẫn lỗi, Liên hệ IT Helpdesk để được hỗ trợ thêm."),
        ],
    )
    out = validate(state)
    assert out["quote_source_in_topk"] is True


def test_negation_mismatch_detected(make_state):
    # Quote omits "không" while a hypothetical mis-negated draft would
    # invert it — simulate by having the quote's negation set differ from
    # the source's.
    source = "Nhân viên không được cấp quyền truy cập hệ thống kế toán."
    quote = "được cấp quyền truy cập hệ thống kế toán."
    state = make_state(proposal=auto_reply(quote), reranked=[chunk(1, source)])
    out = validate(state)
    # quote is a substring of source? "được cấp quyền..." IS a substring
    # of "...không được cấp quyền..." so quote_source_in_topk is True,
    # but the negation sets differ (source has "không", quote doesn't).
    assert out["quote_source_in_topk"] is True
    assert out["negation_consistent"] is False


def test_negation_consistent_when_sets_match(make_state):
    source = "Bạn không được cấp quyền truy cập nếu chưa hoàn thành đào tạo."
    quote = "Bạn không được cấp quyền truy cập nếu chưa hoàn thành đào tạo."
    state = make_state(proposal=auto_reply(quote), reranked=[chunk(1, source)])
    out = validate(state)
    assert out["negation_consistent"] is True


def test_fuzzy_match_catches_whitespace_drift(make_state):
    source = "Khởi động lại   máy   tính  của bạn."
    quote = "Khởi động lại máy tính của bạn."  # normalized whitespace differs
    state = make_state(proposal=auto_reply(quote), reranked=[chunk(1, source)])
    out = validate(state)
    assert out["quote_source_in_topk"] is True
    assert out["quote_match_ratio"] >= 0.95


# ── English (the demo KB is English AWS documentation) ──


def test_english_negation_dropped_from_the_quote_is_detected(make_state):
    """The §6.4 case in English: the quote is a verbatim substring, but the
    "Do not" that governs it was left out, reversing the instruction."""
    source = "Do not delete the root user access keys. Rotate them instead."
    quote = "delete the root user access keys."
    state = make_state(proposal=auto_reply(quote), reranked=[chunk(1, source)])
    out = validate(state)
    assert out["quote_source_in_topk"] is True
    assert out["negation_consistent"] is False


def test_english_contraction_dropped_from_the_quote_is_detected(make_state):
    """Contractions are matched as their own form ("can't"), so a quote that
    drops "You can't" is caught even though "not" never appears."""
    source = "You can't attach an Elastic IP address to a stopped instance in a VPC."
    quote = "attach an Elastic IP address to a stopped instance in a VPC."
    state = make_state(proposal=auto_reply(quote), reranked=[chunk(1, source)])
    assert validate(state)["negation_consistent"] is False


def test_a_negation_in_another_sentence_of_the_chunk_does_not_flag_the_quote(make_state):
    """Chunks run to ~250 words and almost always contain a "not" somewhere.
    Comparing against the whole chunk would send every English auto-reply
    to review as NEGATION_MISMATCH."""
    source = (
        "Open the Amazon EC2 console.\n"
        "+ Choose Instances, then select the instance.\n"
        "+ If the instance is not running, start it first.\n"
        "Choose Connect."
    )
    quote = "Choose Instances, then select the instance."
    state = make_state(proposal=auto_reply(quote), reranked=[chunk(1, source)])
    assert validate(state)["negation_consistent"] is True


def test_a_quote_ending_in_a_period_does_not_absorb_the_next_sentence(make_state):
    """The search for the sentence end starts at the quote's last character,
    so the period that ends the quote ends its sentence. Starting one past it
    would run on into "Do not open port 22…" and flag a clean quote."""
    source = "Check the security group rules. Do not open port 22 to 0.0.0.0/0."
    quote = "Check the security group rules."
    state = make_state(proposal=auto_reply(quote), reranked=[chunk(1, source)])
    assert validate(state)["negation_consistent"] is True


def test_words_containing_not_or_no_are_not_negations(make_state):
    """English is matched on word boundaries. As substrings, "notification"
    and "node" would each count as a negation, and the extra count would
    flag any quote that happens to share a sentence with them."""
    source = "Configure an SNS notification for the node group. Then save."
    quote = "Configure an SNS notification for the node group."
    state = make_state(proposal=auto_reply(quote), reranked=[chunk(1, source)])
    assert validate(state)["negation_consistent"] is True


def test_one_of_two_negations_dropped_from_the_quote_is_detected(make_state):
    """Both the quote and its sentence contain "not", so comparing which
    negations appear would pass. The quote dropped the "Do not" that governs
    it, so the counts differ."""
    source = "Do not disable MFA if you do not have a backup device."
    quote = "disable MFA if you do not have a backup device."
    state = make_state(proposal=auto_reply(quote), reranked=[chunk(1, source)])
    assert validate(state)["negation_consistent"] is False


def test_an_abbreviation_does_not_split_the_sentence_away_from_its_negation(make_state):
    """ "e.g. " looks like a sentence end. Splitting there would compare the
    quote with the text after "e.g." alone, which has no "not"."""
    source = "Do not use root credentials, e.g. the root user access keys, for daily tasks."
    quote = "the root user access keys, for daily tasks."
    state = make_state(proposal=auto_reply(quote), reranked=[chunk(1, source)])
    assert validate(state)["negation_consistent"] is False


def test_fuzzy_matched_quote_that_dropped_a_negation_is_detected(make_state):
    """A quote with punctuation drift isn't an exact substring, so its
    sentence is located by fuzzy alignment rather than by search. That path
    must still find the governing "Do not"."""
    source = "Do not delete the root user access keys, rotate them instead."
    quote = "delete the root user access keys rotate them instead."
    state = make_state(proposal=auto_reply(quote), reranked=[chunk(1, source)])
    out = validate(state)
    assert out["quote_source_in_topk"] is True
    assert out["quote_match_ratio"] < 1.0
    assert out["negation_consistent"] is False


def test_fuzzy_matched_quote_is_compared_with_its_own_sentence_only(make_state):
    """The alignment must narrow the comparison to the quote's own sentence.
    If it fell back to the whole chunk, the "not" in the first sentence would
    flag this clean quote."""
    source = "If the key is not rotated, rotate it.\nChoose Instances, then select the instance."
    quote = "Choose Instances then select the instance."
    state = make_state(proposal=auto_reply(quote), reranked=[chunk(1, source)])
    out = validate(state)
    assert out["quote_source_in_topk"] is True
    assert out["quote_match_ratio"] < 1.0
    assert out["negation_consistent"] is True


@pytest.mark.xfail(
    strict=True,
    reason="Known gap: a list item is its own sentence, so a negated lead-in line doesn't reach it",
)
def test_a_negated_list_lead_in_governs_its_items(make_state):
    """A quote from a list item is checked against that item alone, so the
    "Don't" on the lead-in line is missed and the quote passes. This is the
    cost of splitting on line breaks, which keeps the check from flagging
    every quote in a chunk. strict=True makes this fail when the gap is
    closed, so the marker can't outlive the fix."""
    source = (
        "Don't do any of the following:\n+ Delete the root user access keys.\n+ Share passwords."
    )
    quote = "Delete the root user access keys."
    state = make_state(proposal=auto_reply(quote), reranked=[chunk(1, source)])
    assert validate(state)["negation_consistent"] is False
