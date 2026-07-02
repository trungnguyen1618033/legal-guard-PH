"""Eval RETRIEVAL trên BENCHMARK CÔNG KHAI — Zalo AI Legal Text Retrieval 2021 (MIT).

Khác `legal_eval.py` (đo trên golden 54 ca TỰ TẠO) — đây đo trên bộ đề NGOÀI, công khai, được cộng
đồng dùng chung: 61.425 điều luật + 793 truy vấn có nhãn liên quan (qrels). Cho con số "đo trên
benchmark công khai" để công bố ở /trust + pitch, thay vì chỉ tự chấm.

Đo thành phần LEXICAL (BM25 Okapi) của retriever — cùng tokenizer (`_tokenize`) + tham số k1=1.5/b=0.75
với `KeywordRetriever` trong sản phẩm, nên số phản ánh đúng lõi lexical. (Hybrid embedding trên 61k điều
tốn API + thời gian → để --hybrid opt-in sau; lexical chạy offline, tất định, miễn phí.)

Dùng inverted-index (postings) thay vì quét O(N)/query như KeywordRetriever (thiết kế cho KB nhỏ) —
61k điều × 793 query cần index để chạy trong giây.

Nguồn: https://huggingface.co/datasets/GreenNode/zalo-ai-legal-text-retrieval-vn (MIT)
Chạy (offline sau khi tải, KHÔNG cần API key): uv run python -m evaluation.zalo_ltr_eval
→ ghi evaluation/zalo_ltr_report.json
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from legalguard.adapters.outbound.knowledge_base import _tokenize

_REPO = "GreenNode/zalo-ai-legal-text-retrieval-vn"
_REPORT = Path("evaluation/zalo_ltr_report.json")
_K1, _B = 1.5, 0.75   # khớp KeywordRetriever


def _load_jsonl(fname: str) -> list[dict]:
    from huggingface_hub import hf_hub_download
    p = hf_hub_download(_REPO, fname, repo_type="dataset")
    with open(p, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


class _BM25Index:
    """BM25 Okapi với inverted index — cùng công thức KeywordRetriever, mở rộng cho corpus lớn."""

    def __init__(self, docs: list[tuple[str, str]]) -> None:  # [(doc_id, text)]
        self.ids = [d for d, _ in docs]
        toks = [_tokenize(t) for _, t in docs]
        self.dl = [len(t) for t in toks]
        self.avgdl = (sum(self.dl) / len(self.dl)) if toks else 0.0
        self.tf: list[Counter] = [Counter(t) for t in toks]
        self.postings: dict[str, list[int]] = defaultdict(list)  # term → [doc idx]
        for i, tset in enumerate(map(set, toks)):
            for t in tset:
                self.postings[t].append(i)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}

    def search(self, query: str, top_k: int) -> list[str]:
        q = [t for t in _tokenize(query) if t in self.idf]
        if not q:
            return []
        scores: dict[int, float] = defaultdict(float)
        for t in q:
            idf = self.idf[t]
            for i in self.postings[t]:               # chỉ doc CÓ term → nhanh
                f = self.tf[i][t]
                denom = f + _K1 * (1 - _B + _B * self.dl[i] / (self.avgdl or 1))
                scores[i] += idf * f * (_K1 + 1) / denom
        top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        return [self.ids[i] for i, _ in top]


def metrics(ranked: list[str], relevant: set[str], k: int = 10) -> tuple[float, float, float]:
    """Trả (recall@k, reciprocal_rank@k, hit@1) cho 1 truy vấn."""
    topk = ranked[:k]
    hits = sum(1 for d in topk if d in relevant)
    recall = hits / len(relevant) if relevant else 0.0
    rr = next((1.0 / (i + 1) for i, d in enumerate(topk) if d in relevant), 0.0)
    hit1 = 1.0 if ranked[:1] and ranked[0] in relevant else 0.0
    return recall, rr, hit1


def run(top_k: int = 10, write: bool = True) -> dict:
    corpus = _load_jsonl("corpus.jsonl")
    qrels_rows = _load_jsonl("qrels/test.jsonl")
    queries = {q["_id"]: q["text"] for q in _load_jsonl("queries.jsonl")}

    rel: dict[str, set[str]] = defaultdict(set)
    for r in qrels_rows:
        if int(r.get("score", 0)) > 0:
            rel[r["query-id"]].add(r["corpus-id"])
    test_qids = [qid for qid in rel if qid in queries]

    print(f"Corpus {len(corpus)} điều · {len(test_qids)} truy vấn test · index BM25…")
    idx = _BM25Index([(c["_id"], f"{c.get('title', '')} {c.get('text', '')}") for c in corpus])

    rec = rr = hit1 = 0.0
    for qid in test_qids:
        ranked = idx.search(queries[qid], top_k)
        r, m, h = metrics(ranked, rel[qid], top_k)
        rec += r
        rr += m
        hit1 += h
    n = len(test_qids)
    report = {"benchmark": "Zalo AI Legal Text Retrieval 2021 (MIT)", "retriever": "BM25 lexical (Okapi k1=1.5 b=0.75)",
              "corpus_size": len(corpus), "test_queries": n, "top_k": top_k,
              f"recall@{top_k}": round(rec / n, 4), f"mrr@{top_k}": round(rr / n, 4),
              "hit@1": round(hit1 / n, 4)}
    print(f"\n=== Zalo LTR (BM25 lexical) — {n} truy vấn ===")
    print(f"  Recall@{top_k} = {report[f'recall@{top_k}']:.1%}")
    print(f"  MRR@{top_k}    = {report[f'mrr@{top_k}']:.4f}")
    print(f"  Hit@1      = {report['hit@1']:.1%}")
    if write:
        _REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Đã ghi {_REPORT}")
    return report


if __name__ == "__main__":
    run()
