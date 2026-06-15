"""Domain models — DTO thuần, không phụ thuộc framework/hạ tầng.

Đây là phần "bên trong hexagon": chỉ dữ liệu + ý nghĩa nghiệp vụ.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # tránh import vòng; chỉ dùng cho type hint
    from legalguard.domain.ports import KnowledgeBasePort


# ---- LLM DTO ----
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatTurn:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


# ---- Knowledge base ----
@dataclass
class Snippet:
    source: str
    text: str
    score: float


# ---- Nghiệp vụ rà soát hợp đồng ----
@dataclass
class SourceMeta:
    """Dấu vân tay văn bản đã phân tích — audit trail KHÔNG cần giữ nội dung file.

    Khách đưa lại file → hash khớp → chứng minh "đúng bản này, ngày này, kết quả này".
    """
    sha256: str = ""
    filename: str = ""       # rỗng khi input là text dán trực tiếp
    size_bytes: int = 0

    @classmethod
    def of(cls, data: bytes, filename: str = "") -> SourceMeta:
        return cls(sha256=hashlib.sha256(data).hexdigest(), filename=filename,
                   size_bytes=len(data))


@dataclass
class NegotiationPosition:
    """Vị thế đàm phán của khách — ĐẦU VÀO để fallback bám thế trận thật (BATNA/leverage)."""
    leverage: str = "balanced"      # strong | balanced | weak
    urgency: str = "low"            # low | high
    relationship: str = "new"       # new | repeat
    alternatives: bool = False      # có BATNA (đối tác/nhà cung cấp thay thế) không


@dataclass
class Risk:
    clause: str
    risk: str
    severity: str              # low | medium | high
    source: str = ""           # citation KB: nguồn/quote chính sách rủi ro
    evidence: str = ""         # trích nguyên văn ĐOẠN TRONG HỢP ĐỒNG kích hoạt rủi ro
    priority: str = ""         # must_fix | negotiate | acceptable (theo vị thế đàm phán)
    verified: bool = True       # qua verification (clause-existence + LLM-judge) chưa


@dataclass
class Fallback:
    clause: str
    suggestion: str            # chiến thuật thỏa hiệp (tiếng Việt)
    english_reply: str = ""    # câu mẫu gửi đối tác (tiếng Anh) — sẵn dùng
    source: str = ""           # citation: chunk KB grounding cho fallback này
    win_rate: float | None = None   # tỉ lệ thắng lịch sử (outcome flywheel) nếu có


@dataclass
class Conversation:
    """Phiên chat: working memory (history) + deal context (long-term của phiên)."""
    id: str
    history: list[dict] = field(default_factory=list)   # [{role, content}]
    context: str = ""                                   # tóm tắt deal đang bàn
    updated_at: str = ""

    def add(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})

    def recent(self, n: int = 8) -> list[dict]:
        return self.history[-n:]

    def trim(self, keep: int = 20) -> None:
        self.history = self.history[-keep:]


@dataclass
class Outcome:
    """Kết quả đàm phán thực tế — DỮ LIỆU ĐỘC QUYỀN (moat flywheel)."""
    id: str
    org_id: str
    case_id: str
    clause: str
    tactic: str
    result: str                # accepted | partial | rejected | pending
    created_at: str


@dataclass
class TraceStep:
    step: int
    tool: str
    arguments: dict
    observation: str


@dataclass
class AgentRun:
    final_message: str
    trace: list[TraceStep] = field(default_factory=list)
    iterations: int = 0
    truncated: bool = False    # input vượt giới hạn ký tự, phần đuôi KHÔNG được phân tích


@dataclass
class AgentContext:
    """Trạng thái agent thu thập trong một lượt rà soát."""
    retriever: KnowledgeBasePort
    risks: list[Risk] = field(default_factory=list)
    fallbacks: list[Fallback] = field(default_factory=list)
    needs_human_review: bool = False
    review_reasons: list[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    tenant: str
    risks: list[dict]
    fallbacks: list[dict]
    needs_human_review: bool
    review_reasons: list[str]
    summary: str
    trace: list[dict]
    strategy: str = ""           # chiến lược đàm phán tổng thể (ưu tiên + BATNA/walk-away)
    notes: list[str] = field(default_factory=list)
    case_id: str = ""            # id bản ghi đã lưu (nếu có persistence)


@dataclass
class AnalysisCase:
    """Một lần rà soát được lưu — lịch sử khách + audit/evidence AI-Native (XPRIZE)."""
    id: str
    org_id: str                  # CÔNG TY sở hữu — cô lập dữ liệu theo trường này
    tenant: str                  # quốc gia (jurisdiction)
    created_at: str              # ISO UTC
    lang: str
    contract_excerpt: str        # chỉ trích đoạn — KHÔNG lưu toàn bộ nội dung nhạy cảm
    summary: str
    needs_human_review: bool
    risks: list[dict]
    fallbacks: list[dict]
    trace: list[dict]
    # Audit trail (SourceMeta): vân tay văn bản gốc — không lưu nội dung.
    source_sha256: str = ""
    source_name: str = ""
    source_bytes: int = 0
    text_chars: int = 0          # độ dài text đã phân tích (sau parse, trước redact)


# ---- Evidence doanh thu (cho XPRIZE) ----
@dataclass
class RevenueEntry:
    customer: str
    date: str            # ISO 'YYYY-MM-DD'
    amount_usd: float
    contract_ref: str = ""
    testimonial: str = ""
    related_party: bool = False   # XPRIZE yêu cầu khai riêng related-party
