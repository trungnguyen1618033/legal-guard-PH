"""Adapter knowledge base (file .md) → implement KnowledgeBasePort/Provider.

- KeywordRetriever:  lexical BM25 (Okapi) — chuẩn hóa độ dài + IDF (không cần key, luôn chạy).
- EmbeddingRetriever: semantic search bằng embedding + cosine.
- FileKnowledgeBaseProvider.for_tenant(): chọn semantic nếu có embed_fn, lỗi → keyword.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

from legalguard.adapters.outbound.legal_chunker import (
    article_key,
    chunk_legal,
    extract_article_refs,
    nfc,
    parse_front_matter,
)
from legalguard.domain.models import Snippet
from legalguard.domain.ports import KnowledgeBasePort, LLMPort
from legalguard.domain.tenants import Organization

EmbedFn = Callable[[list[str]], "list[list[float]] | None"]
# Rerank cross-encoder: (query, docs) -> điểm liên quan / doc (cao = liên quan hơn), hoặc None khi không sẵn.
RerankFn = Callable[[str, "list[str]"], "list[float] | None"]

_log = logging.getLogger(__name__)


def _load_chunks(base_dir: str, tenant: str) -> list[tuple[str, str]]:
    """Nạp KB → [(source, text)]. Bỏ front-matter, chunk theo cấu trúc Điều/Khoản (legal_chunker);
    nhãn cấu trúc gắn vào source dạng 'file.md#Điều 5' để dẫn nguồn đúng cấp điều luật."""
    tenant_dir = Path(base_dir) / tenant
    chunks: list[tuple[str, str]] = []
    if not tenant_dir.exists():
        return chunks
    for md in sorted(tenant_dir.glob("*.md")):
        _, body = parse_front_matter(md.read_text(encoding="utf-8"))
        for label, text in chunk_legal(body):
            source = f"{md.name}#{label}" if label else md.name
            chunks.append((source, text))
    return chunks


# Trạng thái coi là CÒN hiệu lực (mặc định khi không khai báo → còn hiệu lực).
_IN_FORCE = {"", "in_force", "con_hieu_luc", "còn hiệu lực", "active", "valid"}


def _load_doc_status(base_dir: str, tenant: str) -> dict[str, str]:
    """filename → status (từ front-matter). File không khai báo → 'in_force'."""
    out: dict[str, str] = {}
    tenant_dir = Path(base_dir) / tenant
    if not tenant_dir.exists():
        return out
    for md in sorted(tenant_dir.glob("*.md")):
        meta, _ = parse_front_matter(md.read_text(encoding="utf-8"))
        out[md.name] = (meta.get("status") or "in_force").strip().lower()
    return out


def _is_in_force(status: str) -> bool:
    return status.strip().lower() in _IN_FORCE


def _load_doc_dates(base_dir: str, tenant: str) -> dict[str, tuple[str, str]]:
    """filename → (effective_date, expiry_date) ISO từ front-matter. Cho point-in-time retrieval."""
    out: dict[str, tuple[str, str]] = {}
    tenant_dir = Path(base_dir) / tenant
    if not tenant_dir.exists():
        return out
    for md in sorted(tenant_dir.glob("*.md")):
        meta, _ = parse_front_matter(md.read_text(encoding="utf-8"))
        out[md.name] = (meta.get("effective_date", "").strip(), meta.get("expiry_date", "").strip())
    return out


# Quan hệ cấp văn bản (front-matter) → cạnh closure doc-level (kéo VB sửa đổi/thay thế/hướng dẫn liên quan).
_REL_FIELDS = ("amends", "amended_by", "replaced_by", "replaces", "guided_by", "guides")


def _load_doc_relations(base_dir: str, tenant: str) -> dict[str, list[str]]:
    """filename → list doc_id liên quan (từ front-matter amends/amended_by/replaced_by/...)."""
    out: dict[str, list[str]] = {}
    tenant_dir = Path(base_dir) / tenant
    if not tenant_dir.exists():
        return out
    for md in sorted(tenant_dir.glob("*.md")):
        meta, _ = parse_front_matter(md.read_text(encoding="utf-8"))
        ids: list[str] = []
        for f in _REL_FIELDS:
            ids += [x.strip().upper() for x in re.split(r"[;,]", meta.get(f, "")) if x.strip()]
        if ids:
            out[md.name] = ids
    return out


# Quan hệ nghịch đảo để suy ra cạnh 2 chiều (A amends B ⇒ B amended_by A).
_REL_INVERSE = {"amends": "amended_by", "amended_by": "amends",
                "replaces": "replaced_by", "replaced_by": "replaces",
                "guides": "guided_by", "guided_by": "guides"}


def _load_doc_meta(base_dir: str, tenant: str) -> dict[str, dict]:
    """filename → front-matter (đầy đủ). Dùng cho changelog (title/ngày/trạng thái + quan hệ)."""
    out: dict[str, dict] = {}
    tenant_dir = Path(base_dir) / tenant
    if not tenant_dir.exists():
        return out
    for md in sorted(tenant_dir.glob("*.md")):
        out[md.name] = parse_front_matter(md.read_text(encoding="utf-8"))[0]
    return out


def legal_changelog(base_dir: str, tenant: str, doc_id: str) -> dict | None:
    """'What changed' cấp văn bản: văn bản `doc_id` được sửa đổi/thay thế/hướng dẫn bởi (hoặc của) VB nào,
    kèm ngày hiệu lực + trạng thái — suy 2 chiều từ front-matter. None nếu không có doc_id trong KB."""
    did = doc_id.strip().upper()
    metas = _load_doc_meta(base_dir, tenant)
    by_docid = {(m.get("doc_id") or "").upper(): m for m in metas.values() if m.get("doc_id")}
    if did not in by_docid:
        return None
    rel: dict[tuple[str, str], bool] = {}
    self_meta = by_docid[did]
    for f in _REL_FIELDS:                                   # cạnh thuận (khai trong chính VB)
        for tid in re.split(r"[;,]", self_meta.get(f, "")):
            if tid.strip():
                rel[(f, tid.strip().upper())] = True
    for m in metas.values():                                # cạnh nghịch (VB khác trỏ tới doc_id)
        oid = (m.get("doc_id") or "").upper()
        if oid == did:
            continue
        for f in _REL_FIELDS:
            if any(t.strip().upper() == did for t in re.split(r"[;,]", m.get(f, "")) if t.strip()):
                rel[(_REL_INVERSE.get(f, f), oid)] = True
    related = []
    for (r, tid) in sorted(rel):
        info = {"relation": r, "doc_id": tid}
        if tid in by_docid:
            tm = by_docid[tid]
            info.update(title=tm.get("title", ""), effective_date=tm.get("effective_date", ""),
                        status=tm.get("status", "in_force"))
        related.append(info)
    return {"doc_id": did, "title": self_meta.get("title", ""),
            "status": self_meta.get("status", "in_force"),
            "effective_date": self_meta.get("effective_date", ""), "related": related}


def _doc_edges(base_dir: str, tenant: str) -> tuple[dict[str, dict], set[tuple[str, str, str]]]:
    """(by_docid: {DOC_ID→front-matter}, edges: {(from_id, relation, to_id)}) — suy 2 chiều MỘT LẦN.
    Nền cho lược đồ + map VB mới nhất ở quy mô lớn (O(N), không quét lại mỗi hop như changelog)."""
    metas = _load_doc_meta(base_dir, tenant)
    by_docid = {(m.get("doc_id") or "").upper(): m for m in metas.values() if m.get("doc_id")}
    edges: set[tuple[str, str, str]] = set()
    for m in metas.values():
        sid = (m.get("doc_id") or "").upper()
        if not sid:
            continue
        for f in _REL_FIELDS:
            for tid in re.split(r"[;,]", m.get(f, "")):
                tid = tid.strip().upper()
                if tid:
                    edges.add((sid, f, tid))
                    edges.add((tid, _REL_INVERSE.get(f, f), sid))   # cạnh nghịch (2 chiều)
    return by_docid, edges


def legal_graph(base_dir: str, tenant: str, doc_id: str, depth: int = 1) -> dict | None:
    """Lược đồ văn bản (như TVPL): từ `doc_id` mở rộng quan hệ tới `depth` hop → {nodes, edges}.
    node: {doc_id, title, status, effective_date, in_kb}; edge: {from, relation, to}. None nếu không có VB."""
    did = doc_id.strip().upper()
    by_docid, edges = _doc_edges(base_dir, tenant)
    adj: dict[str, list[tuple[str, str]]] = {}
    for (s, r, t) in edges:
        adj.setdefault(s, []).append((r, t))
    if did not in by_docid and did not in adj:
        return None
    seen, frontier, node_ids, out_edges = {did}, [did], {did}, []
    for _ in range(max(1, depth)):
        nxt: list[str] = []
        for s in frontier:
            for (r, t) in adj.get(s, []):
                out_edges.append((s, r, t))
                if t not in seen:
                    seen.add(t)
                    node_ids.add(t)
                    nxt.append(t)
        frontier = nxt

    def _node(i: str) -> dict:
        m = by_docid.get(i, {})
        return {"doc_id": i, "title": m.get("title", ""), "status": m.get("status", "in_force"),
                "effective_date": m.get("effective_date", ""), "in_kb": i in by_docid}

    uniq = {e: {"from": e[0], "relation": e[1], "to": e[2]} for e in out_edges}
    edges_sorted = [uniq[e] for e in sorted(uniq)]      # tất định (set adjacency vốn không thứ tự)
    return {"root": did, "depth": depth, "nodes": [_node(i) for i in sorted(node_ids)],
            "edges": edges_sorted}


def latest_version(base_dir: str, tenant: str, doc_id: str) -> dict | None:
    """Map tới VĂN BẢN MỚI NHẤT: theo chuỗi `replaced_by` (thay thế toàn bộ) đến VB cuối chưa bị thay.
    Trả {doc_id, latest, replaced, chain, latest_status, latest_title}. None nếu doc_id không có trong KB.
    (Sửa đổi `amended_by` KHÔNG coi là thay thế — VB gốc vẫn hiệu lực, chỉ bị sửa vài điều.)"""
    did = doc_id.strip().upper()
    by_docid, edges = _doc_edges(base_dir, tenant)
    if did not in by_docid:
        return None
    repl: dict[str, list[str]] = {}
    for (s, r, t) in edges:
        if r == "replaced_by":
            repl.setdefault(s, []).append(t)
    cur, chain, seen = did, [], {did}
    while cur in repl:
        # Nhiều VB thay thế → chọn cái MỚI NHẤT theo effective_date (đúng nghĩa "mới nhất"); chống lặp.
        cands = [t for t in repl[cur] if t not in seen]
        if not cands:
            break
        cur = max(cands, key=lambda i: by_docid.get(i, {}).get("effective_date", ""))
        chain.append(cur)
        seen.add(cur)
    lm = by_docid.get(cur, {})
    return {"doc_id": did, "latest": cur, "replaced": cur != did, "chain": chain,
            "latest_status": lm.get("status", ""), "latest_title": lm.get("title", "")}


def recent_laws(base_dir: str, tenant: str, since: str) -> list[dict]:
    """VB có effective_date >= `since` (ISO 'YYYY-MM-DD') — phát hiện luật MỚI cho giám sát chủ động
    (autopilot). Trả [{doc_id, title, effective_date, status}] sắp giảm dần theo ngày hiệu lực."""
    out = []
    for m in _load_doc_meta(base_dir, tenant).values():
        did = (m.get("doc_id") or "").strip()
        eff = (m.get("effective_date") or "").strip()
        if did and eff and eff >= since:
            out.append({"doc_id": did, "title": m.get("title", ""), "effective_date": eff,
                        "status": m.get("status", "in_force")})
    return sorted(out, key=lambda x: x["effective_date"], reverse=True)


def amended_articles(base_dir: str, tenant: str, doc_id: str) -> dict | None:
    """Đọc luật `doc_id`: ĐIỀU nào của nó đã bị VB khác SỬA ĐỔI + bởi VB nào (cho 'bôi vàng' kiểu TVPL).
    {article: [doc_id VB sửa]} lấy từ `amends_articles` của các VB amends doc_id. None nếu không có VB."""
    did = doc_id.strip().upper()
    by_docid, edges = _doc_edges(base_dir, tenant)
    if did not in by_docid:
        return None
    out: dict[str, list[str]] = {}
    for (s, r, t) in edges:
        if r == "amends" and t == did and s in by_docid:           # VB s sửa doc_id
            for a in re.split(r"[;,]", by_docid[s].get("amends_articles", "")):
                a = a.strip()
                if a:
                    out.setdefault(a, [])
                    if s not in out[a]:
                        out[a].append(s)
    return {"doc_id": did, "amended_articles": out}


_CHANGE_RELATIONS = ("amends", "replaces", "guides")   # doc_id MỚI tác động LÊN văn bản đích


def affected_doc_files(base_dir: str, tenant: str, doc_id: str) -> dict[str, dict]:
    """Văn bản mới `doc_id` sửa đổi/thay thế/hướng dẫn những FILE nào trong KB.

    → {filename: {"relation": str, "articles": list[str]}}. `articles` = các Điều của văn bản đích bị
    tác động (từ front-matter `amends_articles` của CHÍNH `doc_id`); RỖNG = tác động cả văn bản
    (doc-level). Dùng cho regulatory change intelligence: VB mới → file luật cũ bị tác động (qua
    changelog) → đối chiếu căn cứ pháp lý các case. {} nếu doc_id không có trong KB / không tác động ai."""
    cl = legal_changelog(base_dir, tenant, doc_id)
    if not cl:
        return {}
    ids = _load_doc_ids(base_dir, tenant)
    # Điều bị tác động (article-level) khai trong front-matter `amends_articles` của VB mới.
    metas = _load_doc_meta(base_dir, tenant)
    self_fn = ids.get(doc_id.strip().upper())
    raw_arts = (metas.get(self_fn, {}).get("amends_articles", "") if self_fn else "")
    articles = [a.strip() for a in re.split(r"[;,]", raw_arts) if a.strip()]
    out: dict[str, dict] = {}
    for rel in cl["related"]:
        if rel["relation"] in _CHANGE_RELATIONS:
            fn = ids.get(rel["doc_id"])
            if fn:
                # CHỈ "amends" mới lọc theo điều (sửa một số Điều). "replaces" = thay cả văn bản →
                # mọi viện dẫn đều lỗi thời (articles rỗng = doc-level). "guides" cũng doc-level.
                arts = articles if rel["relation"] == "amends" else []
                # doc_id của VB cũ BỊ tác động — để scan_cases khớp được cả căn cứ văn xuôi nêu số hiệu.
                out[fn] = {"relation": rel["relation"], "articles": arts, "doc_id": rel["doc_id"]}
    return out


def _load_doc_ids(base_dir: str, tenant: str) -> dict[str, str]:
    """doc_id (số hiệu, chuẩn hóa UPPER) → filename. Để phân giải dẫn chiếu liên văn bản đúng đích."""
    out: dict[str, str] = {}
    tenant_dir = Path(base_dir) / tenant
    if not tenant_dir.exists():
        return out
    for md in sorted(tenant_dir.glob("*.md")):
        meta, _ = parse_front_matter(md.read_text(encoding="utf-8"))
        did = (meta.get("doc_id") or "").strip().upper()
        if did:
            out[did] = md.name
    return out


def _tokenize(text: str) -> list[str]:
    """Tách token (NFC, lower, len>2). Dùng chung cho index + query của BM25."""
    return [t for t in re.findall(r"\w+", nfc(text).lower()) if len(t) > 2]


class KeywordRetriever:
    """Lexical retrieval bằng BM25 (Okapi) — chuẩn hóa độ dài chunk + IDF, thay cho đếm tần suất thô.

    BM25 sửa hai lỗi của đếm thô: (1) chunk dài không còn thắng oan (length normalization), (2) từ phổ
    biến ('hợp đồng', 'quy định') bị IDF hạ trọng số, từ đặc trưng nổi lên. Tất định, offline, không cần key.
    """
    _K1 = 1.5
    _B = 0.75

    def __init__(self, base_dir: str, tenant: str) -> None:
        self._chunks = _load_chunks(base_dir, tenant)
        self._docs = [_tokenize(text) for _, text in self._chunks]
        self._tf = [Counter(d) for d in self._docs]
        self._len = [len(d) for d in self._docs]
        self._avgdl = (sum(self._len) / len(self._len)) if self._docs else 0.0
        df: Counter = Counter()
        for d in self._docs:
            df.update(set(d))
        n = len(self._docs)
        self._idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def retrieve(self, query: str, top_k: int = 4) -> list[Snippet]:
        q = [t for t in _tokenize(query) if t in self._idf]
        if not q or not self._docs:
            return []
        scored: list[Snippet] = []
        for i, (src, chunk) in enumerate(self._chunks):
            tf, dl = self._tf[i], self._len[i]
            score = 0.0
            for t in q:
                f = tf.get(t, 0)
                if f:
                    denom = f + self._K1 * (1 - self._B + self._B * dl / (self._avgdl or 1))
                    score += self._idf[t] * f * (self._K1 + 1) / denom
            if score > 0:
                scored.append(Snippet(src, chunk, score))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]


class EmbeddingRetriever:
    def __init__(self, base_dir: str, tenant: str, embed_fn: Callable[[list[str]], list[list[float]]],
                 store=None) -> None:
        self._chunks = _load_chunks(base_dir, tenant)
        self._embed_fn = embed_fn
        # `store` (SqlEmbeddingStore, tùy chọn): embed BỀN — chỉ tính chunk mới, boot không embed lại
        # (mở khóa corpus lớn). Không có store → embed tất cả tại chỗ (KB nhỏ, hành vi cũ).
        self._store = store
        # ANN pgvector nếu store hỗ trợ (Postgres+pgvector) → tìm TRONG DB, không quét O(N) trong RAM.
        self._ann = bool(store is not None and getattr(store, "ann_enabled", False) and self._chunks)
        texts = [c for _, c in self._chunks]
        if store is not None and self._chunks:
            self._vectors = store.get_or_embed(texts, embed_fn)   # đảm bảo đã embed (+ ghi cột vec cho ANN)
            if self._vectors is None:                  # embed offline/lỗi → coi như không có embedding
                self._vectors, self._chunks, self._ann = [], [], False
        else:
            self._vectors = embed_fn(texts) if self._chunks else []

    def retrieve(self, query: str, top_k: int = 4) -> list[Snippet]:
        if not self._chunks:
            return []
        qv = self._embed_fn([nfc(query)])[0]
        if self._ann:                                  # ANN trong DB (scale corpus lớn — hết O(N) Python)
            texts = [c for _, c in self._chunks]
            return [Snippet(self._chunks[i][0], self._chunks[i][1], score)
                    for i, score in self._store.search_ann(qv, texts, top_k)]
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


class CrossEncoderRerankRetriever:
    """Decorator: lấy fetch_k ứng viên từ base rồi rerank bằng cross-encoder (vd Qwen/BGE reranker VN).

    Đây là tầng 2 của pipeline retrieve→rerank — lực đẩy chất lượng lớn nhất cho pháp lý VN
    (Zalo-legal: +5 MRR@10). `rerank_fn(query, docs)` trả điểm/doc; None hoặc lỗi → passthrough
    (an toàn offline / khi chưa cấu hình key). Khác RerankRetriever (dùng LLM sinh chuỗi chỉ số):
    cross-encoder cho điểm trực tiếp, rẻ và ổn định hơn.
    """

    def __init__(self, base: KnowledgeBasePort, rerank_fn: RerankFn, fetch_k: int = 12) -> None:
        self.base = base
        self.rerank_fn = rerank_fn
        self.fetch_k = fetch_k
        self._enabled = True       # circuit-breaker: lỗi 1 lần (vd 403 chưa kích hoạt) → tự tắt, khỏi hammer

    def retrieve(self, query: str, top_k: int = 4) -> list[Snippet]:
        cands = self.base.retrieve(query, self.fetch_k)
        if not self._enabled or len(cands) <= top_k:
            return cands[:top_k]
        try:
            scores = self.rerank_fn(nfc(query), [c.text for c in cands])
        except Exception:  # noqa: BLE001 — rerank lỗi → tắt hẳn (tránh gọi lại endpoint hỏng) + giữ base
            self._enabled = False
            _log.warning("Cross-encoder rerank lỗi — tắt rerank, giữ thứ tự base (BM25+embedding).",
                         exc_info=True)
            return cands[:top_k]
        if not scores or len(scores) != len(cands):
            return cands[:top_k]
        ranked = sorted(zip(cands, scores), key=lambda cs: cs[1], reverse=True)
        return [Snippet(c.source, c.text, float(s)) for c, s in ranked[:top_k]]


# Ý định tra cứu lịch sử → cho phép trả cả văn bản đã hết hiệu lực/bị thay.
_HISTORICAL_RE = re.compile(
    r"hết hiệu lực|bản cũ|phiên bản cũ|trước đây|trước khi (sửa|thay)|"
    r"đã bị (thay|sửa|bãi bỏ)|từng quy định|quy định cũ|lịch sử",
    re.IGNORECASE,
)


def _is_historical_query(query: str) -> bool:
    return bool(_HISTORICAL_RE.search(nfc(query)))


# Point-in-time: rút mốc thời gian "as of" từ câu hỏi → ISO date. Tránh năm trong SỐ HIỆU văn bản
# (vd "123/2020/NĐ-CP" — phần loại VB không phải số nên dd/mm/yyyy không khớp).
_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_YEAR_RE = re.compile(r"năm\s+(\d{4})", re.IGNORECASE)
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _extract_as_of(query: str) -> str | None:
    """'ngày 1/6/2022' / '01/06/2022' → '2022-06-01'; 'năm 2020' → '2020-12-31'; ISO giữ nguyên. None nếu không có."""
    q = nfc(query)
    m = _ISO_RE.search(q)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _DATE_RE.search(q)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = _YEAR_RE.search(q)
    if m:
        return f"{m.group(1)}-12-31"        # "năm X" → tính tới cuối năm đó
    return None


def _valid_at(eff: str, exp: str, as_of: str) -> bool:
    """Văn bản còn hiệu lực TẠI as_of: đã có hiệu lực (eff<=as_of) và chưa hết (exp rỗng hoặc as_of<exp)."""
    if eff and eff > as_of:                  # chưa có hiệu lực tại thời điểm đó
        return False
    if exp and as_of >= exp:                 # đã hết hiệu lực tại thời điểm đó
        return False
    return True


class InForceRetriever:
    """Lọc hiệu lực: mặc định CHỈ trả văn bản còn hiệu lực — diệt 'inapplicable authority'
    (trả điều luật đã hết hiệu lực/bị thay; lỗi RAG pháp lý hàng đầu theo Stanford RegLab).

    3 chế độ (theo query): (1) có mốc thời gian ('năm 2020', '1/6/2022') → POINT-IN-TIME: trả VB còn
    hiệu lực TẠI mốc đó (effective_date/expiry_date); (2) ý định lịch sử ('bản cũ') → trả hết; (3) mặc
    định → chỉ VB còn hiệu lực hiện tại. Bọc base (trước rerank/closure).
    """

    def __init__(self, base: KnowledgeBasePort, base_dir: str, tenant: str, fetch_mult: int = 3) -> None:
        self.base = base
        self.fetch_mult = fetch_mult
        self._status = _load_doc_status(base_dir, tenant)
        self._dates = _load_doc_dates(base_dir, tenant)

    def _ok(self, source: str) -> bool:
        return _is_in_force(self._status.get(source.split("#", 1)[0], "in_force"))

    def retrieve(self, query: str, top_k: int = 4) -> list[Snippet]:
        as_of = _extract_as_of(query)
        if as_of:                            # POINT-IN-TIME: lọc theo hiệu lực TẠI mốc as_of
            fetch = max(top_k * self.fetch_mult, 12)
            kept = []
            for h in self.base.retrieve(query, fetch):
                eff, exp = self._dates.get(h.source.split("#", 1)[0], ("", ""))
                if _valid_at(eff, exp, as_of):
                    kept.append(h)
            return kept[:top_k]
        if _is_historical_query(query):
            return self.base.retrieve(query, top_k)
        fetch = max(top_k * self.fetch_mult, 12)
        kept = [h for h in self.base.retrieve(query, fetch) if self._ok(h.source)]
        return kept[:top_k]


class CitationClosureRetriever:
    """Phase 2 — citation closure (DOCUMENT-AWARE): sau khi khớp, ĐI THEO dẫn chiếu kéo về điều được trỏ
    tới, phân giải ĐÚNG VĂN BẢN đích (không đoán theo số điều).

    'Điều 294 của Luật này' → cùng file; 'Điều 9 của Nghị định 123/2020/NĐ-CP' → đúng file NĐ 123 (xuyên
    cấp Luật→NĐ→TT); 'Điều 10' trống ngữ cảnh → mặc định cùng file. Đồ thị dựng BẰNG RULE
    (`extract_article_refs` + map doc_id→file), không để LLM bịa cạnh. 1-hop, decay điểm; đích vắng/đã
    hết hiệu lực → bỏ qua êm. Decorator bọc ngoài cùng (sau rerank).
    """

    def __init__(self, base: KnowledgeBasePort, base_dir: str, tenant: str,
                 decay: float = 0.5, max_expand: int = 6) -> None:
        self.base = base
        self.decay = decay
        self.max_expand = max_expand
        self._status = _load_doc_status(base_dir, tenant)
        self._file_by_docid = _load_doc_ids(base_dir, tenant)
        self._relations = _load_doc_relations(base_dir, tenant)   # cạnh doc-level (sửa đổi/thay thế/hướng dẫn)
        # Chỉ mục (filename, 'điều 9') → chunk + chunk đại diện mỗi file (preamble/đầu tiên, cho doc-level).
        self._by_file_article: dict[tuple[str, str], list[Snippet]] = {}
        self._rep_by_file: dict[str, Snippet] = {}
        for src, text in _load_chunks(base_dir, tenant):
            fn = src.split("#", 1)[0]
            self._rep_by_file.setdefault(fn, Snippet(src, text, 0.0))   # chunk đầu (preamble: tên+trạng thái VB)
            if "#" not in src or not _is_in_force(self._status.get(fn, "in_force")):
                continue
            key = article_key(src.split("#", 1)[1])
            if key:
                self._by_file_article.setdefault((fn, key.lower()), []).append(Snippet(src, text, 0.0))

    def _resolve_file(self, doc_ref: str | None, hit_file: str) -> str | None:
        """doc_ref → filename đích. 'self'/None → cùng file; số hiệu → tra map; không khớp → None."""
        if doc_ref in (None, "self"):
            return hit_file
        return self._file_by_docid.get(doc_ref.upper())

    def retrieve(self, query: str, top_k: int = 4) -> list[Snippet]:
        hits = self.base.retrieve(query, top_k)
        seen = {(h.source, h.text) for h in hits}
        out = list(hits)
        budget = [self.max_expand]

        def _add(snip: Snippet, score: float) -> None:
            rk = (snip.source, snip.text)
            if rk not in seen and budget[0] > 0:
                seen.add(rk)
                out.append(Snippet(snip.source, snip.text, score))
                budget[0] -= 1

        # 1) Article-level: đi theo dẫn chiếu trong câu → đúng văn bản đích.
        for h in hits:
            if budget[0] <= 0:
                break
            hit_file = h.source.split("#", 1)[0]
            own = article_key(h.source.split("#", 1)[1]) if "#" in h.source else None
            for art, doc_ref in extract_article_refs(h.text):
                key = article_key(art)
                if not key:
                    continue
                target_file = self._resolve_file(doc_ref, hit_file)
                if not target_file or (target_file == hit_file and key.lower() == (own or "").lower()):
                    continue                                  # vắng / chính nó / khoản anh em
                for ref in self._by_file_article.get((target_file, key.lower()), []):
                    _add(ref, h.score * self.decay)

        # 2) Doc-level: kéo văn bản sửa đổi/thay thế/hướng dẫn liên quan (từ front-matter), nếu còn hiệu lực.
        for h in hits:
            if budget[0] <= 0:
                break
            for doc_id in self._relations.get(h.source.split("#", 1)[0], []):
                tf = self._file_by_docid.get(doc_id)
                if tf and _is_in_force(self._status.get(tf, "in_force")) and tf in self._rep_by_file:
                    _add(self._rep_by_file[tf], h.score * self.decay * self.decay)
        return out


class TemporalTypedRerankRetriever:
    """TT-SAR — Temporal Typed-edge Structure-Aware Reranking (kỹ thuật tự phát triển, opt-in).

    Mở rộng SAR (Structure-Aware Reranking, arXiv:2604.06173): lan truyền điểm dense theo cạnh đồ thị
    luật, NHƯNG dùng thông tin SAR gốc KHÔNG có — **loại quan hệ (typed)** + **hiệu lực theo thời điểm
    (temporal)** — vốn có sẵn trong front-matter của KB này (amends/replaced_by/guides + effective_date).

    Với mỗi ứng viên (theo doc_id của file), một seed điểm cao lan truyền bonus/penalty tới các văn bản
    liên quan:
      • `guides/amends/replaces` (+): VB hướng dẫn/sửa đổi/thay-thế củng cố → boost đích.
      • `replaced_by` (đặc biệt): KHÔNG boost bản CŨ; **đảo hướng** — boost bản THAY THẾ và **suppress**
        bản bị thay. Nhưng CỔNG THỜI GIAN: nếu câu hỏi hỏi ở mốc lịch sử TRƯỚC khi bản mới có hiệu lực
        (`as_of`), bản cũ khi đó CÒN đúng → KHÔNG suppress (tránh phá point-in-time).
    Dual log-degree penalty (SAR) chống hub cite bừa (out-degree) và super-hub bị trỏ tràn (in-degree).
    Residual Fusion: `S = S_dense_norm + β·adj·(1 − S_dense_norm)` cho bonus dương; suppression trừ thẳng.

    An toàn: thiếu doc_id/cạnh → passthrough (giữ thứ tự base). Không LLM, không train, tất định.
    """

    # Trọng số lan truyền theo loại quan hệ. Cạnh lưu 2 chiều (xem `_doc_edges`); `replaced_by` xử lý riêng.
    _W = {"guides": 0.5, "guided_by": 0.3, "amends": 0.4, "amended_by": 0.3, "replaces": 0.5}
    _W_REPLACED_BOOST = 0.6   # boost bản thay thế (theo cạnh nghịch replaces)
    _W_REPLACED_SUPPRESS = 0.6  # suppress bản bị thay khi bản mới đã hiệu lực tại as_of

    def __init__(self, base: KnowledgeBasePort, base_dir: str, tenant: str,
                 beta: float = 0.5, fetch_mult: int = 3) -> None:
        self.base = base
        self.beta = beta
        self.fetch_mult = fetch_mult
        by_docid, edges = _doc_edges(base_dir, tenant)
        self._file_by_docid = {d: f for d, f in _load_doc_ids(base_dir, tenant).items()}
        self._docid_by_file = {f: d for d, f in self._file_by_docid.items()}
        self._dates = _load_doc_dates(base_dir, tenant)
        self._adj: dict[str, list[tuple[str, str]]] = {}
        self._outdeg: Counter = Counter()
        self._indeg: Counter = Counter()
        for (s, r, t) in edges:
            self._adj.setdefault(s, []).append((r, t))
            self._outdeg[s] += 1
            self._indeg[t] += 1

    def _valid_target(self, docid: str, as_of: str | None) -> bool:
        """Đích còn hiệu lực tại as_of (nếu có mốc) — chỉ lan truyền BOOST tới VB đúng-thời-điểm.
        Target lạ (không trong KB) → True: boost tới doc_id vắng mặt vô hại (không có trong ứng viên)."""
        fn = self._file_by_docid.get(docid)
        if not fn or as_of is None:
            return True
        eff, exp = self._dates.get(fn, ("", ""))
        return _valid_at(eff, exp, as_of)

    def _replacement_active(self, docid: str, as_of: str | None) -> bool:
        """Bản THAY THẾ `docid` có đang hiệu lực (để suppress bản bị thay)? BẢO THỦ:
        - Target VẮNG KB → KHÔNG suppress (không xác nhận được bản mới có thật/hiệu lực; nhiều luật 2024/2025
          ingest rỗng → tránh dìm mất bản cũ là đáp án đúng duy nhất còn truy được). Kiểm TRƯỚC mọi nhánh.
        - as_of=None (hiện tại): bản mới CÓ trong KB → cho suppress bản cũ.
        - as_of có mốc: chỉ suppress nếu bản mới ĐÃ hiệu lực tại mốc đó (point-in-time giữ bản cũ đúng thời điểm)."""
        fn = self._file_by_docid.get(docid)
        if not fn:
            return False
        if as_of is None:
            return True
        eff, exp = self._dates.get(fn, ("", ""))
        return _valid_at(eff, exp, as_of)

    def _penalty(self, s: str, t: str) -> float:
        """Dual log-degree: hạ seed cite bừa (out-degree cao) và target super-hub (in-degree cao)."""
        return 1.0 / (math.log(self._outdeg.get(s, 0) + 1) + 1) / (math.log(self._indeg.get(t, 0) + 1) + 1)

    def retrieve(self, query: str, top_k: int = 4) -> list[Snippet]:
        fetch = max(top_k * self.fetch_mult, 12)
        cands = self.base.retrieve(query, fetch)
        if len(cands) <= 1 or not self._adj:
            return cands[:top_k]
        as_of = _extract_as_of(query)
        smax = max((c.score for c in cands), default=0.0)
        if smax <= 0:                    # điểm base ≤0 (vd cosine âm) → không chuẩn hóa nổi → passthrough an toàn
            return cands[:top_k]
        # Điểm dense chuẩn hóa cao nhất theo doc_id (một VB có thể có nhiều chunk trúng).
        best_norm: dict[str, float] = {}
        for c in cands:
            did = self._docid_by_file.get(c.source.split("#", 1)[0])
            if did:
                best_norm[did] = max(best_norm.get(did, 0.0), c.score / smax)
        adj: dict[str, float] = defaultdict(float)   # doc_id → điều chỉnh (dương boost, âm suppress)
        for did, snorm in best_norm.items():
            for (r, t) in self._adj.get(did, []):
                if r == "replaced_by":
                    # did bị thay bởi t. Chỉ đảo hướng khi bản mới t đang hiệu lực tại thời điểm hỏi.
                    if self._replacement_active(t, as_of):
                        adj[t] += self._W_REPLACED_BOOST * snorm * self._penalty(did, t)
                        adj[did] -= self._W_REPLACED_SUPPRESS * snorm
                    continue
                w = self._W.get(r, 0.0)
                if w and self._valid_target(t, as_of):
                    adj[t] += w * snorm * self._penalty(did, t)
        if not adj:
            return cands[:top_k]

        def _score(c: Snippet) -> float:
            did = self._docid_by_file.get(c.source.split("#", 1)[0])
            a = adj.get(did, 0.0) if did else 0.0
            snorm = c.score / smax
            if a >= 0:
                return snorm + self.beta * a * (1 - snorm)   # Residual Fusion (bonus)
            # suppression trừ thẳng NHƯNG floor ≥0: nhiều cạnh replaced_by cộng dồn không đẩy điểm âm
            # (âm sẽ đảo hạng dưới cả nhiễu + rò thang-điểm-âm sang elbow_cutoff của caller).
            return max(0.0, snorm + self.beta * a)

        ranked = sorted(cands, key=_score, reverse=True)
        return [Snippet(c.source, c.text, _score(c) * smax) for c in ranked[:top_k]]


def build_retriever(base_dir: str, tenant: str, embed_fn: EmbedFn | None = None,
                    reranker_llm: LLMPort | None = None, strategy: str = "auto",
                    rerank_fn: RerankFn | None = None, closure: bool = False,
                    in_force: bool = False, embed_store=None,
                    tt_sar: bool = False, domain_scoped: bool = False) -> KnowledgeBasePort:
    """strategy: auto (hybrid nếu có embed, else keyword) | keyword | hybrid | full.

    Thứ tự bọc: base → [domain_scoped lọc theo lĩnh vực] → [in_force lọc hiệu lực] → [rerank] →
    [tt_sar rerank đồ-thị] → [closure]. domain_scoped đặt SÁT base: thu hẹp vũ trụ ứng viên theo lĩnh vực
    câu hỏi TRƯỚC mọi lớp khác (chống cạnh-tranh-toàn-cục khi KB lớn — kb-expansion-plan trụ cột 1).
    tt_sar đặt SAU rerank để cross-encoder KHÔNG ghi đè tín hiệu đồ-thị (typed/temporal) của TT-SAR — nếu
    đặt trước, reranker re-score thuần theo liên quan và xóa suppression replaced_by. rerank_fn ưu tiên hơn reranker_llm.
    """
    if strategy == "keyword":
        base: KnowledgeBasePort = KeywordRetriever(base_dir, tenant)
    elif strategy == "full":
        return FullContextRetriever(base_dir, tenant)
    else:
        base = KeywordRetriever(base_dir, tenant)
        if embed_fn is not None:
            try:
                base = HybridRetriever(base, EmbeddingRetriever(base_dir, tenant, embed_fn, embed_store))  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001 — fallback an toàn khi embedding lỗi
                _log.warning("Embedding KB lỗi (tenant=%s) — hạ xuống keyword retriever.",
                             tenant, exc_info=True)
    if domain_scoped:
        from legalguard.adapters.outbound.domain_router import DomainScopedRetriever
        base = DomainScopedRetriever(base, base_dir, tenant)
    if in_force:
        base = InForceRetriever(base, base_dir, tenant)
    if rerank_fn is not None:
        base = CrossEncoderRerankRetriever(base, rerank_fn)
    elif reranker_llm is not None:
        base = RerankRetriever(base, reranker_llm)
    if tt_sar:                          # SAU rerank: giữ tín hiệu đồ-thị, không bị cross-encoder ghi đè
        base = TemporalTypedRerankRetriever(base, base_dir, tenant)
    if closure:
        base = CitationClosureRetriever(base, base_dir, tenant)
    return base


class OverlayRetriever:
    """KB tùy biến theo công ty: hợp nhất overlay riêng + KB quốc gia bằng Reciprocal Rank Fusion (RRF).

    Trước đây prepend overlay LÊN TRƯỚC (overlay luôn chiếm top_k) → lớp tactics moat (`premium_tactics.md`)
    đè điều luật thật ở /lookup Q&A pháp lý, phá citation accuracy (đo THẤY: 5-6/7 ca fail). RRF (theo RANK,
    không lệ thuộc thang điểm khác nhau của 2 retriever) để overlay chỉ nổi KHI thật sự liên quan hơn — câu
    hỏi luật thuần → điều luật nổi; câu hỏi tactics/clause → tactics vẫn nổi. Cùng cơ chế HybridRetriever.
    """

    def __init__(self, primary: KnowledgeBasePort, overlay: KnowledgeBasePort) -> None:
        self.primary = primary
        self.overlay = overlay

    def retrieve(self, query: str, top_k: int = 4) -> list[Snippet]:
        fetch = max(top_k * 2, 8)
        scores: dict[tuple, float] = {}
        snippets: dict[tuple, Snippet] = {}
        for lst in (self.overlay.retrieve(query, fetch), self.primary.retrieve(query, fetch)):
            for rank, s in enumerate(lst):
                key = (s.source, s.text)
                scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank + 1)   # RRF, k=60
                snippets[key] = s
        ranked = sorted(scores, key=lambda k: scores[k], reverse=True)
        return [snippets[k] for k in ranked[:top_k]]


class FileKnowledgeBaseProvider:
    """Implement KnowledgeBaseProvider: KB quốc gia (org.country) + overlay riêng công ty.

    Overlay đặt ở `<base_dir>/_orgs/<org_id>/*.md` (tùy chọn). SME dùng KB nền;
    enterprise thêm overlay riêng.
    """

    def __init__(self, base_dir: str, embed_fn: EmbedFn | None = None,
                 reranker_llm: LLMPort | None = None, strategy: str = "auto",
                 rerank_fn: RerankFn | None = None, closure: bool = False,
                 in_force: bool = False, embed_store=None, tt_sar: bool = False,
                 domain_scoped: bool = False) -> None:
        self.base_dir = base_dir
        self.embed_fn = embed_fn
        self.reranker_llm = reranker_llm
        self.strategy = strategy
        self.rerank_fn = rerank_fn
        self.closure = closure
        self.in_force = in_force
        self.tt_sar = tt_sar               # TT-SAR: rerank đồ-thị typed+temporal (opt-in)
        self.domain_scoped = domain_scoped  # định tuyến theo lĩnh vực (opt-in — chống cạnh-tranh-toàn-cục)
        self.embed_store = embed_store     # SqlEmbeddingStore (tùy chọn): embed bền → corpus lớn không re-embed
        self._cache: dict[tuple[str, str, bool, bool], KnowledgeBasePort] = {}

    def for_org(self, org: Organization, *, rerank: bool = True,
                overlay: bool = True) -> KnowledgeBasePort:
        # Cache theo (quốc gia, công ty, có-rerank, có-overlay): KB tĩnh → KHÔNG re-embed mỗi request.
        # rerank=False (path /analyze) bỏ cross-encoder → nhanh hơn, giảm tải/request khi đông user.
        # overlay=False (path /lookup) bỏ lớp tactics moat → Q&A dẫn luật không bị tactics đè điều luật.
        key = (org.country, org.id, rerank, overlay)
        if key not in self._cache:
            self._cache[key] = self._build(org, rerank=rerank, overlay=overlay)
        return self._cache[key]

    def changelog(self, doc_id: str, country: str) -> dict | None:
        return legal_changelog(self.base_dir, country, doc_id)

    def affected_files(self, doc_id: str, country: str) -> dict[str, dict]:
        return affected_doc_files(self.base_dir, country, doc_id)

    def graph(self, doc_id: str, country: str, depth: int = 1) -> dict | None:
        return legal_graph(self.base_dir, country, doc_id, depth)

    def latest(self, doc_id: str, country: str) -> dict | None:
        return latest_version(self.base_dir, country, doc_id)

    def amended_articles(self, doc_id: str, country: str) -> dict | None:
        return amended_articles(self.base_dir, country, doc_id)

    def recent(self, country: str, since: str) -> list[dict]:
        return recent_laws(self.base_dir, country, since)

    def _build(self, org: Organization, *, rerank: bool = True,
               overlay: bool = True) -> KnowledgeBasePort:
        # rerank=False → tắt cả cross-encoder lẫn LLM rerank (giữ hybrid RRF BM25+embedding).
        rerank_fn = self.rerank_fn if rerank else None
        reranker_llm = self.reranker_llm if rerank else None
        base = build_retriever(self.base_dir, org.country, self.embed_fn, reranker_llm,
                               self.strategy, rerank_fn, self.closure, self.in_force,
                               embed_store=self.embed_store, tt_sar=self.tt_sar,
                               domain_scoped=self.domain_scoped)
        overlay_dir = Path(self.base_dir) / "_orgs" / org.id
        if overlay and overlay_dir.exists() and any(overlay_dir.glob("*.md")):
            # Overlay riêng công ty: giữ keyword (nhỏ, khỏi embed) NHƯNG vẫn tôn trọng lọc hiệu lực
            # để không trả văn bản nội bộ đã hết hiệu lực.
            overlay = build_retriever(self.base_dir, f"_orgs/{org.id}",
                                      strategy="keyword", in_force=self.in_force)
            return OverlayRetriever(base, overlay)
        return base


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
