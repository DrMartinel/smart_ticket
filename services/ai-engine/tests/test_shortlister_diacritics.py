"""
Lexical reranker must fold Vietnamese diacritics — spec §6.3.

Tickets are often typed without tone marks ("khong dang nhap duoc") while KB
articles have them. Without folding, a near-verbatim match scored ~0.04
instead of ~0.75 — below `retrieval.floor` — sending such tickets to a human
as "nothing in the KB matches".
"""

from ai_engine.graph.nodes.candidate_pool.shortlister import LexicalShortlister

KB_TEXT = (
    "Không đăng nhập được máy tính công ty. Vui lòng đặt lại mật khẩu "
    "tại cổng self-service nếu mật khẩu đã hết hạn."
)


def _score(query: str) -> float:
    [score] = LexicalShortlister().score(query, [KB_TEXT])
    return score


def test_tokenize_folds_vietnamese_marks_including_d_stroke():
    """NFD doesn't decompose `đ`/`Đ`: they need their own replacement."""
    assert LexicalShortlister._tokenize("Đăng đi") == {"dang", "di"}


def test_unaccented_query_matches_accented_kb():
    unaccented = "Khong dang nhap duoc may tinh"
    accented = "Không đăng nhập được máy tính"
    assert _score(unaccented) == _score(accented)


def test_unaccented_query_scores_well_above_floor():
    """The regression this exists to prevent: 0.04 vs a 0.45 floor."""
    score = _score("Khong dang nhap duoc may tinh")
    assert score > 0.45, f"unaccented Vietnamese scored {score:.3f}, below the retrieval floor"


def test_tokenize_is_case_and_accent_insensitive():
    assert LexicalShortlister._tokenize("Đăng Nhập") == LexicalShortlister._tokenize("dang nhap")


def test_unrelated_text_still_scores_low():
    """Folding accents must not make everything match everything."""
    assert _score("May in bi ket giay") < 0.45
