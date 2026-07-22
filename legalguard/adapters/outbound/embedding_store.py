"""Kho EMBEDDING BỀN trong DB — tính 1 lần, tái dùng qua mọi lần khởi động (mở khóa corpus lớn).

Vấn đề cũ: `EmbeddingRetriever` embed TẤT CẢ chunk mỗi lần boot → chậm + tốn token + không scale.
Giải: lưu vector vào bảng `kb_vectors` theo HASH nội dung (id = sha256(text)). `get_or_embed` chỉ embed
chunk MỚI/đổi, còn lại nạp từ DB → boot gần như tức thì, chi phí embed = một-lần-cho-mỗi-chunk.

TÌM TƯƠNG TỰ — 2 đường (tự chọn theo DB):
- **pgvector ANN** (Postgres có extension `vector`): cột `vec vector(dim)` + index HNSW → tìm bằng
  `ORDER BY vec <=> q` TRONG DB (C, index). Scale tới trăm nghìn+ chunk. Bật tự động khi phát hiện được.
- **Brute-force cosine trong RAM** (SQLite dev / Postgres không pgvector): fallback — đủ tới ~vài nghìn
  chunk. Đo thực: >~18k chunk thì O(N)/truy vấn nghẽn CPU → đây là lý do có nhánh pgvector.
Vector JSON vẫn lưu song song (portable + cache dedup theo hash + fallback); cột `vec` chỉ thêm khi có pgvector.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

from sqlalchemy import String, Text, event, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from legalguard.adapters.outbound.sql_case_repository import Base, get_engine


def normalize_crdb_url(url: str) -> str:
    """URL CockroachDB → scheme `cockroachdb+psycopg://` (dialect chính thức + psycopg3; vanilla postgres
    dialect KHÔNG parse nổi version string CRDB). Nhận biết qua 'cockroach' trong URL; khác → giữ nguyên.
    (Trùng `normalize_memory_url` ở sql_memory_store — để RIÊNG đây tránh import vòng
    embedding_store↔sql_memory_store; gộp về 1 module `_crdb.py` sau khi merge 2 nhánh.)"""
    if not url or "cockroach" not in url.lower():
        return url
    return re.sub(r"^(postgresql(\+\w+)?|cockroachdb(\+\w+)?)://", "cockroachdb+psycopg://", url, count=1)


def _vec_literal(vec: list[float]) -> str:
    """list[float] → chuỗi '[...]' để bind cho cột VECTOR CockroachDB (psycopg không có kiểu vector riêng)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


class KbVectorRow(Base):
    __tablename__ = "kb_vectors"

    id: Mapped[str] = mapped_column(String, primary_key=True)   # sha256(text) — khử trùng + phát hiện đổi
    vector: Mapped[str] = mapped_column(Text)                   # JSON list[float] (portable; cache + fallback)


def _hash(text_: str) -> str:
    return hashlib.sha256(text_.encode("utf-8")).hexdigest()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class SqlEmbeddingStore:
    """Lưu/đọc embedding theo hash nội dung. Tính 1 lần, tái dùng qua các lần boot.

    `ann_enabled` (tự phát hiện): True nếu DB là Postgres + có pgvector → dùng ANN cột `vec`. Ngược lại
    False → brute-force (retriever tự xử). `enable_ann=False` để tắt cưỡng bức (A/B với brute-force)."""

    def __init__(self, database_url: str, enable_ann: bool = True) -> None:
        self.engine = get_engine(normalize_crdb_url(database_url))
        self._crdb = self.engine.dialect.name == "cockroachdb"
        # CRDB (anchor): chỉ tạo BẢNG kb_vectors (không dựng cả schema app lên cluster). Khác: create_all như cũ.
        if self._crdb:
            KbVectorRow.__table__.create(bind=self.engine, checkfirst=True)
        else:
            Base.metadata.create_all(self.engine)
        self.ann_enabled = False
        self._dim: int | None = None
        if enable_ann and self._crdb:
            self.ann_enabled = True        # C-SPANN in-DB; cột vec tạo khi biết dim (get_or_embed)
            self._detect_vec_column()      # restart → cột vec đã có → bật ANN + nhớ dim ngay
        elif enable_ann and self.engine.dialect.name == "postgresql":
            self._try_enable_pgvector()

    def _detect_vec_column(self) -> None:
        """CRDB restart: dò cột `vec VECTOR(dim)` đã tồn tại → set self._dim (khỏi ALTER lại)."""
        try:
            with self.engine.connect() as c:
                for row in c.execute(text("SHOW COLUMNS FROM kb_vectors")):
                    if row[0] == "vec":
                        m = re.search(r"VECTOR\((\d+)\)", str(row[1]), re.I)
                        if m:
                            self._dim = int(m.group(1))
        except Exception:  # noqa: BLE001 — không dò được → _ensure_vec_column sẽ lo khi ghi
            pass

    def _try_enable_pgvector(self) -> None:
        """Bật extension vector + đăng ký kiểu vector cho psycopg. Không có/không quyền → im lặng fallback."""
        try:
            from pgvector.psycopg import register_vector
            with self.engine.begin() as c:
                c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

            @event.listens_for(self.engine, "connect")   # đăng ký kiểu vector trên MỌI kết nối mới (psycopg3)
            def _reg(dbapi_conn, _rec):  # noqa: ANN001
                register_vector(dbapi_conn)
            # Bỏ các kết nối pool tạo TRƯỚC khi gắn listener (kể cả conn của create_all/CREATE EXTENSION)
            # → mọi kết nối sau đều mới → chắc chắn được register_vector (nếu không, list bị gửi thành array).
            self.engine.dispose()
            self.ann_enabled = True
        except Exception:  # noqa: BLE001 — pgvector thiếu/không quyền → fallback brute-force
            self.ann_enabled = False

    def _ensure_vec_column(self, dim: int) -> None:
        """Tạo cột `vec vector(dim)` (một lần, khi biết dim từ vector đầu).

        KHÔNG tạo HNSW index: ở quy mô vài chục nghìn chunk (KB luật VN), tìm EXACT trong Postgres
        (C/SIMD, `ORDER BY vec <=> q`) đã nhanh (ms) VÀ chính xác — thắng brute-force Python O(N) mà
        không mất recall. HNSW (xấp xỉ) chỉ đáng khi HÀNG TRIỆU vector; khi đó thêm index + chấp nhận
        recall<100% (xem docs). Cột PK `id` vẫn index → filter `id = ANY` nhanh."""
        if self._dim is not None:
            return
        with self.engine.begin() as c:
            if self._crdb:
                # CRDB: cột VECTOR + CREATE VECTOR INDEX (C-SPANN) → ANN in-DB scale (feature #1/4).
                c.execute(text(f"ALTER TABLE kb_vectors ADD COLUMN IF NOT EXISTS vec VECTOR({dim})"))
                try:
                    c.execute(text("CREATE VECTOR INDEX IF NOT EXISTS idx_kb_vec ON kb_vectors (vec)"))
                except Exception:  # noqa: BLE001 — index đã có / cú pháp phiên bản khác → ANN vẫn chạy
                    pass
            else:
                c.execute(text(f"ALTER TABLE kb_vectors ADD COLUMN IF NOT EXISTS vec vector({dim})"))
        self._dim = dim

    def get_or_embed(self, texts: list[str], embed_fn) -> list[list[float]] | None:
        """Trả vector cho `texts` (đúng thứ tự). CHỈ embed text CHƯA có trong DB; phần còn lại nạp từ DB.
        embed_fn(list[str])→list[vector]; trả None nếu embed_fn trả None (offline). Nếu ann_enabled: cũng
        ghi cột `vec` (pgvector) để tìm bằng ANN."""
        if not texts:
            return []
        ids = [_hash(t) for t in texts]
        new_pairs: list[tuple[str, list[float]]] = []          # (id, vec) chunk MỚI vừa embed
        # (1) ĐỌC cache trong transaction NGẮN rồi ĐÓNG NGAY. QUAN TRỌNG (CRDB): KHÔNG giữ transaction mở
        # qua `embed_fn` (gọi Qwen — MẠNG CHẬM); CockroachDB abort transaction giữ-mở-lâu =
        # RETRY_COMMIT_DEADLINE_EXCEEDED → EmbeddingRetriever dựng lỗi → hạ xuống keyword-only (mất hybrid).
        # Postgres/SQLite không có deadline này nhưng embed-ngoài-tx đúng cho MỌI backend (tx ngắn).
        with Session(self.engine) as s:
            cached = {r.id: json.loads(r.vector)
                      for r in s.scalars(select(KbVectorRow).where(KbVectorRow.id.in_(set(ids))))}
        missing_idx = [i for i, h in enumerate(ids) if h not in cached]
        if missing_idx:                                        # (2) EMBED phần thiếu — NGOÀI transaction
            new = embed_fn([texts[i] for i in missing_idx])
            if new is None:
                return None                                    # embed_fn offline → để retriever tự xử
            for i, vec in zip(missing_idx, new):
                cached[ids[i]] = vec
                new_pairs.append((ids[i], vec))
            with Session(self.engine) as s:                    # (3) GHI trong transaction NGẮN
                for id_, vec in new_pairs:
                    s.merge(KbVectorRow(id=id_, vector=json.dumps(vec)))
                s.commit()
        # DDL (ALTER TABLE cần ACCESS EXCLUSIVE) + ghi cột vec chạy NGOÀI Session trên — nếu còn trong
        # transaction đang SELECT kb_vectors thì ALTER sẽ deadlock chờ lock. Session đã đóng → an toàn.
        if self.ann_enabled and new_pairs:
            self._ensure_vec_column(len(new_pairs[0][1]))
            if self._crdb:                                     # CRDB: bind vector qua chuỗi '[...]'
                with self.engine.begin() as c:
                    for id_, vec in new_pairs:
                        c.execute(text("UPDATE kb_vectors SET vec = :v WHERE id = :id"),
                                  {"v": _vec_literal(vec), "id": id_})
            else:                                              # pgvector: bind qua kiểu Vector
                from pgvector import Vector
                with self.engine.begin() as c:
                    for id_, vec in new_pairs:
                        c.execute(text("UPDATE kb_vectors SET vec = :v WHERE id = :id"),
                                  {"v": Vector(vec), "id": id_})
        return [cached[h] for h in ids]

    def search_ann(self, query_vec: list[float], texts: list[str], top_k: int) -> list[tuple[int, float]]:
        """ANN trong DB: xếp `texts` (theo hash) gần `query_vec` nhất bằng cosine — [(index, score)] top_k.
        CHỈ trong tập chunk của KB hiện tại (WHERE id = ANY). score = 1 - cosine_distance (khớp brute-force)."""
        ids = [_hash(t) for t in texts]
        id_to_indices: dict[str, list[int]] = {}
        for i, h in enumerate(ids):
            id_to_indices.setdefault(h, []).append(i)
        if self._crdb:
            qv = _vec_literal(query_vec)                       # CRDB: bind vector qua chuỗi '[...]'
        else:
            from pgvector import Vector                        # pgvector: bọc list→kiểu Vector
            qv = Vector(query_vec)
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT id, 1 - (vec <=> :q) AS score FROM kb_vectors "
                "WHERE id = ANY(:ids) AND vec IS NOT NULL ORDER BY vec <=> :q LIMIT :k"),
                {"q": qv, "ids": list(set(ids)), "k": top_k}).all()
        out: list[tuple[int, float]] = []
        for rid, score in rows:
            for idx in id_to_indices.get(rid, []):
                out.append((idx, float(score)))
        return out[:top_k]

    @staticmethod
    def rank(query_vec: list[float], vectors: list[list[float]], top_k: int) -> list[tuple[int, float]]:
        """Cosine query ↔ từng vector → [(index, score)] top_k giảm dần (brute-force, cho fallback)."""
        scored = [(i, _cosine(query_vec, v)) for i, v in enumerate(vectors)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
