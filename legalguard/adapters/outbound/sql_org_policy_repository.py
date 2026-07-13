"""Adapter playbook công ty (OrgPolicy) → implement OrgPolicyRepositoryPort.

Dùng chung Base/engine với cases. Cô lập org_id. In-memory variant cho stub/test.
"""
from __future__ import annotations

from sqlalchemy import Boolean, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from legalguard.adapters.outbound.sql_case_repository import Base, get_engine
from legalguard.domain.models import OrgPolicy


class OrgPolicyRow(Base):
    __tablename__ = "org_policies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String, index=True, default="default")
    rule_text: Mapped[str] = mapped_column(String, default="")
    kind: Mapped[str] = mapped_column(String, default="mandatory")
    severity: Mapped[str] = mapped_column(String, default="must_fix")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


def _to_model(r: OrgPolicyRow) -> OrgPolicy:
    return OrgPolicy(id=r.id, org_id=r.org_id, rule_text=r.rule_text, kind=r.kind,
                     severity=r.severity, active=r.active)


class SqlAlchemyOrgPolicyRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = get_engine(database_url)
        Base.metadata.create_all(self.engine)

    def list_by_org(self, org_id: str, active_only: bool = True) -> list[OrgPolicy]:
        stmt = select(OrgPolicyRow).where(OrgPolicyRow.org_id == org_id)
        if active_only:
            stmt = stmt.where(OrgPolicyRow.active.is_(True))
        with Session(self.engine) as s:
            return [_to_model(r) for r in s.scalars(stmt).all()]

    def upsert(self, policy: OrgPolicy) -> str:
        with Session(self.engine) as s:
            existing = s.get(OrgPolicyRow, policy.id)
            if existing is not None and existing.org_id != policy.org_id:
                return existing.id          # KHÔNG ghi đè policy của org khác (cô lập org)
            s.merge(OrgPolicyRow(**vars(policy)))
            s.commit()
        return policy.id

    def delete(self, policy_id: str, org_id: str) -> bool:
        with Session(self.engine) as s:
            row = s.get(OrgPolicyRow, policy_id)
            if row is None or row.org_id != org_id:   # cô lập org
                return False
            s.delete(row)
            s.commit()
            return True


class InMemoryOrgPolicyRepository:
    """Bản in-memory cho stub/test."""

    def __init__(self) -> None:
        self._items: dict[str, OrgPolicy] = {}

    def list_by_org(self, org_id: str, active_only: bool = True) -> list[OrgPolicy]:
        return [p for p in self._items.values()
                if p.org_id == org_id and (not active_only or p.active)]

    def upsert(self, policy: OrgPolicy) -> str:
        existing = self._items.get(policy.id)
        if existing is not None and existing.org_id != policy.org_id:
            return existing.id              # KHÔNG ghi đè policy của org khác (cô lập org)
        self._items[policy.id] = policy
        return policy.id

    def delete(self, policy_id: str, org_id: str) -> bool:
        p = self._items.get(policy_id)
        if p is None or p.org_id != org_id:
            return False
        del self._items[policy_id]
        return True
