"""Gate memory_eval: golden recall PHẢI hoàn hảo (Recall@k=1 + cô lập org + chống nhiễu) — 2 backend. Offline."""
from __future__ import annotations

from evaluation.memory_eval import build_golden, evaluate, fake_embed
from legalguard.adapters.outbound.memory_store import InMemoryMemory
from legalguard.adapters.outbound.sql_memory_store import SqlMemory


def _seed(m, eps):  # noqa: ANN001
    for e in eps:
        m.remember(e)
    return m


def test_memory_eval_lexical_perfect():
    eps, qs = build_golden()
    r = evaluate(_seed(InMemoryMemory(), eps), qs)
    assert r["recall_at_k"] == 1.0 and r["mrr"] == 1.0
    assert r["org_isolation"] and r["noise_rejection"] and r["supersede_ok"]   # cô lập + chống nhiễu + bi-temporal


def test_memory_eval_semantic_perfect(tmp_path):
    eps, qs = build_golden()
    m = SqlMemory(f"sqlite:///{tmp_path / 'm.db'}", embed_fn=fake_embed)
    r = evaluate(_seed(m, eps), qs)
    assert r["recall_at_k"] == 1.0
    assert r["org_isolation"] and r["noise_rejection"] and r["supersede_ok"]   # + supersede (bỏ vị thế cũ)
