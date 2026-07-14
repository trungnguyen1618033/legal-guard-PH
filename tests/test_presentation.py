"""Tầng trình bày dùng chung — thuần, offline."""
from legalguard.domain.presentation import (
    Block,
    md_to_slack,
    parse_lookup,
    to_text,
)


def test_md_to_slack_bold_and_headers():
    assert md_to_slack("**Trả lời:** x") == "*Trả lời:* x"
    assert md_to_slack("## Căn cứ\nĐiều 5") == "*Căn cứ*\nĐiều 5"
    assert "**" not in md_to_slack("**A** và **B**")
    assert md_to_slack("*đã đúng*") == "*đã đúng*"        # single * giữ nguyên
    assert md_to_slack("") == "" and md_to_slack("thường") == "thường"


def test_to_text_joins_nonempty_with_blank_line():
    doc = [Block("Mở đầu"), Block("  "), Block("(1) Điều 5"), Block("Kết")]
    assert to_text(doc) == "Mở đầu\n\n(1) Điều 5\n\nKết"     # bỏ khối rỗng, ngăn dòng trống


def test_block_clean_strips():
    assert Block("  x \n").clean() == "x"
    assert Block("", context=True).clean() == ""


def test_parse_lookup_structured():
    txt = ("**Trả lời:** Mức phạt tối đa 8%.\n"
           "**Căn cứ:**\n- Điều 301 LTM 2005 — trần 8%\n- Điều 300 LTM — điều kiện phạt\n\n"
           "Độ tin cậy: Cao — nguồn dẫn hậu thuẫn.")
    p = parse_lookup(txt)
    assert p["answer"] == "Mức phạt tối đa 8%."
    assert p["citations"] == ["Điều 301 LTM 2005 — trần 8%", "Điều 300 LTM — điều kiện phạt"]
    assert p["confidence"] == "high"


def test_parse_lookup_english_and_low():
    txt = "**Answer:** X.\n**Basis:** Article 301.\n\nConfidence: Low — verify with a lawyer."
    p = parse_lookup(txt)
    assert p["answer"] == "X." and p["citations"] == ["Article 301."] and p["confidence"] == "low"


def test_parse_lookup_tolerant_no_structure():
    # Không có template → answer = cả text, không vỡ.
    p = parse_lookup("Chưa đủ căn cứ trong cơ sở tri thức để trả lời.")
    assert "Chưa đủ căn cứ" in p["answer"] and p["citations"] == [] and p["confidence"] == "medium"
