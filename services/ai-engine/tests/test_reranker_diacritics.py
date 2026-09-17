"""
Lexical reranker must fold Vietnamese diacritics — spec §6.3.

Tickets are often typed without tone marks ("khong dang nhap duoc") while KB
articles have them. Without folding, a near-verbatim match scored ~0.04
instead of ~0.75 — below `retrieval.floor` — sending such tickets to a human
as "nothing in the KB matches".
"""

from ai_engine.core.providers.reranker import LexicalReranker

KB_TEXT = (
    "Không đăng nhập được máy tính công ty. Vui lòng đặt lại mật khẩu "
    "tại cổng self-service nếu mật khẩu đã hết hạn."
)


def test_strip_diacritics_folds_vietnamese_marks():
    assert LexicalReranker._strip_diacritics("Đăng") == "Dang"


def test_unaccented_query_matches_accented_kb():
    unaccented = "Khong dang nhap duoc may tinh"
    accented = "Không đăng nhập được máy tính"
    assert LexicalReranker._lexical_score(unaccented, KB_TEXT) == LexicalReranker._lexical_score(
        accented, KB_TEXT
    )


def test_unaccented_query_scores_well_above_floor():
    """The regression this exists to prevent: 0.04 vs a 0.45 floor."""
    score = LexicalReranker._lexical_score("Khong dang nhap duoc may tinh", KB_TEXT)
    assert score > 0.45, f"unaccented Vietnamese scored {score:.3f}, below the retrieval floor"


def test_tokenize_is_case_and_accent_insensitive():
    assert LexicalReranker._tokenize("Đăng Nhập") == LexicalReranker._tokenize("dang nhap")


def test_unrelated_text_still_scores_low():
    """Folding accents must not make everything match everything."""
    assert LexicalReranker._lexical_score("May in bi ket giay", KB_TEXT) < 0.45
