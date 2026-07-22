"""Helper CockroachDB/vector DÙNG CHUNG — gộp các bản trùng (embedding_store + sql_memory_store + get_engine).

Module LÁ (chỉ stdlib) → import từ đâu cũng KHÔNG gây vòng (embedding_store ↔ sql_memory_store trước đây
phải nhân bản để tránh cycle). NHÀ CHUNG duy nhất cho: chuẩn hóa scheme URL CRDB + bind vector + cosine.
"""
from __future__ import annotations

import re


def normalize_crdb_url(url: str) -> str:
    """URL CockroachDB → scheme `cockroachdb+psycopg://` (dialect chính thức + psycopg3; vanilla postgres
    dialect KHÔNG parse nổi version string CRDB → mọi repo/alembic phải qua đây). Nhận biết qua 'cockroach'
    trong URL; idempotent; khác → giữ nguyên. NGUỒN CHUẨN duy nhất (get_engine + 2 store re-export/import)."""
    if not url or "cockroach" not in url.lower():
        return url
    return re.sub(r"^(postgresql(\+\w+)?|cockroachdb(\+\w+)?)://", "cockroachdb+psycopg://", url, count=1)


def vec_literal(vec: list[float]) -> str:
    """list[float] → chuỗi '[...]' để bind cột VECTOR CockroachDB (psycopg không có kiểu vector riêng)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity 2 vector; 0.0 nếu một vector rỗng/không chuẩn (an toàn chia)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0
