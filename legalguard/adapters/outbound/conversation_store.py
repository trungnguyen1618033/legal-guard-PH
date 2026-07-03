"""Lưu phiên chat → implement ConversationStorePort.

3 backend (cùng port, đổi không đụng domain):
- InMemory: dev/test (mất khi restart, 1 instance).
- SqlAlchemy: persist + ĐA INSTANCE (chung DB) — mặc định prod.
- Redis: persist + TTL + nhanh. URL redis:// (local) hoặc rediss:// (TLS — Upstash/managed).
"""
from __future__ import annotations

import json

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from legalguard.adapters.outbound.sql_case_repository import Base, get_engine
from legalguard.domain.models import Conversation


class InMemoryConversationStore:
    def __init__(self) -> None:
        self._data: dict[str, Conversation] = {}

    def get(self, key: str) -> Conversation | None:
        return self._data.get(key)

    def save(self, conversation: Conversation) -> None:
        self._data[conversation.id] = conversation


class ConversationRow(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    history: Mapped[list] = mapped_column(JSON, default=list)
    context: Mapped[str] = mapped_column(String, default="")
    nego_state: Mapped[str] = mapped_column(String, default="")
    updated_at: Mapped[str] = mapped_column(String, default="")


class SqlAlchemyConversationStore:
    def __init__(self, database_url: str) -> None:
        self.engine = get_engine(database_url)
        Base.metadata.create_all(self.engine)

    def get(self, key: str) -> Conversation | None:
        with Session(self.engine) as s:
            row = s.get(ConversationRow, key)
            if row is None:
                return None
            return Conversation(id=row.id, history=row.history or [],
                                context=row.context or "", nego_state=row.nego_state or "",
                                updated_at=row.updated_at or "")

    def save(self, conversation: Conversation) -> None:
        with Session(self.engine) as s:
            s.merge(ConversationRow(id=conversation.id, history=conversation.history,
                                    context=conversation.context, nego_state=conversation.nego_state,
                                    updated_at=conversation.updated_at))
            s.commit()


class RedisConversationStore:
    def __init__(self, url: str, ttl_seconds: int = 7 * 24 * 3600) -> None:
        import redis  # lazy — chỉ cần khi dùng backend redis

        self.r = redis.from_url(url)
        self.ttl = ttl_seconds

    def get(self, key: str) -> Conversation | None:
        raw = self.r.get(f"conv:{key}")
        return Conversation(**json.loads(raw)) if raw else None

    def save(self, conversation: Conversation) -> None:
        self.r.set(f"conv:{conversation.id}",
                   json.dumps(vars(conversation), ensure_ascii=False), ex=self.ttl)
