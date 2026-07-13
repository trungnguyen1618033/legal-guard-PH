"""Tầng trình bày dùng chung — thuần, offline."""
from legalguard.domain.presentation import Block, md_to_slack, to_markdown, to_text


def test_md_to_slack_bold_and_headers():
    assert md_to_slack("**Trả lời:** x") == "*Trả lời:* x"
    assert md_to_slack("## Căn cứ\nĐiều 5") == "*Căn cứ*\nĐiều 5"
    assert "**" not in md_to_slack("**A** và **B**")
    assert md_to_slack("*đã đúng*") == "*đã đúng*"        # single * giữ nguyên
    assert md_to_slack("") == "" and md_to_slack("thường") == "thường"


def test_to_text_joins_nonempty_with_blank_line():
    doc = [Block("Mở đầu"), Block("  "), Block("(1) Điều 5"), Block("Kết")]
    assert to_text(doc) == "Mở đầu\n\n(1) Điều 5\n\nKết"     # bỏ khối rỗng, ngăn dòng trống


def test_to_markdown_keeps_content():
    doc = [Block("**đậm**"), Block("thường")]
    assert to_markdown(doc) == "**đậm**\n\nthường"          # web giữ markdown gốc


def test_block_clean_strips():
    assert Block("  x \n").clean() == "x"
    assert Block("", context=True).clean() == ""
