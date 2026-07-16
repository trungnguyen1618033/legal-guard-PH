"""Redaction PII — che thông tin nhạy cảm TRƯỚC khi gửi LLM / lưu / log.

Rule-based (regex) theo khuyến nghị bảo mật: KHÔNG dùng LLM để redact (không đáng tin). Giảm PII
rời VN khi gọi LLM xuyên biên giới (PDPL 91/2025 Đ.20). Che:
- Liên hệ/định danh: email, điện thoại, MST, số tài khoản (chuỗi số/số-chấm ≥9), CCCD/CMND.
- TÊN NGƯỜI sau kính ngữ/đại diện (Ông/Bà/Mr/đại diện/ký bởi…) — heuristic TẤT ĐỊNH, offline.
KHÔNG đụng từ nghiệp vụ (vd "arbitration", "T/T 60 days") nên không ảnh hưởng phát hiện rủi ro.

Nâng cấp NER đầy đủ (mọi tên/địa chỉ/tổ chức): Microsoft Presidio — opt-in `uv sync --group redaction`
(dep nặng + model tiếng Việt), cắm qua cùng hàm này. Rule-based là sàn offline zero-dep.
"""
from __future__ import annotations

import re

# Tên riêng VN (NFC): 1-4 cụm chữ hoa-đầu (có dấu). Chỉ redact khi đứng SAU marker người → tránh nuốt
# tên riêng nghiệp vụ ("Luật Thương Mại"). Over-redact (an toàn) chấp nhận được cho quyền riêng tư.
_NAME = r"(?:[A-ZÀ-Ỹ][a-zà-ỹ]+\s+){0,3}[A-ZÀ-Ỹ][a-zà-ỹ]+"
_NAME_MARKER = r"(Ông|Bà|Ngài|Mr|Mrs|Ms|đại diện(?: bởi)?|người đại diện|ký bởi|họ và tên|họ tên)"

_PATTERNS = [
    # Email: CHẶN độ dài quantifier ({1,64} local-part theo RFC, {1,255} domain) → chống O(n²)/ReDoS trên
    # chuỗi \w dài (vd file chứa 'xxxx…' rất dài): không bound → mỗi vị trí quét cả run rồi fail ở '@'.
    (re.compile(r"[\w.+-]{1,64}@[\w-]{1,255}\.[\w.-]{1,255}"), "[EMAIL]"),
    # CCCD/CMND có nhãn → che cả số (9-12 chữ số)
    (re.compile(r"(?i)\b(CCCD|CMND|căn cước|chứng minh nhân dân)\b[\s:]*\d[\d.\s]{7,}\d"), "[CCCD]"),
    # chuỗi số dài ≥9 (điện thoại, MST, tài khoản; cho phép dấu chấm/gạch/space) — không chạm số ngắn "60"
    (re.compile(r"(?<!\d)(?:\+?\d[\d\-.\s]{7,}\d)(?!\d)"), "[SỐ]"),
    # TÊN sau kính ngữ/đại diện → giữ marker, che tên
    (re.compile(rf"{_NAME_MARKER}(\.?:?\s+){_NAME}"), r"\1\2[TÊN]"),
]


def redact(text: str) -> tuple[str, int]:
    """Trả (text đã che, số lần che)."""
    count = 0
    for pattern, repl in _PATTERNS:
        text, n = pattern.subn(repl, text)
        count += n
    return text, count
