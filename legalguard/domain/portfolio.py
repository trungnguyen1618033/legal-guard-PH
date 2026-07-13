"""Portfolio — danh mục hợp đồng HÀNH-ĐỘNG-ĐƯỢC (per-HĐ), sắp theo mức khẩn. THUẦN domain, không I/O.

KHÁC `/insights/dashboard` (số GỘP: đếm/severity/top-clause). Đây = mỗi HĐ 1 dòng: còn bao nhiêu must_fix
chưa xử · hạn gần nhất (từ obligations — tính năng A) · cần người duyệt → điểm khẩn để ưu tiên xử lý.
Gộp dữ liệu SẴN CÓ (cases + obligations), không gọi LLM. Dùng chung mọi kênh qua AnalysisService.
"""
from __future__ import annotations

from datetime import date


def build_portfolio(cases: list, obligations: list, today: date) -> list[dict]:
    """Mỗi case → 1 dòng {case_id, title, must_fix, illegal, needs_review, next_due, days_to_due, urgency}.
    Sắp giảm dần theo `urgency` (hạn càng gần + càng nhiều must_fix/illegal + cần duyệt → càng cao). THUẦN."""
    due_by_case: dict[str, list[str]] = {}
    for o in obligations:                        # chỉ nghĩa vụ pending CÓ ngày (từ tính năng A)
        if getattr(o, "status", "pending") == "pending" and getattr(o, "due_date", ""):
            due_by_case.setdefault(o.case_id, []).append(o.due_date)

    rows: list[dict] = []
    for c in cases:
        risks = getattr(c, "risks", None) or []
        must_fix = sum(1 for r in risks if r.get("priority") == "must_fix")
        illegal = sum(1 for r in risks if r.get("legal_status") == "illegal")
        dues = sorted(due_by_case.get(c.id, []))
        next_due = dues[0] if dues else ""
        days = (date.fromisoformat(next_due) - today).days if next_due else None
        urgency = must_fix * 8 + illegal * 10 + (5 if getattr(c, "needs_human_review", False) else 0)
        if days is not None:                     # hạn càng gần (kể cả quá hạn: days<0) → điểm càng cao
            urgency += max(0, 60 - min(days, 60))
        title = (getattr(c, "source_name", "") or (getattr(c, "contract_excerpt", "") or "")[:60]
                 or c.id)
        rows.append({"case_id": c.id, "title": title, "created_at": getattr(c, "created_at", ""),
                     "must_fix": must_fix, "illegal": illegal,
                     "needs_review": bool(getattr(c, "needs_human_review", False)),
                     "next_due": next_due, "days_to_due": days, "urgency": urgency})
    rows.sort(key=lambda r: r["urgency"], reverse=True)
    return rows
