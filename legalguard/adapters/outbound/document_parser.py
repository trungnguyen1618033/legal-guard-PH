"""Adapter bóc tách file hợp đồng → implement DocumentParserPort.

Ở production, tác vụ nặng này nên đẩy qua async worker (legal-guard.md §5b.2 điểm 4).
"""
from __future__ import annotations

import io

from legalguard.domain.ports import DocumentParserPort, OcrPort

_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".tiff")


class PdfDocxParser:
    def extract_text(self, data: bytes, filename: str) -> str:
        name = filename.lower()
        if name.endswith(".pdf"):
            return _from_pdf(data)
        if name.endswith(".docx"):
            return _from_docx(data)
        if name.endswith(".txt"):
            return data.decode("utf-8", errors="ignore")
        if name.endswith(".doc"):    # Word 97–2003: SME VN gửi rất nhiều
            if data[:4] == b"PK\x03\x04":   # nhiều file ".doc" thực chất là .docx đổi tên
                return _from_docx(data)
            if data[:5] == b"{\\rtf":       # ... hoặc RTF đổi tên (mẫu HĐ cũ rất hay gặp)
                from striprtf.striprtf import rtf_to_text
                return rtf_to_text(data.decode("utf-8", errors="ignore")).strip()
            return _from_doc(data)
        raise ValueError(f"Định dạng chưa hỗ trợ: {filename} "
                         "(nhận .pdf / .docx / .doc / .txt / ảnh scan .png .jpg)")


def _from_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages).strip()


def _from_docx(data: bytes) -> str:
    import docx

    doc = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs).strip()


def _from_doc(data: bytes) -> str:
    """Word 97–2003 (.doc, OLE nhị phân): không có lib Python thuần đọc tốt →
    dùng tool hệ thống: antiword (Linux/Docker, ~1MB) hoặc textutil (có sẵn macOS)."""
    import shutil
    import subprocess
    import tempfile

    tools = [["antiword", "-m", "UTF-8.txt"], ["textutil", "-convert", "txt", "-stdout"]]
    with tempfile.NamedTemporaryFile(suffix=".doc") as f:
        f.write(data)
        f.flush()
        for cmd in tools:                    # thử lần lượt; tool fail → thử tool kế
            if not shutil.which(cmd[0]):
                continue
            try:
                out = subprocess.run([*cmd, f.name], capture_output=True, timeout=60)
            except (subprocess.TimeoutExpired, OSError):
                continue
            if out.returncode == 0 and out.stdout.strip():
                # utf-8-sig: nuốt BOM ﻿ mà textutil hay chèn đầu output
                return out.stdout.decode("utf-8-sig", errors="ignore").strip()
    raise ValueError("Không đọc được file Word bản cũ (.doc) này. Mở bằng Word → "
                     "Save As → chọn .docx hoặc PDF rồi gửi lại giúp em nhé.")


class OcrFallbackParser:
    """Decorator: text-PDF/DOCX/TXT dùng base; nếu rỗng (scan) hoặc là ảnh → OCR.

    OCR không sẵn sàng → lỗi rõ ràng (không "im lặng nuốt" file scan).
    """

    def __init__(self, base: DocumentParserPort, ocr: OcrPort) -> None:
        self.base = base
        self.ocr = ocr

    def extract_text(self, data: bytes, filename: str) -> str:
        name = filename.lower()
        is_image = name.endswith(_IMAGE_EXT)
        text = ""
        if not is_image:
            try:
                text = self.base.extract_text(data, filename)
            except ValueError:
                if not name.endswith(".pdf"):   # .rtf… → giữ lỗi "định dạng chưa hỗ trợ"
                    raise
        if text.strip():
            return text
        if is_image or name.endswith(".pdf"):   # scan/ảnh → OCR
            if not self.ocr.available:
                raise ValueError("File scan/ảnh cần OCR — cấu hình QWEN_API_KEY (Qwen-VL) "
                                 "hoặc gửi bản .txt / PDF có text.")
            return self.ocr.ocr(data, filename)
        return text
