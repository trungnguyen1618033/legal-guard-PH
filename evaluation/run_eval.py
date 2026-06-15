"""Eval harness — đo chất lượng phát hiện rủi ro + groundedness trên bộ golden.

Chạy:  uv run python -m evaluation.run_eval
Mặc định dùng stub (offline). Có QWEN/GEMINI key → đo trên model thật.
"""
from __future__ import annotations

import json
from pathlib import Path

from legalguard.adapters.outbound.knowledge_base import build_retriever
from legalguard.config.container import build_service
from legalguard.config.settings import settings
from legalguard.domain.analysis import AnalysisService
from legalguard.domain.tenants import default_org

# Đồng nghĩa để khớp rủi ro phát hiện ↔ category kỳ vọng (song ngữ).
_SYN = {
    "arbitration": ["arbitration", "trọng tài", "beijing", "bắc kinh"],
    "payment": ["payment", "thanh toán", "t/t", "trả sau", "advance", "đặt cọc"],
    "inspection": ["inspection", "kiểm định", "destination", "cảng đến"],
}


def _matches(category: str, risk: dict) -> bool:
    text = f"{risk['clause']} {risk['risk']}".lower()
    return any(s in text for s in _SYN.get(category, [category]))


def _load_golden(golden_path: str | None = None) -> list[dict]:
    path = Path(golden_path) if golden_path else Path(__file__).parent / "golden.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _context_stats(strategy: str) -> dict:
    """Proxy chi phí: trung bình số chunk + ký tự KB nạp vào prompt cho mỗi case."""
    r = build_retriever(settings.knowledge_base_dir, "VN", strategy=strategy)
    cases = _load_golden()
    chunks = chars = 0
    for c in cases:
        hits = r.retrieve(c["contract"], top_k=4)
        chunks += len(hits)
        chars += sum(len(h.text) for h in hits)
    n = len(cases) or 1
    return {"avg_chunks": round(chunks / n, 1), "avg_chars": round(chars / n)}


def run_eval(service: AnalysisService | None = None, golden_path: str | None = None,
             lang: str = "en") -> dict:
    service = service or build_service()
    cases = _load_golden(golden_path)
    org = default_org("VN")

    tp = fp = fn = grounded = total_risks = 0
    for case in cases:
        risks = service.analyze(case["contract"], org, lang=lang).risks
        expected = set(case["expected"])
        matched = {c for c in expected if any(_matches(c, r) for r in risks)}
        tp += len(matched)
        fn += len(expected - matched)
        for r in risks:
            total_risks += 1
            if r.get("source"):
                grounded += 1
            if not any(_matches(c, r) for c in expected):
                fp += 1

    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "cases": len(cases),
        "precision": round(precision, 2),
        "recall": round(recall, 2),
        "f1": round(f1, 2),
        "groundedness": round(grounded / total_risks, 2) if total_risks else 1.0,
    }


def compare(strategies: tuple[str, ...] = ("keyword", "hybrid", "full")) -> dict:
    """A/B nhiều chiến lược retrieval trên cùng bộ golden.

    Lưu ý: chất lượng (precision/recall) chỉ KHÁC nhau khi chạy với LLM thật (đọc context).
    Ở stub, metric giống nhau — phần khác biệt thấy được offline là CHI PHÍ context (avg_chunks/chars).
    """
    out = {}
    for strat in strategies:
        metrics = run_eval(build_service(kb_strategy=strat))
        out[strat] = {**metrics, **_context_stats(strat)}
    return out


if __name__ == "__main__":
    table = compare()
    print(f"{'strategy':10} {'prec':>5} {'recall':>6} {'f1':>5} {'ground':>6} {'chunks':>7} {'chars':>6}")
    for strat, m in table.items():
        print(f"{strat:10} {m['precision']:>5} {m['recall']:>6} {m['f1']:>5} "
              f"{m['groundedness']:>6} {m['avg_chunks']:>7} {m['avg_chars']:>6}")
