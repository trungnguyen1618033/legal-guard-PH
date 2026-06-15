import pytest

from legalguard.adapters.outbound.document_parser import PdfDocxParser
from legalguard.domain.tenants import get_tenant


def test_get_tenant_vn():
    t = get_tenant("vn")  # không phân biệt hoa thường
    assert t.id == "VN"
    assert t.arbitration_body == "VIAC"


def test_get_tenant_unknown_raises():
    with pytest.raises(ValueError):
        get_tenant("XX")


def test_extract_text_txt():
    assert PdfDocxParser().extract_text("Nội dung hợp đồng".encode(), "hd.txt") == "Nội dung hợp đồng"


def test_extract_text_unsupported_raises():
    with pytest.raises(ValueError):
        PdfDocxParser().extract_text(b"...", "hd.rtf")
