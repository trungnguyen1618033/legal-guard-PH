"""Adapter obligations (nghĩa vụ & hạn chót, giai đoạn SAU KÝ) → implement ObligationRepositoryPort.

Dùng chung Base/engine với cases. Cô lập org_id; `within_days` lọc due_date <= hôm-nay+N. Cascade
delete_by_case (right-to-erasure, như outcomes). In-memory variant cho stub/test (không cần DB).
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from legalguard.adapters.outbound.sql_case_repository import Base, get_engine
from legalguard.domain.models import Obligation


class ObligationRow(Base):
    __tablename__ = "obligations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String, index=True, default="default")
    case_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String, default="other")
    description: Mapped[str] = mapped_column(String, default="")
    due_date: Mapped[str] = mapped_column(String, index=True, default="")
    rule: Mapped[str] = mapped_column(String, default="")
    party: Mapped[str] = mapped_column(String, default="")
    consequence: Mapped[str] = mapped_column(String, default="")
    source_clause: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[str] = mapped_column(String, default="")


def _to_model(r: ObligationRow) -> Obligation:
    return Obligation(id=r.id, org_id=r.org_id, case_id=r.case_id, kind=r.kind, description=r.description,
                      due_date=r.due_date, rule=r.rule, party=r.party, consequence=r.consequence,
                      source_clause=r.source_clause, status=r.status, created_at=r.created_at)


class SqlAlchemyObligationRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = get_engine(database_url)
        Base.metadata.create_all(self.engine)

    def add_many(self, items: list[Obligation]) -> None:
        if not items:
            return
        with Session(self.engine) as s:
            for o in items:
                s.merge(ObligationRow(**vars(o)))
            s.commit()

    def list_by_org(self, org_id: str, within_days: int | None = None,
                    status: str = "pending") -> list[Obligation]:
        stmt = select(ObligationRow).where(ObligationRow.org_id == org_id)
        if status:
            stmt = stmt.where(ObligationRow.status == status)
        if within_days is not None:      # chỉ nghĩa vụ CÓ due_date trong [hôm nay, +N] (lọc nhắc)
            lim = (date.today() + timedelta(days=within_days)).isoformat()
            today = date.today().isoformat()
            stmt = stmt.where(ObligationRow.due_date != "",
                              ObligationRow.due_date >= today, ObligationRow.due_date <= lim)
        stmt = stmt.order_by(ObligationRow.due_date)
        with Session(self.engine) as s:
            return [_to_model(r) for r in s.scalars(stmt).all()]

    def set_status(self, obligation_id: str, org_id: str, status: str) -> None:
        with Session(self.engine) as s:
            row = s.get(ObligationRow, obligation_id)
            if row is not None and row.org_id == org_id:   # cô lập org
                row.status = status
                s.commit()

    def delete_by_case(self, case_id: str) -> int:
        with Session(self.engine) as s:
            rows = s.scalars(select(ObligationRow).where(ObligationRow.case_id == case_id)).all()
            for r in rows:
                s.delete(r)
            s.commit()
            return len(rows)


class InMemoryObligationRepository:
    """Bản in-memory cho stub/test (không cần DB)."""

    def __init__(self) -> None:
        self._items: list[Obligation] = []

    def add_many(self, items: list[Obligation]) -> None:
        self._items.extend(items)

    def list_by_org(self, org_id: str, within_days: int | None = None,
                    status: str = "pending") -> list[Obligation]:
        out = [o for o in self._items if o.org_id == org_id and (not status or o.status == status)]
        if within_days is not None:
            lim = (date.today() + timedelta(days=within_days)).isoformat()
            today = date.today().isoformat()
            out = [o for o in out if o.due_date and today <= o.due_date <= lim]
        return sorted(out, key=lambda o: o.due_date)

    def set_status(self, obligation_id: str, org_id: str, status: str) -> None:
        for o in self._items:
            if o.id == obligation_id and o.org_id == org_id:
                o.status = status

    def delete_by_case(self, case_id: str) -> int:
        before = len(self._items)
        self._items = [o for o in self._items if o.case_id != case_id]
        return before - len(self._items)
