"""Tầng TRÌNH BÀY dùng chung (semantic document → serialize theo kênh).

Một NGUỒN (list[Block]) → nhiều kênh: text/Zalo (`to_text`), Slack mrkdwn (`md_to_slack` + block builder
ở adapter), web/markdown (`to_markdown`). Giải VĨNH VIỄN lớp lỗi trình bày (markdown `**`↔`*`, giãn dòng,
lặp footer) — sửa 1 chỗ, mọi kênh đúng. Thuần (không phụ thuộc adapter/framework) → test offline, tái dùng.

`Block` = 1 khối ngữ nghĩa (đoạn/mục/ghi chú). `action` = metadata nút (chỉ kênh có nút như Slack dùng);
`context` = khối phụ (vd công bố AI — kênh Slack render kiểu 'context', text render thường).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)          # **đậm** (markdown chuẩn)
_MD_HEADER_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*$", re.MULTILINE)   # # Tiêu đề


@dataclass
class Block:
    """Một khối trình bày. `text` là nội dung (có thể nhiều dòng). `context=True` → khối phụ (công bố).
    `action` (tùy chọn) → nút trên kênh hỗ trợ (Slack accessory): {label, action_id, value}."""
    text: str
    context: bool = False
    action: dict | None = None
    key: str = ""                 # định danh khối (vd 'lg_amend_1') — kênh có block_id dùng

    def clean(self) -> str:
        return (self.text or "").strip()


Doc = list      # Doc = list[Block] (alias cho dễ đọc)


def md_to_slack(text: str) -> str:
    """Markdown chuẩn (GitHub) → Slack mrkdwn: `**đậm**`→`*đậm*`, tiêu đề `#…`→`*…*`. Slack dùng MỘT dấu `*`
    cho đậm; `**` KHÔNG render (hiện thô). Thuần — dùng cho MỌI text mrkdwn gửi Slack."""
    if not text:
        return text
    t = _MD_BOLD_RE.sub(r"*\1*", text)          # làm TRƯỚC (tránh tạo *** khi tiêu đề chứa đậm)
    return _MD_HEADER_RE.sub(r"*\1*", t)


def to_text(doc: Doc, *, sep: str = "\n\n") -> str:
    """Serialize Doc → text thuần (Zalo/email/fallback). Bỏ khối rỗng; ngăn cách bằng dòng trống."""
    return sep.join(b.clean() for b in doc if b.clean())


def to_markdown(doc: Doc, *, sep: str = "\n\n") -> str:
    """Serialize Doc → markdown chuẩn (web). Hiện giữ nguyên text (nội dung đã là markdown/plain)."""
    return sep.join(b.clean() for b in doc if b.clean())
