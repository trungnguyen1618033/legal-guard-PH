"""Adapter outcomes (kết quả đàm phán) → implement OutcomeRepositoryPort.

Dùng chung Base/engine kiểu với cases. win_rates() là tín hiệu cho outcome-aware ranking
+ là dữ liệu tích lũy riêng theo org (càng nhiều kết quả thật, gợi ý càng chuẩn).
"""
from __future__ import annotations

from sqlalchemy import String, case, func, select
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

    def delete_by_case(self, case_id: str) -> int:
        """Cascade right-to-erasure: xóa mọi outcome của 1 case (khi xóa case). Trả số dòng đã xóa."""
        with Session(self.engine) as s:
            rows = s.scalars(select(OutcomeRow).where(OutcomeRow.case_id == case_id)).all()
            for r in rows:
                s.delete(r)
            s.commit()
            return len(rows)

    def win_rates(self, org_id: str | None = None) -> dict[str, dict]:
        """Tổng hợp win-rate theo điều khoản. Gộp bằng SQL GROUP BY (chỉ trả mỗi-clause-1-dòng) thay vì
        load mọi outcome rồi gộp Python — O(số clause) thay vì O(số outcome), nhẹ RAM khi data lớn."""
        weight = case(*[(OutcomeRow.result == r, w) for r, w in _WEIGHT.items()], else_=0.0)
        stmt = (select(OutcomeRow.clause, func.sum(weight), func.count())
                .where(OutcomeRow.result.in_(tuple(_WEIGHT)))   # bỏ qua pending
                .group_by(OutcomeRow.clause))
        if org_id:
            stmt = stmt.where(OutcomeRow.org_id == org_id)
        with Session(self.engine) as s:
            rows = s.execute(stmt).all()
        return {clause: {"accepted": round(float(acc), 2), "total": total,
                         "rate": round(float(acc) / total, 2)}
                for clause, acc, total in rows if total}
