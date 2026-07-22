"""Eval LIVE chất lượng recall bộ nhớ agent trên embedding THẬT (không phải fake topic-vector).

BỔ TRỢ `memory_eval.py`: bản offline (fake_embed) đo LOGIC recall (ranking/cô-lập/nhiễu/bi-temporal) tất
định — làm cổng regression. Bản LIVE này đo CHẤT LƯỢNG SEMANTIC THẬT của embedder → chứng minh 'semantic
agentic memory' hoạt động trên embedding thực + cho phép **A/B đổi embedding model TRƯỚC khi swap**.

Embedder PLUGGABLE (MemoryPort nhận `embed_fn`): đổi model = đổi `--model` (trong Qwen) → đo lại Recall@k/
MRR + noise-floor. Opt-in QWEN_API_KEY (như ragas_eval); thiếu key → skip (không làm đỏ CI).

Chạy:
  uv run python -m evaluation.memory_live_eval                       # model mặc định (settings.qwen_embed_model)
  uv run python -m evaluation.memory_live_eval --model text-embedding-v3  # A/B model khác trước khi swap
  uv run python -m evaluation.memory_live_eval -k 5

LƯU Ý gate: cổng ROBUST (độc lập embedder hoặc boost hằng-số) = org-isolation · chống-nhiễu (KIỂM _MIN_SIM
trên model này!) · supersede · boost · consolidation. **recency = ADVISORY** (tie-break chỉ khi điểm BẰNG
nhau → embedding thật hiếm khi bằng tuyệt đối → phụ thuộc model, KHÔNG gate). Đổi model có dim khác → cột
VECTOR phải fresh; noise-floor `_MIN_SIM` PHẢI calibrate lại (evaluation/memory_threshold_calibrate.py).
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from evaluation.memory_eval import build_golden, evaluate

# Cổng gate cho LIVE: độc lập embedder (org/supersede/consolidation lọc bằng cột, không embed) HOẶC boost
# hằng-số (+_CP_BOOST luôn nâng cùng-đối-tác trên MỌI model) HOẶC kiểm ngưỡng (noise → _MIN_SIM đúng chưa).
_LIVE_GATES = ("org_isolation", "noise_rejection", "supersede_ok", "boost_ok", "consolidation_ok")


def run(embed_fn, model_name: str, k: int = 3) -> dict:  # noqa: ANN001
    """Seed SqlMemory (sqlite tạm) bằng embedding THẬT của `embed_fn` → evaluate trên golden chung."""
    from legalguard.adapters.outbound.sql_memory_store import SqlMemory

    eps, qs = build_golden()
    with tempfile.TemporaryDirectory() as d:
        m = SqlMemory(f"sqlite:///{Path(d) / 'live.db'}", embed_fn=embed_fn)
        for e in eps:
            m.remember(e)
        r = evaluate(m, qs, k=k)

    gate = all(r[g] for g in _LIVE_GATES)
    print(f"\n=== memory LIVE eval · embedder = {model_name} (k={k}) ===")
    print(f"  Recall@{k} = {r['recall_at_k']:.0%} | MRR = {r['mrr']:.3f}")
    print("  cổng gate (robust):  " + " | ".join(f"{g}={'✅' if r[g] else '❌'}" for g in _LIVE_GATES))
    print(f"  recency (advisory) = {'✅' if r['recency_ok'] else '⚠️ (tie-break — embedding thật hiếm bằng tuyệt đối)'}")
    for row in r["details"]:
        tag = "✅" if row.get("pass") else "❌"
        got = row["got"] if isinstance(row["got"], list) else str(row["got"])[:70]
        print(f"   [{tag}] {row['name']}: {got}")
    print(f"\n  → GATE ROBUST: {'✅ PASS' if gate else '❌ FAIL'}  (Recall@{k}={r['recall_at_k']:.0%})")
    r["gate_pass"] = gate
    r["embedder"] = model_name
    return r


def _qwen_embedder(model: str | None):
    """Dựng embedder Qwen từ settings; `model` override embed_model (A/B). Trả (embed_fn, tên) hoặc (None, lý do)."""
    from legalguard.adapters.outbound.qwen import QwenAdapter
    from legalguard.config.settings import settings

    embed_model = model or settings.qwen_embed_model
    llm = QwenAdapter(settings.qwen_api_key, settings.qwen_base_url, settings.qwen_model,
                      embed_model=embed_model)
    if not llm.available:
        return None, "thiếu QWEN_API_KEY"
    return llm.embed, f"qwen:{embed_model}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="embed_model Qwen để A/B (mặc định settings.qwen_embed_model)")
    ap.add_argument("-k", type=int, default=3)
    args = ap.parse_args()

    embed_fn, name = _qwen_embedder(args.model)
    if embed_fn is None:
        print(f"SKIP memory LIVE eval — {name} (cần embedding thật; offline dùng memory_eval).")
        return
    run(embed_fn, name, k=args.k)


if __name__ == "__main__":
    main()
