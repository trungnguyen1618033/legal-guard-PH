"""Detector câu LIỆT KÊ (_ENUM_RE) cho answer prompt — chống nén sót mục (ca FDI). Thuần, offline."""
from legalguard.domain.analysis import _ENUM_RE


def test_enum_detects_list_questions():
    for q in ["Dự án FDI được hưởng những ưu đãi đầu tư nào?",
              "Các trường hợp miễn giấy phép xây dựng?", "Liệt kê hình thức xử phạt vi phạm.",
              "Hợp đồng gồm những nội dung bắt buộc nào?"]:
        assert _ENUM_RE.search(q), q


def test_enum_ignores_figure_questions():
    for q in ["Trần lãi suất cho vay theo BLDS là bao nhiêu?",
              "Mức phạt vi phạm hợp đồng thương mại tối đa?", "Điều 301 quy định gì?"]:
        assert not _ENUM_RE.search(q), q
