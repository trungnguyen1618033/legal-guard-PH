"""Tầng TRÌNH BÀY dùng chung (semantic document → serialize theo kênh).

Một NGUỒN (list[Block]) → nhiều kênh: text/Zalo (`to_text`), Slack mrkdwn (`md_to_slack` + block builder
ở adapter). Giải VĨNH VIỄN lớp lỗi trình bày (markdown `**`↔`*`, giãn dòng, lặp footer) — sửa 1 chỗ, mọi
kênh đúng. Thuần (không phụ thuộc adapter/framework) → test offline, tái dùng.

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


Doc = list[Block]      # alias cho dễ đọc


def md_to_slack(text: str) -> str:
    """Markdown chuẩn (GitHub) → Slack mrkdwn: `**đậm**`→`*đậm*`, tiêu đề `#…`→`*…*`. Slack dùng MỘT dấu `*`
    cho đậm; `**` KHÔNG render (hiện thô). Thuần — dùng cho MỌI text mrkdwn gửi Slack."""
    if not text:
        return text
    t = _MD_BOLD_RE.sub(r"*\1*", text)          # làm TRƯỚC (tránh tạo *** khi tiêu đề chứa đậm)
    return _MD_HEADER_RE.sub(r"*\1*", t)


def strip_md(text: str) -> str:
    """Bỏ dấu markdown ĐẬM (`**x**`→`x`) + tiêu đề (`#…`→`…`) cho kênh KHÔNG render markdown (Zalo/text
    thuần) — tránh lộ dấu `**` thô. Thuần; giữ nguyên nội dung, chỉ gỡ dấu định dạng."""
    if not text:
        return text
    t = _MD_BOLD_RE.sub(r"\1", text)
    return _MD_HEADER_RE.sub(r"\1", t)


def to_text(doc: Doc, *, sep: str = "\n\n") -> str:
    """Serialize Doc → text thuần (Zalo/email/fallback). Bỏ khối rỗng; ngăn cách bằng dòng trống."""
    return sep.join(b.clean() for b in doc if b.clean())


# ---- Biến thể GIỌNG/ĐỊNH DẠNG (D) — bọc nội dung tư vấn theo văn phong khác nhau ----
_EMAIL_OPEN = "Kính gửi Quý Công ty,"
_EMAIL_CLOSE = ("Kính đề nghị Quý Công ty xem xét điều chỉnh các nội dung nêu trên và phản hồi để các bên "
                "tiếp tục hoàn thiện trước khi ký kết.\n\nTrân trọng.")


def to_email_wrap(body: str) -> str:
    """Bọc nội dung tư vấn ĐÃ SOẠN thành THƯ trang trọng (giữ NGUYÊN substance — deterministic, không LLM).
    Dùng cho biến thể 'bản email'."""
    return f"{_EMAIL_OPEN}\n\n{(body or '').strip()}\n\n{_EMAIL_CLOSE}"


# ---- Structured lookup (B) — PARSE text tra cứu → cấu trúc để render giàu (link điều luật, badge tin cậy) ----
_CONF_PREFIX = ("độ tin cậy:", "confidence:")
# Nhãn = ĐẦU DÒNG + (tùy chọn `**`) + tên + DẤU HAI CHẤM (bắt buộc) + (tùy chọn `**`). Colon bắt buộc +
# neo đầu dòng → KHÔNG khớp "căn cứ" giữa câu (vd 'Chưa đủ căn cứ trong…').
_BASIS_SPLIT = re.compile(r"^\s*\*{0,2}\s*(?:Căn cứ|Basis)\s*:\s*\*{0,2}\s*", re.IGNORECASE | re.MULTILINE)
_ANS_PREFIX = re.compile(r"^\s*\*{0,2}\s*(?:Trả lời|Answer)\s*:\s*\*{0,2}\s*", re.IGNORECASE)


def parse_lookup(text: str) -> dict:
    """Tách text tra cứu ('**Trả lời:** … **Căn cứ:** … + dòng Độ tin cậy') → {answer, citations[],
    confidence}. THUẦN, không LLM, khoan dung (không khớp → answer = cả text). KHÔNG đổi generation ⇒
    accuracy KHÔNG đổi; chỉ để RENDER giàu hơn (web link điều luật / badge). confidence: high|medium|low."""
    t = (text or "").strip()
    conf = "medium"
    kept: list[str] = []
    for ln in t.split("\n"):
        s = ln.strip().lstrip("*").strip().lower()
        if s.startswith(_CONF_PREFIX):
            conf = "low" if ("thấp" in s or "low" in s) else "high" if ("cao" in s or "high" in s) else "medium"
            continue                                  # bỏ dòng tin cậy khỏi thân
        kept.append(ln)
    body = "\n".join(kept).strip()
    parts = _BASIS_SPLIT.split(body, maxsplit=1)
    answer = _ANS_PREFIX.sub("", parts[0].strip()).strip()
    citations = [re.sub(r"^[-•*]\s*", "", c).strip()
                 for c in (parts[1].strip().split("\n") if len(parts) > 1 else []) if c.strip()]
    return {"answer": answer, "citations": citations, "confidence": conf}
