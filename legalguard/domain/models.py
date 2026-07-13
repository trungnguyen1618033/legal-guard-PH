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
    protected_party: str = ""       # "bên mình bảo vệ" (vd Bên Vay/Bên B/Buyer); rỗng = mặc định SME {country}


@dataclass
class Risk:
    clause: str
    risk: str
    severity: str              # low | medium | high
    source: str = ""           # citation KB: nguồn/quote chính sách rủi ro
    evidence: str = ""         # trích nguyên văn ĐOẠN TRONG HỢP ĐỒNG kích hoạt rủi ro
    priority: str = ""         # must_fix | negotiate | acceptable (theo vị thế đàm phán)
    verified: bool = True       # qua verification (clause-existence + LLM-judge) chưa
    legal_basis: str = ""      # căn cứ pháp lý gắn tất định từ KB: 'file#Điều N: <nguyên văn>'
    legal_status: str = "unfavorable"  # illegal (trái luật, có thể vô hiệu) | unfavorable (bất lợi nhưng hợp pháp)
    violated_law: str = ""     # điều luật bị vi phạm (khi legal_status=illegal), vd 'Điều 301 LTM 2005'
    counter_clause: dict = field(default_factory=dict)  # điều khoản mới dán-được-ngay {vi,en,rationale,grounded}
    # — auto sinh INLINE cho rủi ro illegal/must_fix (AUTO_COUNTER_ON_ANALYZE); rủi ro nhẹ → soạn qua nút "Đồng ý sửa"


@dataclass
class Fallback:
    clause: str
    suggestion: str            # chiến thuật thỏa hiệp (tiếng Việt)
    english_reply: str = ""    # câu mẫu gửi đối tác (tiếng Anh) — sẵn dùng
    source: str = ""           # citation: chunk KB grounding cho fallback này
    win_rate: float | None = None   # tỉ lệ thắng lịch sử (outcome flywheel) nếu có
    legal_basis: str = ""      # căn cứ pháp lý gắn tất định từ KB: 'file#Điều N: <nguyên văn>'


@dataclass
class Obligation:
    """Nghĩa vụ CÓ MỐC trích từ hợp đồng (giai đoạn SAU KÝ) — để nhắc trước khi lỡ hạn. Dữ liệu tích lũy
    riêng org (system-of-record). THUẦN dữ liệu — không phụ thuộc kênh (Slack/Zalo/web/MCP dùng chung)."""
    id: str
    org_id: str            # cô lập công ty (index)
    case_id: str           # thuộc lần rà soát nào
    kind: str              # payment | delivery | renewal | termination_notice | warranty | other
    description: str       # "Thanh toán đợt 2 40% giá trị hợp đồng"
    due_date: str = ""     # ISO 'YYYY-MM-DD' nếu ra được mốc TUYỆT ĐỐI; rỗng nếu chỉ có rule tương đối
    rule: str = ""         # mốc TƯƠNG ĐỐI chưa quy ra ngày: "30 ngày trước ngày hết hạn hợp đồng"
    party: str = ""        # bên chịu nghĩa vụ
    consequence: str = ""  # hệ quả nếu lỡ ("hợp đồng tự gia hạn 12 tháng", "phạt 0,05%/ngày")
    source_clause: str = ""# trích điều khoản gốc
    status: str = "pending"# pending | done | dismissed
    created_at: str = ""


@dataclass
class Conversation:
    """Phiên chat: working memory (history) + deal context (long-term của phiên)."""
    id: str
    history: list[dict] = field(default_factory=list)   # [{role, content}]
    context: str = ""                                   # tóm tắt deal đang bàn
    nego_state: str = ""                                # sổ nhượng-bộ đàm phán (JSON, xem negotiation.state_*)
    updated_at: str = ""

    def add(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})

    def recent(self, n: int = 8) -> list[dict]:
        return self.history[-n:]

    def trim(self, keep: int = 20) -> None:
        self.history = self.history[-keep:]


@dataclass
class Outcome:
    """Kết quả đàm phán thực tế — dữ liệu tích lũy riêng org (data flywheel)."""
    id: str
    org_id: str
    case_id: str
    clause: str
    tactic: str
    result: str                # accepted | partial | rejected | pending
    created_at: str


@dataclass
class Feedback:
    """Phản hồi người dùng về một câu trả lời — vòng học: gom golden set + tìm lỗ hổng từ usage thật."""
    id: str
    org_id: str
    kind: str                  # analysis | lookup
    ref: str                   # case_id (analysis) hoặc câu hỏi (lookup)
    rating: str                # helpful | wrong | incomplete
    note: str
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
    contract_type: str = ""      # loại hợp đồng (LLM tự xác định) — nêu ở dòng đầu reply luật sư
    protected_party: str = ""    # TÊN ĐẦY ĐỦ khách hàng được bảo vệ (LLM trích từ HĐ) — dòng đầu reply
    drafting_notes: list[str] = field(default_factory=list)  # lỗi CHÍNH TẢ/soạn thảo trong HĐ + cách sửa (cuối reply)
    notes: list[str] = field(default_factory=list)
    case_id: str = ""            # id bản ghi đã lưu (nếu có persistence)
    execution_summary: dict = field(default_factory=dict)  # đếm tool-call (evidence AI-Native, xem domain/runs.py)


@dataclass
class AnalysisCase:
    """Một lần rà soát được lưu — lịch sử khách + audit/evidence AI-Native (system-of-record)."""
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


# ---- Evidence doanh thu (system-of-record) ----
@dataclass
class RevenueEntry:
    customer: str
    date: str            # ISO 'YYYY-MM-DD'
    amount_usd: float
    contract_ref: str = ""
    testimonial: str = ""
    related_party: bool = False   # khai riêng related-party (không thổi phồng số liệu organic)
