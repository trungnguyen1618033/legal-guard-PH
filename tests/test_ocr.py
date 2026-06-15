import pytest

from legalguard.adapters.outbound.document_parser import OcrFallbackParser, PdfDocxParser


class _FakeOcr:
    def __init__(self, available=True, text="OCR_TEXT"):
        self._a = available
        self._t = text

    @property
    def available(self):
        return self._a

    def ocr(self, data, filename):
        return self._t


def test_text_file_uses_base_not_ocr():
    p = OcrFallbackParser(PdfDocxParser(), _FakeOcr(text="SHOULD_NOT_USE"))
    assert p.extract_text("Hợp đồng số 1".encode(), "hd.txt") == "Hợp đồng số 1"


def test_image_routes_to_ocr():
    p = OcrFallbackParser(PdfDocxParser(), _FakeOcr(text="VĂN BẢN OCR"))
    assert p.extract_text(b"\x89PNG\r\n", "scan.png") == "VĂN BẢN OCR"


def test_image_without_ocr_raises_clear_error():
    p = OcrFallbackParser(PdfDocxParser(), _FakeOcr(available=False))
    with pytest.raises(ValueError, match="OCR"):
        p.extract_text(b"\x89PNG", "scan.jpg")


def test_unsupported_format_keeps_base_error():
    p = OcrFallbackParser(PdfDocxParser(), _FakeOcr())
    with pytest.raises(ValueError, match="hỗ trợ"):
        p.extract_text(b"...", "hd.rtf")
