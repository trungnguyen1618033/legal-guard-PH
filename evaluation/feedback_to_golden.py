"""Đóng vòng học (living flywheel): feedback người dùng → ứng viên golden set + báo lỗ hổng KB.

Câu hỏi bị đánh ⚠️ Sai / ➖ Thiếu = chỗ cơ sở tri thức còn yếu. Biến chúng thành:
- `gap_report`: thống kê + danh sách câu hỏi yếu (để đội pháp lý biết chỗ cần bổ sung KB).
- `feedback_to_candidates`: ứng viên golden set (query + expected RỖNG cho luật sư điền) → merge vào
  `legal_golden.json` → eval đo được cải thiện. Đây là vòng usage → feedback → golden → đo → vá.

Chạy:  uv run python -m evaluation.feedback_to_golden --org default --out evaluation/golden_candidates.json
Hàm `feedback_to_candidates`/`gap_report` thuần (test offline). CLI đọc feedback từ DB.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

_WEAK = ("wrong", "incomplete")          # tín hiệu KB yếu (helpful không cần đưa vào golden)


def _slug(text: str, i: int) -> str:
    keep = "".join(c if c.isalnum() or c == " " else " " for c in text.lower())
    return ("fb-" + "-".join(keep.split()[:5])) or f"fb-{i}"


def feedback_to_candidates(feedbacks: list) -> list[dict]:
    """Feedback ⚠️/➖ → ứng viên golden set (khử trùng theo câu hỏi; expected để rỗng cho luật sư điền)."""
    out: list[dict] = []
    seen: set[str] = set()
    for i, f in enumerate(feedbacks):
        if f.rating not in _WEAK or not (f.ref or "").strip():
            continue
        key = f.ref.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        note = f.rating + (f": {f.note}" if f.note else "")
        out.append({"id": _slug(f.ref, i), "query": f.ref.strip(),
                    "expected": [], "type": "from_feedback", "note": note})
    return out


def gap_report(feedbacks: list) -> dict:
    """Tổng quan tín hiệu: số theo rating + danh sách câu hỏi yếu (KB cần bổ sung)."""
    by_rating = Counter(f.rating for f in feedbacks)
    weak = list(dict.fromkeys(f.ref.strip() for f in feedbacks
                              if f.rating in _WEAK and (f.ref or "").strip()))
    return {"total": len(feedbacks), "by_rating": dict(by_rating), "weak_queries": weak}


def main() -> None:
    ap = argparse.ArgumentParser(description="Feedback → golden candidates + KB-gap report")
    ap.add_argument("--org", default="default")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--out", default="evaluation/golden_candidates.json")
    args = ap.parse_args()

    from legalguard.adapters.outbound.sql_feedback_repository import SqlAlchemyFeedbackRepository
    from legalguard.config.settings import settings

    feedbacks = SqlAlchemyFeedbackRepository(settings.database_url).list_by_org(args.org, args.limit)
    report = gap_report(feedbacks)
    candidates = feedback_to_candidates(feedbacks)
    print(f"Feedback (org={args.org}): {report['total']} | theo rating: {report['by_rating']}")
    print(f"Câu hỏi yếu (KB cần bổ sung): {len(report['weak_queries'])}")
    for q in report["weak_queries"][:20]:
        print(f"  • {q}")
    if candidates:
        Path(args.out).write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nĐã ghi {len(candidates)} ứng viên golden vào {args.out} — luật sư điền `expected` rồi "
              f"merge vào legal_golden.json.")
    else:
        print("\nChưa có feedback ⚠️/➖ để tạo golden.")


if __name__ == "__main__":
    main()
