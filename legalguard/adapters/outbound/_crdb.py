"""Helper CockroachDB/vector DÙNG CHUNG — gộp các bản trùng ở embedding_store + sql_memory_store.

Module LÁ (chỉ stdlib) → import từ đâu cũng KHÔNG gây vòng (embedding_store ↔ sql_memory_store trước đây
phải nhân bản để tránh cycle). Chuẩn hóa scheme URL CRDB nằm ở `sql_case_repository.get_engine`
(NGUỒN CHUẨN, mọi engine đi qua đó) — KHÔNG lặp ở đây.
"""
from __future__ import annotations


def vec_literal(vec: list[float]) -> str:
    """list[float] → chuỗi '[...]' để bind cột VECTOR CockroachDB (psycopg không có kiểu vector riêng)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity 2 vector; 0.0 nếu một vector rỗng/không chuẩn (an toàn chia)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0
