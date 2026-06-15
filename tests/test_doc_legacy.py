"""Word 97–2003 (.doc): bóc text qua antiword/textutil; .doc giả (docx đổi tên) vẫn đọc."""
import io
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from legalguard.adapters.outbound import document_parser as dp

VN_TEXT = "Tranh chấp giải quyết bằng trọng tài tại Bắc Kinh."


@pytest.mark.skipif(not shutil.which("textutil"),
                    reason="cần textutil (macOS) để tạo file .doc mẫu")
def test_legacy_doc_extracted():
    with tempfile.TemporaryDirectory() as d:
        txt = Path(d) / "hd.txt"
        txt.write_text(VN_TEXT, encoding="utf-8")
        doc = Path(d) / "hd.doc"
        subprocess.run(["textutil", "-convert", "doc", str(txt), "-output", str(doc)],
                       check=True, capture_output=True)
        out = dp.PdfDocxParser().extract_text(doc.read_bytes(), "hd.doc")
    assert "trọng tài" in out.lower()


def test_doc_renamed_from_docx_still_parses():
    # SME hay đổi tên file .docx thành .doc — nhận diện qua magic bytes ZIP.
    import docx

    buf = io.BytesIO()
    d = docx.Document()
    d.add_paragraph(VN_TEXT)
    d.save(buf)
    out = dp.PdfDocxParser().extract_text(buf.getvalue(), "hd.doc")
    assert "trọng tài" in out.lower()


def test_doc_clear_error_when_no_tool(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="Save As"):
        dp.PdfDocxParser().extract_text(b"\xd0\xcf\x11\xe0 fake ole", "hd.doc")


def test_doc_renamed_from_rtf_still_parses():
    # Mẫu HĐ cũ ở VN hay là RTF đổi tên thành .doc — nhận diện magic {\rtf.
    rtf = rb"{\rtf1\ansi Arbitration in Beijing. Payment T/T 60 days.}"
    out = dp.PdfDocxParser().extract_text(rtf, "hd.doc")
    assert "Arbitration in Beijing" in out
