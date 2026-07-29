"""
Lexical reranker must fold Vietnamese diacritics — spec §6.3.

Vietnamese support tickets are very often typed without tone marks
("khong dang nhap duoc may tinh") while KB articles are written with them
("không đăng nhập được máy tính"). Under exact token matching those are
disjoint vocabularies, so a ticket that restates a KB title almost
verbatim scored ~0.04 rather than ~0.75 — below `retrieval.floor`, which
tripped refuse-before-LLM and pushed every such ticket to a human with
"nothing in the KB matches". The retrieval was fine; the tokenizer wasn't.
"""

from ai_engine.providers.reranker import _lexical_score, _strip_diacritics, _tokenize

KB_TEXT = (
    "Không đăng nhập được máy tính công ty. Vui lòng đặt lại mật khẩu "
    "tại cổng self-service nếu mật khẩu đã hết hạn."
)


def test_strip_diacritics_folds_vietnamese_marks():
    assert _strip_diacritics("không đăng nhập được") == "khong dang nhap duoc"


def test_strip_diacritics_handles_d_stroke():
    """đ/Đ are distinct letters, not a decomposable base + combining mark,
    so NFD alone leaves them untouched."""
    assert _strip_diacritics("Đăng") == "Dang"


def test_unaccented_query_matches_accented_kb():
    unaccented = "Khong dang nhap duoc may tinh"
    accented = "Không đăng nhập được máy tính"
    assert _lexical_score(unaccented, KB_TEXT) == _lexical_score(accented, KB_TEXT)


def test_unaccented_query_scores_well_above_floor():
    """The regression this exists to prevent: 0.04 vs a 0.45 floor."""
    score = _lexical_score("Khong dang nhap duoc may tinh", KB_TEXT)
    assert score > 0.45, f"unaccented Vietnamese scored {score:.3f}, below the retrieval floor"


def test_tokenize_is_case_and_accent_insensitive():
    assert _tokenize("Đăng Nhập") == _tokenize("dang nhap")


def test_unrelated_text_still_scores_low():
    """Folding accents must not make everything match everything."""
    assert _lexical_score("May in bi ket giay", KB_TEXT) < 0.45
