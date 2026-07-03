"""HttpReranker — cross-encoder rerank qua HTTP endpoint chuẩn TEI (`/rerank`).

Cho phép cắm reranker self-host (vd AITeamVN/Vietnamese_Reranker phục vụ bằng
text-embeddings-inference) vào retrieval mà KHÔNG đổi domain: trả về hàm
`rerank(query, docs) -> list[float]` cùng CONTRACT với `QwenAdapter.rerank`
(điểm theo ĐÚNG thứ tự `docs`; None khi chưa cấu hình → retriever passthrough).

Bật bằng: `CROSS_ENCODER_RERANK=true` + `RERANK_URL=http://<host>:<port>` (base URL của
TEI; adapter tự nối `/rerank`). Ưu tiên hơn qwen3-rerank khi cả hai được cấu hình.

A/B (Zalo LTR 788 query): AITeamVN MRR@10 0.745 vs qwen3-rerank 0.614 — xem
docs/internal/reranker-ab-deploy.md.
"""
from __future__ import annotations

from legalguard.adapters.outbound._http import post_json


class HttpReranker:
    name = "http-reranker"

    def __init__(self, base_url: str, timeout: float = 60) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.base_url)

    def rerank(self, query: str, docs: list[str]) -> list[float] | None:
        """Điểm/doc theo đúng thứ tự `docs`. TEI `/rerank` trả [{index, score}] đã sắp giảm dần —
        map ngược về thứ tự đầu vào. None khi chưa cấu hình (→ retriever giữ thứ tự base)."""
        if not self.available or not docs:
            return None
        results = post_json(f"{self.base_url}/rerank", provider=self.name,
                            json={"query": query, "texts": docs, "raw_scores": True},
                            timeout=self.timeout)
        scores = [0.0] * len(docs)
        for r in results:                          # TEI: list[{"index": int, "score": float}]
            scores[r["index"]] = float(r["score"])
        return scores
