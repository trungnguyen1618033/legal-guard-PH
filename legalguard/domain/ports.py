"""Ports — interface mà domain ĐỊNH NGHĨA và phụ thuộc vào.

Adapters (hạ tầng) ở ngoài hexagon sẽ implement các port này. Domain không bao
giờ import adapter; chiều phụ thuộc luôn hướng vào trong (Dependency Inversion).
"""
from __future__ import annotations

import abc
from typing import Protocol, runtime_checkable

from legalguard.domain.models import (
    AnalysisCase,
    ChatTurn,
    Conversation,
    Feedback,
    Outcome,
    RevenueEntry,
    Snippet,
)
from legalguard.domain.tenants import Organization


class LLMError(RuntimeError):
    """Lỗi gọi provider đã làm sạch (KHÔNG chứa URL/API key)."""

    def __init__(self, provider: str, detail: str) -> None:
        self.provider = provider
        super().__init__(f"{provider}: {detail}")


class LLMPort(abc.ABC):
    """Cổng tới một LLM provider (driven/secondary port)."""

    name: str = "llm"

    @property
    @abc.abstractmethod
    def available(self) -> bool: ...

    @abc.abstractmethod
    def complete(self, prompt: str, *, system: str | None = None) -> str: ...

    def chat(self, messages: list[dict], *, tools: list[dict] | None = None) -> ChatTurn:
        raise NotImplementedError(f"{self.name} chưa hỗ trợ tool-calling")

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        return None


@runtime_checkable
class KnowledgeBasePort(Protocol):
    """Truy xuất knowledge base của một tenant."""

    def retrieve(self, query: str, top_k: int = 4) -> list[Snippet]: ...


@runtime_checkable
class KnowledgeBaseProvider(Protocol):
    """Tạo KnowledgeBasePort cho một công ty: KB quốc gia + overlay riêng của công ty."""

    def for_org(self, org: Organization) -> KnowledgeBasePort: ...

    def changelog(self, doc_id: str, country: str) -> dict | None: ...   # "what changed" cấp văn bản


@runtime_checkable
class DocumentParserPort(Protocol):
    """Bóc tách text từ file hợp đồng."""

    def extract_text(self, data: bytes, filename: str) -> str: ...


@runtime_checkable
class OcrPort(Protocol):
    """OCR cho HĐ scan/ảnh (text-PDF thường không cần). available=False → bỏ qua."""

    @property
    def available(self) -> bool: ...

    def ocr(self, data: bytes, filename: str) -> str: ...


@runtime_checkable
class ChatSenderPort(Protocol):
    """Gửi trả lời + tải file đính kèm trên nền tảng chat (Zalo/Slack)."""

    @property
    def available(self) -> bool: ...

    def send(self, conversation_id: str, text: str, thread_ts: str | None = None,
             blocks: list | None = None) -> None: ...

    def download(self, url: str) -> bytes: ...


@runtime_checkable
class ConversationStorePort(Protocol):
    """Lưu phiên chat (history + deal context). MVP in-memory; prod Redis/SQL."""

    def get(self, key: str) -> Conversation | None: ...

    def save(self, conversation: Conversation) -> None: ...


@runtime_checkable
class ObservabilityPort(Protocol):
    """Ghi telemetry (trace/event) — evidence AI-Native (XPRIZE) + debug. NoOp nếu tắt."""

    def event(self, name: str, data: dict) -> None: ...


@runtime_checkable
class RevenueLogPort(Protocol):
    """Lưu & đọc bản ghi doanh thu (evidence XPRIZE)."""

    def record(self, entry: RevenueEntry) -> None: ...

    def all(self) -> list[RevenueEntry]: ...


@runtime_checkable
class CaseRepositoryPort(Protocol):
    """Lưu & đọc các lần rà soát (cases). Adapter mặc định: SQLite; sau: Postgres."""

    def save(self, case: AnalysisCase) -> str: ...

    def get(self, case_id: str) -> AnalysisCase | None: ...

    def list_by_org(self, org_id: str, limit: int = 20) -> list[AnalysisCase]: ...

    def delete(self, case_id: str) -> bool: ...   # right-to-erasure (PDPD/GDPR)


@runtime_checkable
class OutcomeRepositoryPort(Protocol):
    """Lưu & thống kê kết quả đàm phán — flywheel dữ liệu độc quyền."""

    def record(self, outcome: Outcome) -> str: ...

    # {clause: {"accepted": float, "total": int, "rate": float}}
    def win_rates(self, org_id: str | None = None) -> dict[str, dict]: ...


@runtime_checkable
class FeedbackRepositoryPort(Protocol):
    """Lưu phản hồi người dùng về câu trả lời — vòng học (gom golden set, tìm lỗ hổng)."""

    def record(self, feedback: Feedback) -> str: ...

    def list_by_org(self, org_id: str, limit: int = 100) -> list[Feedback]: ...
