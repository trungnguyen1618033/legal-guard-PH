"""Adapter bộ nhớ agent BỀN (MemoryPort) — SQL + vector; thay InMemory ở prod.

Recall theo BẬC THANG semantic→lexical + boost cùng counterparty; cô lập org; cascade erasure theo case.

VECTOR:
- **CockroachDB** (dialect `cockroachdb`, anchor): cột `vec VECTOR(dim)` + `CREATE VECTOR INDEX` (C-SPANN)
  → ANN in-DB `ORDER BY vec <=> :q` (cosine distance; verified trên cluster thật v26.2). Scale + rẻ CPU.
- **SQLite/Postgres-thường** (dev/test): brute-force cosine trong RAM trên tập tình tiết của org (bounded).
Vector luôn lưu JSON song song (portable + fallback). Cùng MemoryPort → domain KHÔNG đổi khi đổi backend.
"""
from __future__ import annotations

import json
import re
import uuid

from sqlalchemy import Index, String, Text, delete, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from legalguard.adapters.outbound.embedding_store import _cosine
from legalguard.adapters.outbound.memory_store import _terms
from legalguard.adapters.outbound.sql_case_repository import Base, get_engine
from legalguard.domain.models import MemoryEpisode

_RECALL_CAP = 500          # trần tình tiết/org nạp RAM (đường brute-force) — bounded → nhanh, đủ sớm
_ANN_CAP = 40              # số ứng viên ANN kéo về trước khi re-rank counterparty (đường CockroachDB)
_CP_BOOST = 2.0            # cùng đối tác = tín hiệu mạnh → luôn nổi lên đầu


def normalize_memory_url(url: str) -> str:
    """URL CockroachDB → scheme `cockroachdb+psycopg://` (dialect chính thức + psycopg3; vanilla postgres
    dialect KHÔNG parse được version string CRDB). Nhận biết qua 'cockroach' trong URL. Khác → giữ nguyên."""
    if not url or "cockroach" not in url.lower():
        return url
    return re.sub(r"^(postgresql(\+\w+)?|cockroachdb(\+\w+)?)://", "cockroachdb+psycopg://", url, count=1)


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


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
    """MemoryPort bền. `embed_fn(list[str])->list[vector]|None` (từ reasoner.embed); None → chỉ lexical.
    Tự phát hiện CockroachDB → dùng ANN `<=>` in-DB; ngược lại brute-force RAM (hành vi cũ, test offline)."""

    def __init__(self, database_url: str, embed_fn=None) -> None:  # noqa: ANN001
        self.engine = get_engine(normalize_memory_url(database_url))
        # Chỉ tạo BẢNG memory (không create_all mọi bảng — tránh dựng cả schema lên CRDB).
        MemoryRow.__table__.create(bind=self.engine, checkfirst=True)
        self._embed_fn = embed_fn
        self._crdb = self.engine.dialect.name == "cockroachdb"
        self._vec_dim: int | None = None
        if self._crdb:                                    # cột vec đã tồn tại (restart) → bật ANN NGAY
            try:
                with self.engine.connect() as c:
                    for row in c.execute(text("SHOW COLUMNS FROM memory_episodes")):
                        if row[0] == "vec":
                            m = re.search(r"VECTOR\((\d+)\)", str(row[1]), re.I)
                            if m:
                                self._vec_dim = int(m.group(1))
            except Exception:  # noqa: BLE001 — không dò được → _ensure_vec_column sẽ lo khi remember
                pass

    def _embed_one(self, text_: str) -> list[float] | None:
        if self._embed_fn is None or not (text_ or "").strip():
            return None
        try:
            out = self._embed_fn([text_])
        except Exception:  # noqa: BLE001 — embed lỗi/offline → bỏ vector, vẫn lưu (lexical dùng được)
            return None
        return out[0] if out else None

    def _ensure_vec_column(self, dim: int) -> None:
        """CRDB: thêm cột `vec VECTOR(dim)` + CREATE VECTOR INDEX (C-SPANN) — một lần, khi biết dim."""
        if self._vec_dim is not None:
            return
        with self.engine.begin() as c:
            c.execute(text(f"ALTER TABLE memory_episodes ADD COLUMN IF NOT EXISTS vec VECTOR({dim})"))
            try:
                c.execute(text("CREATE VECTOR INDEX IF NOT EXISTS idx_mem_vec ON memory_episodes (vec)"))
            except Exception:  # noqa: BLE001 — index đã có / phiên bản khác cú pháp → ANN vẫn chạy không index
                pass
        self._vec_dim = dim

    def remember(self, episode: MemoryEpisode) -> str:
        ep = episode
        eid = ep.id or uuid.uuid4().hex
        vec = self._embed_one(f"{ep.clause} {ep.content}")
        with Session(self.engine) as s:
            s.merge(MemoryRow(id=eid, org_id=ep.org_id, counterparty=ep.counterparty, kind=ep.kind,
                              clause=ep.clause, content=ep.content, created_at=ep.created_at,
                              case_id=ep.case_id, embedding=json.dumps(vec) if vec is not None else None))
            s.commit()
        if self._crdb and vec is not None:                         # ghi thêm cột vec cho ANN in-DB
            self._ensure_vec_column(len(vec))
            with self.engine.begin() as c:
                c.execute(text("UPDATE memory_episodes SET vec = :v WHERE id = :id"),
                          {"v": _vec_literal(vec), "id": eid})
        return eid

    def _candidates_ann(self, org_id: str, qv: list[float]) -> list[tuple[MemoryEpisode, float]]:
        """CockroachDB ANN in-DB: top ứng viên gần `qv` (cosine) trong org. rel = 1 - cosine_distance."""
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT id, org_id, counterparty, kind, clause, content, created_at, case_id, "
                "(vec <=> :q) AS dist FROM memory_episodes "
                "WHERE org_id = :org AND vec IS NOT NULL ORDER BY vec <=> :q LIMIT :cap"),
                {"q": _vec_literal(qv), "org": org_id, "cap": _ANN_CAP}).all()
        out = []
        for r in rows:
            ep = MemoryEpisode(id=r[0], org_id=r[1], counterparty=r[2], kind=r[3], clause=r[4],
                               content=r[5], created_at=r[6], case_id=r[7])
            out.append((ep, 1.0 - float(r[8])))
        return out

    def _candidates_scan(self, org_id: str, qv: list[float] | None,
                         qterms: set[str]) -> list[tuple[MemoryEpisode, float]]:
        """Brute-force RAM (sqlite/postgres-thường): nạp tình tiết org → rel = cosine(nếu có vector+qv) hoặc
        overlap từ khóa (lexical)."""
        with Session(self.engine) as s:
            rows = list(s.scalars(select(MemoryRow).where(MemoryRow.org_id == org_id)
                                   .order_by(MemoryRow.created_at.desc()).limit(_RECALL_CAP)))
        out = []
        for r in rows:
            if qv is not None and r.embedding:
                rel = _cosine(qv, json.loads(r.embedding))
            else:
                rel = float(len(qterms & _terms(f"{r.clause} {r.content}")))
            out.append((_row_to_episode(r), rel))
        return out

    def recall(self, org_id: str, query: str, counterparty: str = "", k: int = 5) -> list[MemoryEpisode]:
        qv = self._embed_one(query) if self._embed_fn is not None else None
        if self._crdb and qv is not None and self._vec_dim is not None:
            cands = self._candidates_ann(org_id, qv)               # CockroachDB ANN
        else:
            cands = self._candidates_scan(org_id, qv, _terms(query))  # brute-force/lexical
        cp = counterparty.strip().lower()
        scored: list[tuple[float, str, MemoryEpisode]] = []
        for ep, rel in cands:
            same_cp = bool(cp) and (ep.counterparty or "").strip().lower() == cp
            if rel <= 0 and not same_cp:                           # không liên quan → bỏ (chống nhiễu)
                continue
            scored.append((rel + (_CP_BOOST if same_cp else 0.0), ep.created_at, ep))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)      # điểm ↓ rồi recency ↓
        return [ep for _, _, ep in scored[:max(0, k)]]

    def delete_by_case(self, case_id: str) -> int:
        if not case_id:
            return 0
        with Session(self.engine) as s:
            n = s.execute(delete(MemoryRow).where(MemoryRow.case_id == case_id)).rowcount
            s.commit()
        return int(n or 0)
