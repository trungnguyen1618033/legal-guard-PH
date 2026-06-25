"""Adapter feedback (phản hồi người dùng về câu trả lời) → implement FeedbackRepositoryPort.

Dùng chung Base/engine với cases. Phản hồi 'wrong'/'incomplete' là tín hiệu để gom golden set + tìm
lỗ hổng KB từ usage thật (vòng học). Cô lập theo org.
"""
from __future__ import annotations

from sqlalchemy import String, desc, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from legalguard.adapters.outbound.sql_case_repository import Base, get_engine
from legalguard.domain.models import Feedback


class FeedbackRow(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String, index=True, default="default")
    kind: Mapped[str] = mapped_column(String, default="lookup")     # analysis | lookup
    ref: Mapped[str] = mapped_column(String, default="")
    rating: Mapped[str] = mapped_column(String, index=True, default="")  # helpful | wrong | incomplete
    note: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[str] = mapped_column(String)


class SqlAlchemyFeedbackRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = get_engine(database_url)
        Base.metadata.create_all(self.engine)

    def record(self, feedback: Feedback) -> str:
        with Session(self.engine) as s:
            s.merge(FeedbackRow(**vars(feedback)))
            s.commit()
        return feedback.id

    def list_by_org(self, org_id: str, limit: int = 100) -> list[Feedback]:
        stmt = (select(FeedbackRow).where(FeedbackRow.org_id == org_id)
                .order_by(desc(FeedbackRow.created_at)).limit(limit))
        with Session(self.engine) as s:
            return [Feedback(id=r.id, org_id=r.org_id, kind=r.kind, ref=r.ref,
                             rating=r.rating, note=r.note, created_at=r.created_at)
                    for r in s.scalars(stmt).all()]
