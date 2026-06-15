"""Redaction PII — che thông tin nhạy cảm TRƯỚC khi gửi LLM / lưu / log.

Rule-based (regex) theo khuyến nghị bảo mật: KHÔNG dùng LLM để redact (không đáng tin).
Chỉ che PII liên hệ/định danh (email, điện thoại, mã số dài) — KHÔNG đụng từ nghiệp vụ
(vd "arbitration", "T/T 60 days") nên không ảnh hưởng phát hiện rủi ro.
Nâng cấp sau: Microsoft Presidio / LLM Guard cho NER + tên riêng + entity pháp lý.
"""
from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    # chuỗi số dài ≥9 (điện thoại, MST, số tài khoản) — không chạm số ngắn như "60"
    (re.compile(r"(?<!\d)(?:\+?\d[\d\-\s]{7,}\d)(?!\d)"), "[SỐ]"),
]


def redact(text: str) -> tuple[str, int]:
    """Trả (text đã che, số lần che)."""
    count = 0
    for pattern, repl in _PATTERNS:
        text, n = pattern.subn(repl, text)
        count += n
    return text, count
