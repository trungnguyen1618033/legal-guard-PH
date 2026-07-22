"""Gate memory_eval: golden recall PHẢI hoàn hảo (Recall@k=1 + 7 cổng boolean) — 2 backend. Offline."""
from __future__ import annotations

from evaluation.memory_eval import build_golden, evaluate, fake_embed
from legalguard.adapters.outbound.memory_store import InMemoryMemory
from legalguard.adapters.outbound.sql_memory_store import SqlMemory

# 7 cổng chất lượng PHẢI True (cô lập org · chống nhiễu · bi-temporal supersede · provenance/history ·
# boost cùng-đối-tác · recency tie-break · consolidation vị-thế-hiện-tại).
_GATES = ("org_isolation", "noise_rejection", "supersede_ok", "history_ok",
          "boost_ok", "recency_ok", "consolidation_ok")


def _seed(m, eps):  # noqa: ANN001
    for e in eps:
        m.remember(e)
    return m


def test_memory_eval_lexical_perfect():
    eps, qs = build_golden()
    r = evaluate(_seed(InMemoryMemory(), eps), qs)
    assert r["recall_at_k"] == 1.0 and r["mrr"] == 1.0
    assert all(r[g] for g in _GATES), {g: r[g] for g in _GATES}


def test_memory_eval_semantic_perfect(tmp_path):
    eps, qs = build_golden()
    m = SqlMemory(f"sqlite:///{tmp_path / 'm.db'}", embed_fn=fake_embed)
    r = evaluate(_seed(m, eps), qs)
    assert r["recall_at_k"] == 1.0
    assert all(r[g] for g in _GATES), {g: r[g] for g in _GATES}


def test_memory_live_eval_harness_offline():
    """Harness LIVE (embedder pluggable) chạy được OFFLINE với fake_embed → gate_pass (không cần QWEN key).
    Bảo vệ chính code harness; đo trên embedding THẬT là chạy thủ công `python -m evaluation.memory_live_eval`."""
    from evaluation.memory_live_eval import run
    r = run(fake_embed, "fake", k=3)
    assert r["gate_pass"] is True and r["recall_at_k"] == 1.0 and r["embedder"] == "fake"
