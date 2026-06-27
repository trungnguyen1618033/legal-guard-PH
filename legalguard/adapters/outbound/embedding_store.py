"""Kho EMBEDDING BỀN trong DB — tính 1 lần, tái dùng qua mọi lần khởi động (mở khóa corpus lớn).

Vấn đề cũ: `EmbeddingRetriever` embed TẤT CẢ chunk mỗi lần boot → chậm + tốn token + không scale.
Giải: lưu vector vào bảng `kb_vectors` theo HASH nội dung (id = sha256(text)). `get_or_embed` chỉ embed
chunk MỚI/đổi, còn lại nạp từ DB → boot gần như tức thì, chi phí embed = một-lần-cho-mỗi-chunk.

Portable: vector lưu JSON (chạy SQLite dev + Postgres prod). Tìm tương tự = cosine trong RAM (đủ tới ~chục
nghìn chunk). Quy mô RẤT lớn (100k+): nâng cột `Vector` pgvector + `ORDER BY emb <=> q` (ANN) — cùng bảng/
interface, chỉ đổi search. Đây là adapter nền cho hướng pgvector.
"""
from __future__ import annotations

import hashlib
import json
import math

from sqlalchemy import String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from legalguard.adapters.outbound.sql_case_repository import Base, get_engine


class KbVectorRow(Base):
    __tablename__ = "kb_vectors"

    id: Mapped[str] = mapped_column(String, primary_key=True)   # sha256(text) — khử trùng + phát hiện đổi
    vector: Mapped[str] = mapped_column(Text)                   # JSON list[float] (portable; pgvector sau)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class SqlEmbeddingStore:
    """Lưu/đọc embedding theo hash nội dung. Tính 1 lần, tái dùng qua các lần boot."""

    def __init__(self, database_url: str) -> None:
        self.engine = get_engine(database_url)
        Base.metadata.create_all(self.engine)

    def get_or_embed(self, texts: list[str], embed_fn) -> list[list[float]] | None:
        """Trả vector cho `texts` (đúng thứ tự). CHỈ embed text CHƯA có trong DB; phần còn lại nạp từ DB.
        embed_fn(list[str])→list[vector] (vd QwenAdapter.embed); trả None nếu embed_fn trả None (offline)."""
        if not texts:
            return []
        ids = [_hash(t) for t in texts]
        with Session(self.engine) as s:
            cached = {r.id: json.loads(r.vector)
                      for r in s.scalars(select(KbVectorRow).where(KbVectorRow.id.in_(set(ids))))}
            missing_idx = [i for i, h in enumerate(ids) if h not in cached]
            if missing_idx:                                    # chỉ embed phần thiếu
                new = embed_fn([texts[i] for i in missing_idx])
                if new is None:
                    return None                               # embed_fn offline → để retriever tự xử
                for i, vec in zip(missing_idx, new):
                    cached[ids[i]] = vec
                    s.merge(KbVectorRow(id=ids[i], vector=json.dumps(vec)))
                s.commit()
        return [cached[h] for h in ids]

    @staticmethod
    def rank(query_vec: list[float], vectors: list[list[float]], top_k: int) -> list[tuple[int, float]]:
        """Cosine query ↔ từng vector → [(index, score)] top_k giảm dần. (pgvector sẽ thay bằng ANN trong DB.)"""
        scored = [(i, _cosine(query_vec, v)) for i, v in enumerate(vectors)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
