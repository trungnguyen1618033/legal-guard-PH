"""Adapter knowledge base (file .md) → implement KnowledgeBasePort/Provider.

- KeywordRetriever:  chấm điểm từ khóa (không cần key, luôn chạy).
- EmbeddingRetriever: semantic search bằng embedding + cosine.
- FileKnowledgeBaseProvider.for_tenant(): chọn semantic nếu có embed_fn, lỗi → keyword.
"""
from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Callable

from legalguard.domain.models import Snippet
from legalguard.domain.ports import KnowledgeBasePort, LLMPort
from legalguard.domain.tenants import Organization

EmbedFn = Callable[[list[str]], "list[list[float]] | None"]

_log = logging.getLogger(__name__)


def _load_chunks(base_dir: str, tenant: str) -> list[tuple[str, str]]:
    tenant_dir = Path(base_dir) / tenant
    chunks: list[tuple[str, str]] = []
    if not tenant_dir.exists():
        return chunks
    for md in sorted(tenant_dir.glob("*.md")):
        for para in re.split(r"\n\s*\n", md.read_text(encoding="utf-8")):
            if para.strip():
                chunks.append((md.name, para.strip()))
    return chunks


class KeywordRetriever:
    def __init__(self, base_dir: str, tenant: str) -> None:
        self._chunks = _load_chunks(base_dir, tenant)

    def retrieve(self, query: str, top_k: int = 4) -> list[Snippet]:
        terms = {t for t in re.findall(r"\w+", query.lower()) if len(t) > 2}
        scored = [
            Snippet(src, chunk, float(sum(chunk.lower().count(t) for t in terms)))
            for src, chunk in self._chunks
        ]
        scored = [s for s in scored if s.score > 0]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]


class EmbeddingRetriever:
    def __init__(self, base_dir: str, tenant: str, embed_fn: Callable[[list[str]], list[list[float]]]) -> None:
        self._chunks = _load_chunks(base_dir, tenant)
        self._vectors = embed_fn([c for _, c in self._chunks]) if self._chunks else []
        self._embed_fn = embed_fn

    def retrieve(self, query: str, top_k: int = 4) -> list[Snippet]:
        if not self._chunks:
            return []
        qv = self._embed_fn([query])[0]
        scored = [
            Snippet(src, chunk, _cosine(qv, vec))
            for (src, chunk), vec in zip(self._chunks, self._vectors)
        ]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]


class FullContextRetriever:
    """Trả TOÀN BỘ KB (CAG / long-context). Hợp khi KB nhỏ + tĩnh — bỏ qua query/top_k.

    Dùng để A/B với retrieval: với KB nhỏ, nạp hết có thể chính xác hơn nhưng tốn token hơn.
    """

    def __init__(self, base_dir: str, tenant: str) -> None:
        self._chunks = _load_chunks(base_dir, tenant)

    def retrieve(self, query: str, top_k: int = 4) -> list[Snippet]:
        return [Snippet(src, text, 1.0) for src, text in self._chunks]


class HybridRetriever:
    """Kết hợp keyword + embedding bằng Reciprocal Rank Fusion (RRF)."""

    def __init__(self, keyword: KnowledgeBasePort, embedding: KnowledgeBasePort) -> None:
        self.keyword = keyword
        self.embedding = embedding

    def retrieve(self, query: str, top_k: int = 4) -> list[Snippet]:
        fetch = max(top_k * 2, 8)
        lists = [self.keyword.retrieve(query, fetch), self.embedding.retrieve(query, fetch)]
        scores: dict[tuple, float] = {}
        snippets: dict[tuple, Snippet] = {}
        for lst in lists:
            for rank, s in enumerate(lst):
                key = (s.source, s.text)
                scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank + 1)  # RRF, k=60
                snippets[key] = s
        ranked = sorted(scores, key=lambda k: scores[k], reverse=True)
        return [snippets[k] for k in ranked[:top_k]]


class RerankRetriever:
    """Decorator: lấy nhiều ứng viên từ base rồi để LLM rerank (opt-in).

    LLM chưa cấu hình → passthrough (an toàn offline).
    """

    def __init__(self, base: KnowledgeBasePort, llm: LLMPort, fetch_k: int = 8) -> None:
        self.base = base
        self.llm = llm
        self.fetch_k = fetch_k

    def retrieve(self, query: str, top_k: int = 4) -> list[Snippet]:
        cands = self.base.retrieve(query, self.fetch_k)
        if not self.llm.available or len(cands) <= top_k:
            return cands[:top_k]
        listing = "\n".join(f"[{i}] {c.text[:200]}" for i, c in enumerate(cands))
        try:
            out = self.llm.complete(
                f"Query: {query}\nĐoạn:\n{listing}\n\n"
                "Liệt kê chỉ số [i] các đoạn liên quan nhất, giảm dần, cách nhau dấu phẩy."
            )
        except Exception:  # noqa: BLE001 — rerank lỗi → dùng thứ tự base
            return cands[:top_k]
        seen: set[int] = set()
        ranked: list[Snippet] = []
        for i in (int(x) for x in re.findall(r"\d+", out)):
            if 0 <= i < len(cands) and i not in seen:
                seen.add(i)
                ranked.append(cands[i])
        ranked += [c for j, c in enumerate(cands) if j not in seen]
        return ranked[:top_k]


def build_retriever(base_dir: str, tenant: str, embed_fn: EmbedFn | None = None,
                    reranker_llm: LLMPort | None = None, strategy: str = "auto") -> KnowledgeBasePort:
    """strategy: auto (hybrid nếu có embed, else keyword) | keyword | hybrid | full."""
    if strategy == "keyword":
        return KeywordRetriever(base_dir, tenant)
    if strategy == "full":
        return FullContextRetriever(base_dir, tenant)

    base: KnowledgeBasePort = KeywordRetriever(base_dir, tenant)
    if embed_fn is not None:
        try:
            base = HybridRetriever(base, EmbeddingRetriever(base_dir, tenant, embed_fn))  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001 — fallback an toàn khi embedding lỗi
            _log.warning("Embedding KB lỗi (tenant=%s) — hạ xuống keyword retriever.",
                         tenant, exc_info=True)
    if reranker_llm is not None:
        return RerankRetriever(base, reranker_llm)
    return base


class OverlayRetriever:
    """KB tùy biến theo công ty: ưu tiên overlay riêng, rồi tới KB quốc gia."""

    def __init__(self, primary: KnowledgeBasePort, overlay: KnowledgeBasePort) -> None:
        self.primary = primary
        self.overlay = overlay

    def retrieve(self, query: str, top_k: int = 4) -> list[Snippet]:
        seen, out = set(), []
        for h in self.overlay.retrieve(query, top_k) + self.primary.retrieve(query, top_k):
            key = (h.source, h.text)
            if key not in seen:
                seen.add(key)
                out.append(h)
        return out[:top_k]


class FileKnowledgeBaseProvider:
    """Implement KnowledgeBaseProvider: KB quốc gia (org.country) + overlay riêng công ty.

    Overlay đặt ở `<base_dir>/_orgs/<org_id>/*.md` (tùy chọn). SME dùng KB nền;
    enterprise thêm overlay riêng.
    """

    def __init__(self, base_dir: str, embed_fn: EmbedFn | None = None,
                 reranker_llm: LLMPort | None = None, strategy: str = "auto") -> None:
        self.base_dir = base_dir
        self.embed_fn = embed_fn
        self.reranker_llm = reranker_llm
        self.strategy = strategy
        self._cache: dict[tuple[str, str], KnowledgeBasePort] = {}

    def for_org(self, org: Organization) -> KnowledgeBasePort:
        # Cache theo (quốc gia, công ty): KB tĩnh → KHÔNG re-embed mỗi request.
        key = (org.country, org.id)
        if key not in self._cache:
            self._cache[key] = self._build(org)
        return self._cache[key]

    def _build(self, org: Organization) -> KnowledgeBasePort:
        base = build_retriever(self.base_dir, org.country, self.embed_fn,
                               self.reranker_llm, self.strategy)
        overlay_dir = Path(self.base_dir) / "_orgs" / org.id
        if overlay_dir.exists() and any(overlay_dir.glob("*.md")):
            overlay = build_retriever(self.base_dir, f"_orgs/{org.id}", strategy="keyword")
            return OverlayRetriever(base, overlay)
        return base


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
