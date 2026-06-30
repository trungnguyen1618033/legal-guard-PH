"""Evidence AI-Native: tóm tắt việc agent ĐÃ LÀM (cho track Autopilot Agent — giám khảo cần NHÌN THẤY
agent gọi tool & ra quyết định, không chỉ kết quả). Thuần, không phụ thuộc adapter — test offline.
"""
from collections import Counter

# Map tên tool (agent.py/tools.py) → khóa hiển thị trong execution_summary.
_TOOL_KEY = {
    "search_legal_knowledge": "searches",
    "flag_risk": "risks_flagged",
    "propose_fallback": "fallbacks_proposed",
    "request_human_review": "human_review_requested",
}


def execution_summary(trace: list[dict]) -> dict:
    """Đếm tool-call theo loại từ trace 1 lần phân tích → 'agent đã suy nghĩ bao nhiêu bước'.

    `trace` = list[{step, tool, arguments, observation}] (AnalysisResult.trace). An toàn với list rỗng."""
    counts = Counter((s.get("tool") or "") for s in (trace or []))
    summary = {"total_tool_calls": sum(counts.values())}
    for tool, key in _TOOL_KEY.items():
        summary[key] = counts.get(tool, 0)
    return summary


def runs_feed(cases: list, limit: int = 50) -> list[dict]:
    """Feed hoạt động agent: mỗi case → {case_id, created_at, tenant, tool_calls, risks, needs_human_review}.
    Cô lập org do caller truyền `cases` đã lọc theo org. Bằng chứng agent chạy liên tục (cho giám khảo)."""
    feed = []
    for c in (cases or [])[:limit]:
        trace = getattr(c, "trace", None) or []
        risks = getattr(c, "risks", None) or []
        # `unverified` = số rủi ro agent TỰ đánh dấu chưa xác minh (self-critique verify_risks) →
        # bằng chứng agent tự soi lại việc của mình, không chỉ phun ra rủi ro.
        unverified = sum(1 for r in risks if r.get("verified") is False)
        feed.append({
            "case_id": getattr(c, "id", ""),
            "created_at": getattr(c, "created_at", ""),
            "tenant": getattr(c, "tenant", ""),
            "tool_calls": execution_summary(trace)["total_tool_calls"],
            "risks": len(risks),
            "unverified": unverified,
            "needs_human_review": bool(getattr(c, "needs_human_review", False)),
        })
    return feed
