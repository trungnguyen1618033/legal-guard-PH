from legalguard.adapters.outbound.knowledge_base import KeywordRetriever
from legalguard.domain.models import AgentContext
from legalguard.domain.tools import TOOL_SCHEMAS, execute_tool


def _props(tool_name: str) -> list[str]:
    fn = next(t["function"] for t in TOOL_SCHEMAS if t["function"]["name"] == tool_name)
    return list(fn["parameters"]["properties"])


def _ctx() -> AgentContext:
    return AgentContext(retriever=KeywordRetriever("knowledge_base", "VN"))


def test_flag_risk_records_structured_risk():
    ctx = _ctx()
    out = execute_tool("flag_risk", {"clause": "Trọng tài", "risk": "Bất lợi", "severity": "high"}, ctx)
    assert len(ctx.risks) == 1
    assert ctx.risks[0].severity == "high"
    assert "Trọng tài" in out


def test_propose_fallback_records():
    ctx = _ctx()
    execute_tool("propose_fallback", {"clause": "Trọng tài", "suggestion": "Đề xuất SIAC"}, ctx)
    assert ctx.fallbacks[0].suggestion == "Đề xuất SIAC"


def test_request_human_review_sets_flag():
    ctx = _ctx()
    execute_tool("request_human_review", {"reason": "rủi ro cao"}, ctx)
    assert ctx.needs_human_review is True
    assert ctx.review_reasons == ["rủi ro cao"]


def test_search_legal_knowledge_returns_text():
    ctx = _ctx()
    out = execute_tool("search_legal_knowledge", {"query": "trọng tài"}, ctx)
    assert "trọng tài" in out.lower()


def test_unknown_tool_is_handled():
    assert "không tồn tại" in execute_tool("no_such_tool", {}, _ctx()).lower()


# ---- reason-then-format: `reasoning` đứng ĐẦU schema (model suy luận trước khi quyết) ----
def test_reasoning_field_is_first_in_decision_tools():
    assert _props("flag_risk")[0] == "reasoning"
    assert _props("propose_fallback")[0] == "reasoning"
    assert "reasoning" not in _props("flag_risk")[1:]   # không required, chỉ là gợi ý suy luận


def test_dispatch_tolerates_reasoning_field():
    # `reasoning` không phải required → có hay không, kết quả structured vẫn ghi nhận bình thường.
    ctx = _ctx()
    execute_tool("flag_risk", {"reasoning": "đẩy rủi ro về khách", "clause": "X", "risk": "Y",
                               "severity": "high"}, ctx)
    assert len(ctx.risks) == 1 and ctx.risks[0].severity == "high"


# ---- QA chất lượng output LLM ----
def test_flag_risk_drops_garbage_missing_fields():
    ctx = _ctx()
    execute_tool("flag_risk", {"clause": "", "risk": "", "severity": "high"}, ctx)
    assert ctx.risks == []                       # output thiếu → bỏ, không nhiễm kết quả


def test_flag_risk_coerces_invalid_severity():
    ctx = _ctx()
    execute_tool("flag_risk", {"clause": "X", "risk": "Y", "severity": "siêu cao"}, ctx)
    assert ctx.risks[0].severity == "medium"     # enum sai → ép hợp lệ


def test_propose_fallback_drops_incomplete():
    ctx = _ctx()
    execute_tool("propose_fallback", {"clause": "X", "suggestion": ""}, ctx)
    assert ctx.fallbacks == []


def test_tool_error_returns_observation_not_exception():
    # Retriever hỏng → agent nhận observation lỗi, KHÔNG sập cả vòng phân tích.
    class _Broken:
        def retrieve(self, query, top_k=4):
            raise RuntimeError("KB down")

    ctx = AgentContext(retriever=_Broken())
    out = execute_tool("search_legal_knowledge", {"query": "trọng tài"}, ctx)
    assert "Lỗi khi chạy tool" in out and "KB down" in out
