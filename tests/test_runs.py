from dataclasses import dataclass, field

from legalguard.domain.runs import execution_summary, runs_feed


def test_execution_summary_counts_by_tool():
    trace = [
        {"step": 1, "tool": "search_legal_knowledge", "arguments": {}, "observation": ""},
        {"step": 2, "tool": "flag_risk", "arguments": {}, "observation": ""},
        {"step": 3, "tool": "flag_risk", "arguments": {}, "observation": ""},
        {"step": 4, "tool": "propose_fallback", "arguments": {}, "observation": ""},
        {"step": 5, "tool": "request_human_review", "arguments": {}, "observation": ""},
    ]
    s = execution_summary(trace)
    assert s["total_tool_calls"] == 5
    assert s["searches"] == 1
    assert s["risks_flagged"] == 2
    assert s["fallbacks_proposed"] == 1
    assert s["human_review_requested"] == 1


def test_execution_summary_empty_safe():
    s = execution_summary([])
    assert s["total_tool_calls"] == 0
    assert s["risks_flagged"] == 0          # khóa luôn có, kể cả khi rỗng


def test_execution_summary_ignores_unknown_tool():
    s = execution_summary([{"tool": "mystery"}, {"tool": "flag_risk"}])
    assert s["total_tool_calls"] == 2       # vẫn đếm tổng
    assert s["risks_flagged"] == 1          # nhưng chỉ phân loại tool đã biết


@dataclass
class _Case:
    id: str
    created_at: str = "2026-06-30T00:00:00Z"
    tenant: str = "VN"
    needs_human_review: bool = False
    risks: list = field(default_factory=list)
    trace: list = field(default_factory=list)


def test_runs_feed_shape_and_counts():
    cases = [
        _Case(id="c1", risks=[{"clause": "A", "verified": True}, {"clause": "B", "verified": False}],
              trace=[{"tool": "search_legal_knowledge"}, {"tool": "flag_risk"}], needs_human_review=True),
        _Case(id="c2"),
    ]
    feed = runs_feed(cases)
    assert [f["case_id"] for f in feed] == ["c1", "c2"]
    assert feed[0]["tool_calls"] == 2 and feed[0]["risks"] == 2 and feed[0]["needs_human_review"] is True
    assert feed[0]["unverified"] == 1                # agent tự đánh dấu 1 rủi ro chưa xác minh
    assert feed[1]["tool_calls"] == 0 and feed[1]["risks"] == 0 and feed[1]["unverified"] == 0


def test_runs_feed_respects_limit_and_empty():
    assert runs_feed([], limit=10) == []
    assert len(runs_feed([_Case(id=str(i)) for i in range(5)], limit=3)) == 3
