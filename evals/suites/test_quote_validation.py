"""
Quote-validation precision — spec §12.2 (`test_quote_validation`,
threshold: precision >= 0.95 at catching hallucinated/misattributed/
mis-negated quotes). Fully offline: exercises ai_engine's validator
directly against hand-crafted (quote, source, should_pass) triples,
including the negation-flip case that's the whole reason §6.4 exists.
"""

from contracts.llm_draft import AutoReplyProposal, LLMProposalEnvelope

from ai_engine.graph.nodes.rerank import RankedChunk
from ai_engine.graph.nodes.validate import ValidateNode

# The production-configured validator — zero I/O at construction, so the
# eval measures exactly what the graph runs.
_NODE = ValidateNode()

PRECISION_THRESHOLD = 0.95

# (quote, source_chunks, should_be_flagged_as_hallucination)
# "flagged as hallucination" = quote_source_in_topk is False OR
# negation_consistent is False — i.e. the validator correctly refuses to
# trust this quote.
CASES: list[tuple[str, list[str], bool]] = [
    # Genuinely correct quotes — must NOT be flagged.
    (
        "Kiểm tra phím Caps Lock có đang bật không.",
        ["Kiểm tra phím Caps Lock có đang bật không. Sau đó thử lại."],
        False,
    ),
    (
        "Khởi động lại dịch vụ Print Spooler.",
        ["Bước 5: Khởi động lại dịch vụ Print Spooler."],
        False,
    ),
    (
        "Bạn không được cấp quyền nếu chưa hoàn thành đào tạo.",
        ["Bạn không được cấp quyền nếu chưa hoàn thành đào tạo."],
        False,
    ),
    # Fabricated quote not present in any source — must be flagged.
    (
        "Hệ thống sẽ tự động gia hạn giấy phép của bạn trong 24 giờ.",
        ["Kiểm tra phím Caps Lock có đang bật không."],
        True,
    ),
    # Quote pulled from the wrong article entirely (verbatim, but not in
    # the retrieved top-k at all) — must be flagged.
    (
        "Liên hệ phòng Nhân sự để biết thêm chi tiết về nghỉ phép.",
        ["Kiểm tra phím Caps Lock có đang bật không.", "Khởi động lại máy in."],
        True,
    ),
    # Negation flip — the highest-value case (spec §6.4). Quote drops the
    # negation present in the source it's drawn from.
    (
        "được cấp quyền truy cập hệ thống kế toán",
        ["Nhân viên không được cấp quyền truy cập hệ thống kế toán nếu chưa được duyệt."],
        True,
    ),
    (
        "được phép cài đặt phần mềm ngoài danh sách",
        ["Nhân viên không được phép cài đặt phần mềm ngoài danh sách đã duyệt."],
        True,
    ),
    # Whitespace-only drift — a real match, must NOT be flagged.
    (
        "Đặt lại mật khẩu tại portal.company.local",
        ["Bạn có thể   Đặt lại mật khẩu tại   portal.company.local   để tiếp tục."],
        False,
    ),
]


def _is_flagged(quote: str, sources: list[str]) -> bool:
    reranked = [
        RankedChunk(chunk_id=i, article_id=1, article_slug="KB-TEST", content=content, score=0.9)
        for i, content in enumerate(sources)
    ]
    proposal = LLMProposalEnvelope(
        root=AutoReplyProposal(
            proposed_intent="auto_reply",
            kb_slug="KB-TEST",
            verbatim_quote=quote,
            answer_draft="x",
            self_confidence=90,
        )
    )
    result = _NODE({"proposal": proposal, "reranked": reranked, "iteration": 0})["validation"]
    return not result["quote_source_in_topk"] or not result["negation_consistent"]


def test_quote_validation_precision_meets_threshold():
    hallucination_cases = [c for c in CASES if c[2]]
    correct_catches = sum(
        1 for quote, sources, _ in hallucination_cases if _is_flagged(quote, sources)
    )
    precision = correct_catches / len(hallucination_cases)

    assert precision >= PRECISION_THRESHOLD, (
        f"hallucination-catch precision {precision:.2%} < {PRECISION_THRESHOLD:.0%} "
        f"({correct_catches}/{len(hallucination_cases)})"
    )


def test_valid_quotes_are_not_false_flagged():
    valid_cases = [c for c in CASES if not c[2]]
    false_positives = [(q, s) for q, s, _ in valid_cases if _is_flagged(q, s)]
    assert not false_positives, f"valid quotes incorrectly flagged: {false_positives}"
