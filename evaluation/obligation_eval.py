"""Eval TRÍCH NGHĨA VỤ & HẠN CHÓT (tính năng A, sau-ký) — golden có đáp án đã biết.

Đo: precision/recall BẮT nghĩa vụ (kind + keyword) + ĐỘ CHÍNH XÁC NGÀY (mốc tuyệt đối). Ca NDA (expected
rỗng) kiểm CHỐNG BỊA (extract ra nghĩa vụ = FP). `score_case`/`aggregate` THUẦN → test offline; CLI gọi
Qwen thật. Chạy (cần QWEN key): uv run python -m evaluation.obligation_eval → obligation_report.json.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

_GOLDEN = Path("evaluation/obligation_golden.json")
_REPORT = Path("evaluation/obligation_report.json")


def _text(o: dict) -> str:
    return " ".join(str(o.get(k, "")) for k in ("description", "source_clause", "rule")).lower()


def _matches(exp: dict, ext: dict) -> bool:
    """1 nghĩa vụ kỳ vọng khớp 1 nghĩa vụ trích: cùng kind (expected='other' = catch-all) + ≥1 keyword."""
    ek, xk = exp.get("kind", "other"), ext.get("kind", "other")
    if ek != "other" and ek != xk:
        return False
    text = _text(ext)
    kws = [k.lower() for k in exp.get("keywords", [])]
    return any(k in text for k in kws) if kws else True


def score_case(expected: list[dict], extracted: list[dict]) -> dict:
    """TP/FP/FN + date-correct cho 1 HĐ. Ghép greedy 1-1 (mỗi extracted dùng 1 lần). THUẦN."""
    used = [False] * len(extracted)
    tp = date_total = date_correct = 0
    for exp in expected:
        hit = None
        for i, ext in enumerate(extracted):
            if not used[i] and _matches(exp, ext):
                hit = i
                break
        if hit is not None:
            used[hit] = True
            tp += 1
            if exp.get("due_date"):                    # chỉ chấm ngày khi expected có mốc tuyệt đối
                date_total += 1
                if extracted[hit].get("due_date") == exp["due_date"]:
                    date_correct += 1
        else:
            if exp.get("due_date"):
                date_total += 1                        # bỏ sót nghĩa vụ có ngày = ngày cũng sai
    fn = len(expected) - tp
    fp = used.count(False)
    return {"tp": tp, "fp": fp, "fn": fn, "date_total": date_total, "date_correct": date_correct}


def aggregate(results: list[dict]) -> dict:
    tp = sum(r["tp"] for r in results)
    fp = sum(r["fp"] for r in results)
    fn = sum(r["fn"] for r in results)
    dt = sum(r["date_total"] for r in results)
    dc = sum(r["date_correct"] for r in results)
    prec = tp / (tp + fp) if (tp + fp) else 1.0
    rec = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3),
            "date_accuracy": round(dc / dt, 3) if dt else 1.0,
            "tp": tp, "fp": fp, "fn": fn, "date_total": dt, "date_correct": dc}


def main() -> None:  # pragma: no cover — cần Qwen key
    from legalguard.config.container import build_service
    from legalguard.domain.obligations import extract_obligations

    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))["cases"]
    svc = build_service()
    if not svc.reasoner.available:
        raise SystemExit("Cần QWEN_API_KEY để chạy obligation_eval (trích cần LLM thật).")
    results, per_case = [], []
    for c in golden:
        ce = date.fromisoformat(c["contract_end"]) if c.get("contract_end") else None
        extracted = extract_obligations(svc.reasoner, c["contract"], contract_end=ce)
        s = score_case(c.get("expected", []), extracted)
        results.append(s)
        per_case.append({"name": c["name"], **s, "n_extracted": len(extracted)})
        print(f"  {c['name']}: tp={s['tp']} fp={s['fp']} fn={s['fn']} date {s['date_correct']}/{s['date_total']}")
    agg = aggregate(results)
    report = {"aggregate": agg, "cases": per_case}
    _REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nĐỘ CHÍNH XÁC A (nghĩa vụ): precision={agg['precision']} recall={agg['recall']} "
          f"f1={agg['f1']} date_acc={agg['date_accuracy']} → {_REPORT}")


if __name__ == "__main__":  # pragma: no cover
    main()
