"""So sánh 2 phiên bản văn bản → redline (đã thêm / đã bỏ). Thuần Python (difflib), tất định.

Dùng cho tính năng "what changed": dán điều luật bản cũ + bản mới → thấy đổi gì ở mức từ.
Không phải tư vấn — chỉ hiển thị khác biệt cơ học để người đọc tự đối chiếu.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher


def _tokens(text: str) -> list[str]:
    # Giữ khoảng trắng làm token để ghép lại nguyên dạng; tách theo ranh giới từ.
    return re.findall(r"\s+|\S+", text or "")


def redline(old: str, new: str) -> str:
    """Trả chuỗi redline: phần THÊM bọc [+...+], phần BỎ bọc [-...-], phần giữ nguyên để trần."""
    a, b = _tokens(old), _tokens(new)
    out: list[str] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            out.append("".join(a[i1:i2]))
        elif tag == "delete":
            out.append(f"[-{''.join(a[i1:i2])}-]")
        elif tag == "insert":
            out.append(f"[+{''.join(b[j1:j2])}+]")
        else:  # replace
            out.append(f"[-{''.join(a[i1:i2])}-][+{''.join(b[j1:j2])}+]")
    return "".join(out).strip()


def change_ratio(old: str, new: str) -> float:
    """Tỉ lệ giống nhau 0..1 (1 = y hệt). Dùng để báo mức độ thay đổi."""
    return round(SequenceMatcher(None, _tokens(old), _tokens(new), autojunk=False).ratio(), 3)
