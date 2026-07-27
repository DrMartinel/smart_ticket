"""
Validator tests — spec §6.4. The negation check is the highest-value
addition versus a naive fuzzy-match-only validator, so it gets the most
coverage here: fuzzy matching alone would score "được cấp quyền" vs
"không được cấp quyền" at ~0.96 similarity despite meaning the opposite.
"""

from contracts.llm_draft import AutoReplyProposal, LLMProposalEnvelope, RouteProposal
from contracts.enums import TicketCategory

from ai_engine.graph.nodes.rerank import RankedChunk
from ai_engine.graph.nodes.validate import validate_output


def chunk(chunk_id: int, content: str) -> RankedChunk:
    return RankedChunk(chunk_id=chunk_id, article_id=1, article_slug="KB-0001", content=content, score=0.9)


def auto_reply(quote: str, kb_slug="KB-0001") -> LLMProposalEnvelope:
    return LLMProposalEnvelope(
        root=AutoReplyProposal(
            proposed_intent="auto_reply", kb_slug=kb_slug, verbatim_quote=quote,
            answer_draft="x", self_confidence=90,
        )
    )


def test_no_proposal_is_schema_invalid_and_bumps_iteration():
    state = {"proposal": None, "reranked": [], "iteration": 0}
    out = validate_output(state)
    assert out["validation"]["schema_valid"] is False
    assert out["iteration"] == 1


def test_route_proposal_skips_quote_check():
    proposal = LLMProposalEnvelope(
        root=RouteProposal(
            proposed_intent="route_to_team", proposed_category=TicketCategory.NETWORK,
            rationale="r", self_confidence=90,
        )
    )
    state = {"proposal": proposal, "reranked": [chunk(1, "some content")], "iteration": 0}
    out = validate_output(state)
    assert out["validation"]["schema_valid"] is True
    assert out["validation"]["quote_applicable"] is False


def test_exact_substring_match():
    source = "Kiểm tra phím Caps Lock có đang bật không. Sau đó khởi động lại máy."
    quote = "Kiểm tra phím Caps Lock có đang bật không."
    state = {"proposal": auto_reply(quote), "reranked": [chunk(1, source)], "iteration": 0}
    out = validate_output(state)["validation"]
    assert out["quote_match_ratio"] == 1.0
    assert out["quote_source_in_topk"] is True
    assert out["source_chunk_id"] == 1


def test_quote_not_found_anywhere_fails_source_check():
    state = {
        "proposal": auto_reply("Câu này hoàn toàn không có trong bất kỳ nguồn nào cả."),
        "reranked": [chunk(1, "Nội dung hoàn toàn khác không liên quan.")],
        "iteration": 0,
    }
    out = validate_output(state)["validation"]
    assert out["quote_source_in_topk"] is False


def test_quote_from_wrong_chunk_not_in_topk_even_if_verbatim_elsewhere():
    # Quote is verbatim-correct text, but only chunk 2 has it — if the
    # LLM claims a different source, quote_source_in_topk still needs to
    # find SOME chunk containing it. This confirms the search covers all
    # of `reranked`, not just the first entry.
    state = {
        "proposal": auto_reply("Liên hệ IT Helpdesk để được hỗ trợ thêm."),
        "reranked": [
            chunk(1, "Nội dung không liên quan."),
            chunk(2, "Nếu vẫn lỗi, Liên hệ IT Helpdesk để được hỗ trợ thêm."),
        ],
        "iteration": 0,
    }
    out = validate_output(state)["validation"]
    assert out["quote_source_in_topk"] is True
    assert out["source_chunk_id"] == 2


def test_negation_mismatch_detected():
    # Quote omits "không" while a hypothetical mis-negated draft would
    # invert it — simulate by having the quote's negation set differ from
    # the source's.
    source = "Nhân viên không được cấp quyền truy cập hệ thống kế toán."
    quote = "được cấp quyền truy cập hệ thống kế toán."
    state = {"proposal": auto_reply(quote), "reranked": [chunk(1, source)], "iteration": 0}
    out = validate_output(state)["validation"]
    # quote is a substring of source? "được cấp quyền..." IS a substring
    # of "...không được cấp quyền..." so quote_source_in_topk is True,
    # but the negation sets differ (source has "không", quote doesn't).
    assert out["quote_source_in_topk"] is True
    assert out["negation_consistent"] is False


def test_negation_consistent_when_sets_match():
    source = "Bạn không được cấp quyền truy cập nếu chưa hoàn thành đào tạo."
    quote = "Bạn không được cấp quyền truy cập nếu chưa hoàn thành đào tạo."
    state = {"proposal": auto_reply(quote), "reranked": [chunk(1, source)], "iteration": 0}
    out = validate_output(state)["validation"]
    assert out["negation_consistent"] is True


def test_fuzzy_match_catches_whitespace_drift():
    source = "Khởi động lại   máy   tính  của bạn."
    quote = "Khởi động lại máy tính của bạn."  # normalized whitespace differs
    state = {"proposal": auto_reply(quote), "reranked": [chunk(1, source)], "iteration": 0}
    out = validate_output(state)["validation"]
    assert out["quote_source_in_topk"] is True
    assert out["quote_match_ratio"] >= 0.95
