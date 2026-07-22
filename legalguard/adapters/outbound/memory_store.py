"""Adapter bộ nhớ agent theo ĐỐI TÁC (MemoryPort) — bản InMemory offline/test.

Đây là adapter MẶC ĐỊNH/stub: giữ tình tiết trong RAM, recall bằng OVERLAP từ khóa + ưu tiên cùng
counterparty + recency (TẤT ĐỊNH, không LLM/network → test offline). Bản SQL+vector (pgvector giờ,
CockroachDB `<=>`/C-SPANN sau — thay `SqlEmbeddingStore` ở Phase 2) là increment kế; cùng MemoryPort nên
domain KHÔNG đổi. Cô lập org_id; cascade erasure theo case_id (PDPD/GDPR).

Nguyên tắc (docs/internal/agent-memory-stack-2026.md): recall = NGỮ CẢNH cố vấn inject vào prompt (như
tactics_context) → KHÔNG đổi generation → accuracy giữ; ghi gọi ASYNC ngoài hot-path.
"""
from __future__ import annotations

import re
import unicodedata
import uuid

from legalguard.domain.models import MemoryEpisode

# Stopword VN/EN tối thiểu — loại từ chức năng để overlap bám từ NỘI DUNG (điều khoản/rủi ro), không nhiễu.
_STOP = {
    "và", "hoặc", "của", "cho", "các", "những", "là", "có", "không", "được", "theo", "về", "với", "khi",
    "này", "đó", "một", "trong", "bên", "đã", "sẽ", "bị", "phải", "nếu", "thì", "mà", "ở", "để",
    "the", "a", "an", "of", "for", "to", "and", "or", "is", "are", "in", "on", "with", "this", "that",
}


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", (s or "").lower())


def _terms(s: str) -> set[str]:
    """Tách token có nghĩa (≥2 ký tự, bỏ stopword) từ text đã NFC+lower."""
    return {t for t in re.split(r"\W+", _norm(s)) if len(t) >= 2 and t not in _STOP}


class InMemoryMemory:
    """MemoryPort in-process. Không bền (mất khi restart) → chỉ cho test/offline/dev; prod dùng adapter SQL."""

    def __init__(self) -> None:
        self._episodes: list[MemoryEpisode] = []

    def remember(self, episode: MemoryEpisode) -> str:
        ep = episode
        if not ep.id:
            ep = MemoryEpisode(**{**ep.__dict__, "id": uuid.uuid4().hex})
        self._supersede(ep)                                             # bi-temporal: cũ cùng (cp,clause) → superseded
        self._episodes = [e for e in self._episodes if e.id != ep.id]   # upsert theo id (hồ sơ profile idempotent)
        self._episodes.append(ep)
        return ep.id

    def _supersede(self, new_ep: MemoryEpisode) -> None:
        """Tình tiết MỚI cùng (org, counterparty, clause) → đánh dấu tình tiết HIỆN TẠI cũ là superseded
        (valid_to + superseded_by), KHÔNG xóa. Chỉ khi cp & clause đều có + không phải profile."""
        cp, clause = _norm(new_ep.counterparty), _norm(new_ep.clause)
        if not (cp and clause) or new_ep.kind == "profile":
            return
        vt = new_ep.created_at or "superseded"
        for i, e in enumerate(self._episodes):
            if (e.org_id == new_ep.org_id and e.id != new_ep.id and not e.valid_to
                    and e.kind != "profile" and _norm(e.counterparty) == cp and _norm(e.clause) == clause):
                self._episodes[i] = MemoryEpisode(**{**e.__dict__, "valid_to": vt, "superseded_by": new_ep.id})

    def list_by_counterparty(self, org_id: str, counterparty: str, limit: int = 200,
                             include_history: bool = False) -> list[MemoryEpisode]:
        cp = _norm(counterparty)
        out = [e for e in self._episodes if e.org_id == org_id and _norm(e.counterparty) == cp
               and (include_history or not e.valid_to)]
        return out[-limit:] if limit else out

    def recall(self, org_id: str, query: str, counterparty: str = "", k: int = 5,
               include_history: bool = False) -> list[MemoryEpisode]:
        """Tình tiết liên quan nhất: cô lập org → điểm = overlap từ khóa(query, clause+content) + boost nếu
        cùng counterparty → tie-break recency. Bỏ tình tiết điểm 0 (không liên quan → không inject nhiễu).
        Mặc định CHỈ tình tiết HIỆN TẠI (valid_to rỗng); include_history=True để xem cả đã-superseded."""
        qterms = _terms(query)
        cp = _norm(counterparty)
        scored: list[tuple[float, str, MemoryEpisode]] = []
        for ep in self._episodes:
            if ep.org_id != org_id:                     # cô lập org TUYỆT ĐỐI
                continue
            if ep.valid_to and not include_history:     # đã superseded → bỏ (chỉ trả vị thế HIỆN TẠI)
                continue
            overlap = len(qterms & _terms(f"{ep.clause} {ep.content}"))
            same_cp = bool(cp) and _norm(ep.counterparty) == cp
            if overlap == 0 and not same_cp:            # không liên quan gì → bỏ (chống inject nhiễu)
                continue
            score = overlap + (2.0 if same_cp else 0.0)  # cùng đối tác = tín hiệu mạnh (moat theo-đối-tác)
            scored.append((score, ep.created_at, ep))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)   # điểm ↓ rồi recency ↓
        return [ep for _, _, ep in scored[:max(0, k)]]

    def delete_by_case(self, case_id: str) -> int:
        """Cascade right-to-erasure: xóa mọi tình tiết thuộc case bị xóa. Trả số đã xóa."""
        if not case_id:
            return 0
        before = len(self._episodes)
        self._episodes = [ep for ep in self._episodes if ep.case_id != case_id]
        return before - len(self._episodes)
