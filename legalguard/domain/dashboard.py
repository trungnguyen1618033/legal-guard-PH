"""System-of-record dashboard — tổng hợp hoạt động pháp lý của một công ty (moat: switching cost).

Càng dùng, dữ liệu tích trong hệ thống càng nhiều → khó rời. Dashboard biến đống case/feedback/outcome
rời rạc thành bức tranh: đã rà soát bao nhiêu HĐ, rủi ro hay gặp nhất, tín hiệu phản hồi, tỉ lệ thắng
chiến thuật. THUẦN (offline-testable): nhận list đã lấy từ repo → trả dict aggregate.
"""
from __future__ import annotations

from collections import Counter


def build_dashboard(cases: list, feedbacks: list, win_rates: dict | None = None,
                    top_n: int = 5) -> dict:
    """Tổng hợp số liệu của 1 org từ cases (AnalysisCase) + feedbacks (Feedback) + win_rates (tactic→stat).

    Không phụ thuộc thứ tự; an toàn với list rỗng. Các con số dùng cho trang tổng quan / báo cáo khách."""
    risk_sev: Counter = Counter()
    clause_freq: Counter = Counter()
    n_review = 0
    total_risks = 0
    for c in cases:
        if getattr(c, "needs_human_review", False):
            n_review += 1
        for r in getattr(c, "risks", None) or []:
            total_risks += 1
            risk_sev[r.get("severity", "medium")] += 1
            if r.get("clause"):
                clause_freq[r["clause"].strip()] += 1

    fb_rating: Counter = Counter(f.rating for f in feedbacks)
    weak = len({f.ref.strip().lower() for f in feedbacks
                if f.rating in ("wrong", "incomplete") and (f.ref or "").strip()})

    wr = win_rates or {}
    top_tactics = sorted(
        ((clause, s.get("rate", 0.0), s.get("total", 0)) for clause, s in wr.items()),
        key=lambda x: (x[1], x[2]), reverse=True)[:top_n]

    return {
        "cases": {"total": len(cases), "needs_review": n_review,
                  "total_risks": total_risks, "risk_by_severity": dict(risk_sev)},
        "top_risky_clauses": [{"clause": c, "count": n} for c, n in clause_freq.most_common(top_n)],
        "feedback": {"total": len(feedbacks), "by_rating": dict(fb_rating), "kb_gaps": weak},
        "top_tactics": [{"clause": c, "win_rate": rate, "samples": n} for c, rate, n in top_tactics],
    }
