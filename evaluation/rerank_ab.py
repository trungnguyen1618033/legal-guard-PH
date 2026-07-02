"""A/B RERANKER trên benchmark công khai Zalo LTR — đo LIFT của rerank so với BM25 first-stage.

Quy trình 2 tầng (giống production): BM25 lấy top-N ứng viên → reranker xếp lại → đo MRR@10/Recall@10.
So baseline (BM25 thuần) với từng reranker để biết rerank ĐÁNG bao nhiêu điểm trên bộ đề ngoài.

Reranker CẮM-ĐƯỢC (--reranker):
  qwen3-api                → DashScope qwen3-rerank (PRODUCTION hiện tại; cần QWEN_API_KEY; chạy NGAY)
  hf:AITeamVN/Vietnamese_Reranker  → cross-encoder self-host (cần GPU + sentence-transformers; ứng viên vượt trần)
  hf:Qwen/Qwen3-Reranker-4B        → (cần GPU)
Chạy A/B đủ khi có GPU (xem docs/internal/reranker-ab-deploy.md để dựng GPU Alibaba theo kinh phí).

Chạy nhanh (subset, API arm):  uv run python -m evaluation.rerank_ab --reranker qwen3-api --limit 40
Chạy đầy:                       uv run python -m evaluation.rerank_ab --reranker qwen3-api
→ ghi evaluation/rerank_ab_report.json
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from evaluation.zalo_ltr_eval import _BM25Index, _load_jsonl, metrics

_REPORT = Path("evaluation/rerank_ab_report.json")


def _make_reranker(spec: str):
    """Trả hàm rerank(query, docs)->list[float] (điểm theo thứ tự docs). API hoặc HF cross-encoder."""
    if spec == "qwen3-api":
        from legalguard.adapters.outbound.qwen import QwenAdapter
        from legalguard.config.settings import settings as cfg
        adapter = QwenAdapter(cfg.qwen_api_key, cfg.qwen_base_url, cfg.qwen_model,
                              rerank_model=cfg.qwen_rerank_model)
        if not adapter.available:
            raise SystemExit("qwen3-api cần QWEN_API_KEY.")
        return lambda q, docs: adapter.rerank(q, docs) or [0.0] * len(docs)
    if spec.startswith("hf:"):
        model = spec[3:]
        from sentence_transformers import CrossEncoder   # cần GPU + cài sentence-transformers
        ce = CrossEncoder(model, max_length=512)
        return lambda q, docs: list(ce.predict([[q, d] for d in docs]))
    raise SystemExit(f"reranker không hỗ trợ: {spec}")


def run(reranker: str, fetch_n: int = 50, top_k: int = 10, limit: int | None = None,
        write: bool = True) -> dict:
    corpus = _load_jsonl("corpus.jsonl")
    queries = {q["_id"]: q["text"] for q in _load_jsonl("queries.jsonl")}
    rel: dict[str, set[str]] = defaultdict(set)
    for r in _load_jsonl("qrels/test.jsonl"):
        if int(r.get("score", 0)) > 0:
            rel[r["query-id"]].add(r["corpus-id"])
    qids = [q for q in rel if q in queries]
    if limit:
        qids = qids[:limit]

    text = {c["_id"]: f"{c.get('title', '')} {c.get('text', '')}" for c in corpus}
    print(f"BM25 index {len(corpus)} điều · {len(qids)} query · fetch top-{fetch_n} → rerank [{reranker}]…")
    idx = _BM25Index([(cid, t) for cid, t in text.items()])
    rerank_fn = _make_reranker(reranker)

    base = {"recall": 0.0, "rr": 0.0}
    rr_agg = {"recall": 0.0, "rr": 0.0}
    for n, qid in enumerate(qids, 1):
        cand = idx.search(queries[qid], fetch_n)          # tầng 1: BM25 top-N
        if not cand:
            continue
        br, bm, _ = metrics(cand, rel[qid], top_k)         # baseline: thứ tự BM25
        base["recall"] += br
        base["rr"] += bm
        # cắt mỗi doc (điều luật đầy đủ có thể vượt giới hạn token API) — giống chunk trong production
        scores = rerank_fn(queries[qid], [text[c][:800] for c in cand])   # tầng 2: rerank
        reranked = [c for c, _ in sorted(zip(cand, scores), key=lambda x: x[1], reverse=True)]
        rr_, rm, _ = metrics(reranked, rel[qid], top_k)
        rr_agg["recall"] += rr_
        rr_agg["rr"] += rm
        if n % 20 == 0:
            print(f"  {n}/{len(qids)}…")
    n = len(qids)
    rep = {"benchmark": "Zalo LTR 2021 (MIT)", "reranker": reranker, "fetch_n": fetch_n,
           "top_k": top_k, "queries": n,
           "bm25_baseline": {f"recall@{top_k}": round(base["recall"] / n, 4), f"mrr@{top_k}": round(base["rr"] / n, 4)},
           "reranked": {f"recall@{top_k}": round(rr_agg["recall"] / n, 4), f"mrr@{top_k}": round(rr_agg["rr"] / n, 4)},
           "mrr_lift": round((rr_agg["rr"] - base["rr"]) / n, 4)}
    print(f"\n=== A/B [{reranker}] trên {n} query (fetch {fetch_n}) ===")
    print(f"  BM25 baseline : Recall@{top_k}={rep['bm25_baseline'][f'recall@{top_k}']:.1%}  MRR@{top_k}={rep['bm25_baseline'][f'mrr@{top_k}']:.4f}")
    print(f"  + rerank      : Recall@{top_k}={rep['reranked'][f'recall@{top_k}']:.1%}  MRR@{top_k}={rep['reranked'][f'mrr@{top_k}']:.4f}")
    print(f"  MRR lift      : {rep['mrr_lift']:+.4f}")
    if write:
        _REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Đã ghi {_REPORT}")
    return rep


def main() -> None:
    ap = argparse.ArgumentParser(description="A/B reranker trên Zalo LTR")
    ap.add_argument("--reranker", default="qwen3-api", help="qwen3-api | hf:<model>")
    ap.add_argument("--fetch-n", type=int, default=50)
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--limit", type=int, default=None, help="giới hạn số query (smoke test)")
    args = ap.parse_args()
    run(args.reranker, args.fetch_n, args.top_k, args.limit)


if __name__ == "__main__":
    main()
