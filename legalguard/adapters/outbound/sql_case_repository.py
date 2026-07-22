"""Adapter persistence cases bằng SQLAlchemy 2.0 → implement CaseRepositoryPort.

Cùng một code chạy SQLite (local/test) và PostgreSQL (prod) chỉ bằng đổi DATABASE_URL:
  - sqlite:///data/cases.db
  - postgresql+psycopg://user:pass@host:5432/legalguard
Schema versioning ở prod: Alembic (migrations/). __init__ gọi create_all() để dev/test
có bảng ngay mà không cần chạy migration.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import JSON, Boolean, Index, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

# normalize_crdb_url gộp về _crdb (nhà chung); re-export ở đây để migrations/env.py import không đổi.
from legalguard.adapters.outbound._crdb import normalize_crdb_url
from legalguard.domain.models import AnalysisCase


class Base(DeclarativeBase):
    pass


_ENGINES: dict = {}


def get_engine(database_url: str):
    """Chia sẻ 1 engine (1 connection pool) cho mỗi URL — tránh tạo nhiều pool/leak. URL CRDB tự chuẩn hóa."""
    database_url = normalize_crdb_url(database_url)
    if database_url not in _ENGINES:
        if database_url.startswith("sqlite") and ":memory:" not in database_url:
            path = database_url.split("///", 1)[-1]
            if path:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        # pre_ping + recycle: Postgres serverless (Neon) autosuspend giết connection nhàn rỗi
        # → kiểm tra trước khi dùng, chết thì tự reconnect (tránh AdminShutdown giữa request).
        _ENGINES[database_url] = create_engine(database_url, connect_args=connect_args,
                                               pool_pre_ping=True, pool_recycle=300)
    return _ENGINES[database_url]


class CaseRow(Base):
    __tablename__ = "cases"
    # Composite cho truy vấn nóng nhất: list_by_org (WHERE org_id=? ORDER BY created_at DESC).
    __table_args__ = (Index("idx_cases_org_created", "org_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String, index=True, default="default")
    tenant: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[str] = mapped_column(String, index=True)
    lang: Mapped[str] = mapped_column(String, default="en")
    contract_excerpt: Mapped[str] = mapped_column(String, default="")
    summary: Mapped[str] = mapped_column(String, default="")
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    risks: Mapped[list] = mapped_column(JSON, default=list)
    fallbacks: Mapped[list] = mapped_column(JSON, default=list)
    trace: Mapped[list] = mapped_column(JSON, default=list)
    # Audit trail: vân tay văn bản gốc (không lưu nội dung). Index để tra theo hash.
    source_sha256: Mapped[str] = mapped_column(String, index=True, default="")
    source_name: Mapped[str] = mapped_column(String, default="")
    source_bytes: Mapped[int] = mapped_column(Integer, default=0)
    text_chars: Mapped[int] = mapped_column(Integer, default=0)
    drafting_issues: Mapped[list] = mapped_column(JSON, default=list)   # lỗi soạn thảo cấu trúc → file .docx có comment
    counterparty: Mapped[str] = mapped_column(String, index=True, default="")   # trục nhớ theo-đối-tác của deal


class SqlAlchemyCaseRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = get_engine(database_url)
        Base.metadata.create_all(self.engine)

    def save(self, case: AnalysisCase) -> str:
        with Session(self.engine) as s:
            s.merge(CaseRow(**vars(case)))   # upsert theo id
            s.commit()
        return case.id

    def get(self, case_id: str) -> AnalysisCase | None:
        with Session(self.engine) as s:
            row = s.get(CaseRow, case_id)
            return _to_case(row) if row else None

    def list_by_org(self, org_id: str, limit: int = 20) -> list[AnalysisCase]:
        stmt = (select(CaseRow).where(CaseRow.org_id == org_id)
                .order_by(CaseRow.created_at.desc()).limit(limit))
        with Session(self.engine) as s:
            return [_to_case(r) for r in s.scalars(stmt).all()]

    def delete(self, case_id: str) -> bool:
        with Session(self.engine) as s:
            row = s.get(CaseRow, case_id)
            if row is None:
                return False
            s.delete(row)
            s.commit()
            return True


def _to_case(row: CaseRow) -> AnalysisCase:
    return AnalysisCase(
        id=row.id, org_id=row.org_id, tenant=row.tenant, created_at=row.created_at, lang=row.lang,
        contract_excerpt=row.contract_excerpt, summary=row.summary,
        needs_human_review=row.needs_human_review,
        risks=row.risks, fallbacks=row.fallbacks, trace=row.trace,
        source_sha256=row.source_sha256, source_name=row.source_name,
        source_bytes=row.source_bytes, text_chars=row.text_chars,
        drafting_issues=row.drafting_issues or [],
        counterparty=getattr(row, "counterparty", "") or "",
    )
