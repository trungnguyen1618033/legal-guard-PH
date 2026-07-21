"""Adapter bộ nhớ agent BỀN (MemoryPort) — SQL + vector; thay InMemory ở prod.

Cùng code chạy SQLite (dev/test) và Postgres (prod). Recall theo BẬC THANG semantic→lexical (như
_relevance_scores của thread context):
- có `embed_fn` + tình tiết đã embed → COSINE (semantic) trong RAM trên tập tình tiết của org (bounded);
- offline / chưa embed → OVERLAP từ khóa (lexical), y như InMemory;
- cả hai + BOOST khi cùng counterparty (moat theo-đối-tác).
Cô lập org (SQL WHERE org_id); cascade erasure theo case_id (PDPD/GDPR). Vector lưu sẵn (JSON) → nâng
pgvector ANN in-DB sau (như SqlEmbeddingStore, CockroachDB `<=>` Phase 2) mà KHÔNG phải re-embed.
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import Index, String, Text, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from legalguard.adapters.outbound.embedding_store import _cosine
from legalguard.adapters.outbound.memory_store import _terms
from legalguard.adapters.outbound.sql_case_repository import Base, get_engine
from legalguard.domain.models import MemoryEpisode

_RECALL_CAP = 500          # trần tình tiết/org nạp vào RAM để xếp hạng (bounded → recall nhanh, đủ sớm)
_CP_BOOST = 2.0            # cùng đối tác = tín hiệu mạnh, đủ để luôn nổi lên đầu


class MemoryRow(Base):
    __tablename__ = "memory_episodes"
    __table_args__ = (Index("idx_mem_org_created", "org_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String, index=True, default="default")
    counterparty: Mapped[str] = mapped_column(String, index=True, default="")
    kind: Mapped[str] = mapped_column(String, default="note")
    clause: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String, index=True, default="")
    case_id: Mapped[str] = mapped_column(String, index=True, default="")
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON list[float] | None (offline)


def _row_to_episode(r: MemoryRow) -> MemoryEpisode:
    return MemoryEpisode(id=r.id, org_id=r.org_id, counterparty=r.counterparty, kind=r.kind,
                         clause=r.clause, content=r.content, created_at=r.created_at, case_id=r.case_id)


class SqlMemory:
    """MemoryPort bền. `embed_fn(list[str])->list[vector]|None` (từ reasoner.embed); None → chỉ lexical."""

    def __init__(self, database_url: str, embed_fn=None) -> None:  # noqa: ANN001
        self.engine = get_engine(database_url)
        Base.metadata.create_all(self.engine)
        self._embed_fn = embed_fn

    def _embed_one(self, text_: str) -> list[float] | None:
        if self._embed_fn is None or not (text_ or "").strip():
            return None
        try:
            out = self._embed_fn([text_])
        except Exception:  # noqa: BLE001 — embed lỗi/offline → bỏ vector, vẫn lưu (lexical dùng được)
            return None
        return out[0] if out else None

    def remember(self, episode: MemoryEpisode) -> str:
        ep = episode
        eid = ep.id or uuid.uuid4().hex
        vec = self._embed_one(f"{ep.clause} {ep.content}")
        with Session(self.engine) as s:
            s.merge(MemoryRow(id=eid, org_id=ep.org_id, counterparty=ep.counterparty, kind=ep.kind,
                              clause=ep.clause, content=ep.content, created_at=ep.created_at,
                              case_id=ep.case_id, embedding=json.dumps(vec) if vec is not None else None))
            s.commit()
        return eid

    def recall(self, org_id: str, query: str, counterparty: str = "", k: int = 5) -> list[MemoryEpisode]:
        with Session(self.engine) as s:
            rows = list(s.scalars(select(MemoryRow).where(MemoryRow.org_id == org_id)
                                   .order_by(MemoryRow.created_at.desc()).limit(_RECALL_CAP)))
        if not rows:
            return []
        cp = counterparty.strip().lower()
        qv = self._embed_one(query) if self._embed_fn is not None else None
        qterms = _terms(query)
        scored: list[tuple[float, str, MemoryRow]] = []
        for r in rows:
            same_cp = bool(cp) and (r.counterparty or "").strip().lower() == cp
            if qv is not None and r.embedding:                     # semantic
                rel = _cosine(qv, json.loads(r.embedding))
            else:                                                  # lexical fallback
                rel = float(len(qterms & _terms(f"{r.clause} {r.content}")))
            if rel <= 0 and not same_cp:                           # không liên quan → bỏ (chống nhiễu)
                continue
            scored.append((rel + (_CP_BOOST if same_cp else 0.0), r.created_at, r))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)      # điểm ↓ rồi recency ↓
        return [_row_to_episode(r) for _, _, r in scored[:max(0, k)]]

    def delete_by_case(self, case_id: str) -> int:
        if not case_id:
            return 0
        with Session(self.engine) as s:
            n = s.execute(delete(MemoryRow).where(MemoryRow.case_id == case_id)).rowcount
            s.commit()
        return int(n or 0)
