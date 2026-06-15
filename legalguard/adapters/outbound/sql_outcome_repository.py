"""Adapter outcomes (kết quả đàm phán) → implement OutcomeRepositoryPort.

Dùng chung Base/engine kiểu với cases. win_rates() là tín hiệu cho outcome-aware ranking
+ là moat dữ liệu độc quyền (càng nhiều kết quả thật, gợi ý càng chuẩn).
"""
from __future__ import annotations

from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from legalguard.adapters.outbound.sql_case_repository import Base, get_engine
from legalguard.domain.models import Outcome

_WEIGHT = {"accepted": 1.0, "partial": 0.5, "rejected": 0.0}   # pending bị loại khỏi thống kê


class OutcomeRow(Base):
    __tablename__ = "outcomes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String, index=True, default="default")
    case_id: Mapped[str] = mapped_column(String, index=True)
    clause: Mapped[str] = mapped_column(String, index=True)
    tactic: Mapped[str] = mapped_column(String, default="")
    result: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[str] = mapped_column(String)


class SqlAlchemyOutcomeRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = get_engine(database_url)
        Base.metadata.create_all(self.engine)

    def record(self, outcome: Outcome) -> str:
        with Session(self.engine) as s:
            s.merge(OutcomeRow(**vars(outcome)))
            s.commit()
        return outcome.id

    def win_rates(self, org_id: str | None = None) -> dict[str, dict]:
        stmt = select(OutcomeRow)
        if org_id:
            stmt = stmt.where(OutcomeRow.org_id == org_id)
        agg: dict[str, list[float]] = {}
        with Session(self.engine) as s:
            for row in s.scalars(stmt).all():
                if row.result in _WEIGHT:                       # bỏ qua pending
                    agg.setdefault(row.clause, []).append(_WEIGHT[row.result])
        return {
            clause: {"accepted": round(sum(w), 2), "total": len(w),
                     "rate": round(sum(w) / len(w), 2)}
            for clause, w in agg.items()
        }
