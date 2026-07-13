from legalguard.adapters.outbound.knowledge_base import KeywordRetriever
from legalguard.adapters.outbound.qwen import QwenAdapter
from legalguard.domain.agent import run_agent
from legalguard.domain.models import AgentContext


def _stub_llm() -> QwenAdapter:
    # Không API key → chế độ stub (mô phỏng agent có tool-calling).
    return QwenAdapter(api_key="", base_url="http://x", model="qwen-plus")


def _ctx() -> AgentContext:
    return AgentContext(retriever=KeywordRetriever("knowledge_base", "VN"))


def test_agent_produces_structured_risks_and_trace(sample_contract):
    ctx = _ctx()
    run = run_agent(sample_contract, "Việt Nam", _stub_llm(), ctx)
    assert len(ctx.risks) == 3
    tools_used = [s.tool for s in run.trace]
    assert "search_legal_knowledge" in tools_used
    assert tools_used.count("flag_risk") == 3


def test_agent_proposes_fallback_with_english_reply(sample_contract):
    ctx = _ctx()
    run_agent(sample_contract, "Việt Nam", _stub_llm(), ctx)
    # Lõi sản phẩm: mỗi rủi ro có fallback + câu đàm phán tiếng Anh sẵn dùng.
    assert len(ctx.fallbacks) == 3
    assert all(f.suggestion and f.english_reply for f in ctx.fallbacks)


def test_agent_grounds_risks_with_source(sample_contract):
    ctx = _ctx()
    run_agent(sample_contract, "Việt Nam", _stub_llm(), ctx)
    # Grounding: mỗi rủi ro gắn nguồn KB (citation) + evidence trích từ hợp đồng.
    assert all(r.source for r in ctx.risks)
    assert all(r.evidence and r.evidence.lower() in sample_contract.lower() for r in ctx.risks)
    assert all(f.source for f in ctx.fallbacks)


def test_agent_flags_human_review_for_high_severity(sample_contract):
    ctx = _ctx()
    run_agent(sample_contract, "Việt Nam", _stub_llm(), ctx)
    assert ctx.needs_human_review is True


def test_agent_terminates_with_final_message(sample_contract):
    ctx = _ctx()
    run = run_agent(sample_contract, "Việt Nam", _stub_llm(), ctx)
    assert run.final_message
    assert run.iterations <= 6


def test_high_severity_always_requires_human_review():
    # Lời hứa sản phẩm: rủi ro HIGH luôn cần duyệt — kể cả khi LLM "quên" gọi
    # request_human_review (đã xảy ra với LLM thật khi cạn iterations).
    from legalguard.adapters.outbound.knowledge_base import FileKnowledgeBaseProvider
    from legalguard.domain.analysis import AnalysisService
    from legalguard.domain.models import ChatTurn, ToolCall
    from legalguard.domain.tenants import default_org

    contract = "Tranh chấp giải quyết bằng trọng tài tại Bắc Kinh."

    class _ForgetfulLLM:                       # flag HIGH nhưng không gọi request_human_review
        available = False

        def __init__(self):
            self.done = False

        def chat(self, messages, tools=None):
            if self.done or tools is None:
                return ChatTurn(content="chiến lược")
            self.done = True
            return ChatTurn(tool_calls=[ToolCall(id="t1", name="flag_risk", arguments={
                "clause": "Trọng tài", "risk": "bất lợi", "severity": "high",
                "source": "kb", "evidence": "trọng tài tại Bắc Kinh"})])

        def complete(self, prompt, *, system=None):   # summary giờ dùng judge (=reasoner ở đây)
            return "Tóm tắt: 1 rủi ro cao về trọng tài."

    svc = AnalysisService(_ForgetfulLLM(), FileKnowledgeBaseProvider("knowledge_base"))
    result = svc.analyze(contract, default_org("VN"), lang="vi")
    assert result.needs_human_review is True
    assert any("tự động" in r for r in result.review_reasons)


def test_agent_no_risk_for_clean_contract():
    ctx = _ctx()
    run_agent("Hai bên hợp tác thân thiện, không điều khoản đặc biệt.", "Việt Nam", _stub_llm(), ctx)
    assert ctx.risks == []
    assert ctx.needs_human_review is False


def test_agent_forces_final_strategy_when_iters_exhausted(sample_contract):
    # LLM thật hay dồn hết max_iters cho tool calls → phải có lượt chốt, không trả strategy rỗng.
    from legalguard.domain.models import ChatTurn, ToolCall

    class _BusyLLM:
        available = False

        def __init__(self):
            self.calls = 0

        def chat(self, messages, tools=None):
            self.calls += 1
            if tools is not None:                  # trong vòng lặp: chỉ gọi tool, không kết luận
                return ChatTurn(tool_calls=[ToolCall(id=f"t{self.calls}", name="flag_risk",
                                arguments={"clause": f"C{self.calls}", "risk": "r",
                                           "severity": "medium", "source": "kb", "evidence": "x"})])
            return ChatTurn(content="CHIẾN LƯỢC CUỐI")   # lượt nudge (không tool) → chốt

    ctx = _ctx()
    run = run_agent(sample_contract, "Việt Nam", _BusyLLM(), ctx, lang="vi", max_iters=2)
    assert run.final_message == "CHIẾN LƯỢC CUỐI"


def test_agent_on_progress_reports_risk_count(sample_contract):
    # Heartbeat A1: callback được gọi sau mỗi vòng có tool, báo #rủi ro đã flag TĂNG dần.
    from legalguard.domain.models import ChatTurn, ToolCall

    class _BusyLLM:
        available = False

        def __init__(self):
            self.calls = 0

        def chat(self, messages, tools=None):
            self.calls += 1
            if tools is not None:
                return ChatTurn(tool_calls=[ToolCall(id=f"t{self.calls}", name="flag_risk",
                                arguments={"clause": f"C{self.calls}", "risk": "r",
                                           "severity": "medium", "source": "kb", "evidence": "x"})])
            return ChatTurn(content="XONG")

    events: list[dict] = []
    ctx = _ctx()
    run_agent(sample_contract, "Việt Nam", _BusyLLM(), ctx, lang="vi", max_iters=3,
              on_progress=events.append)
    assert events, "callback phải được gọi ít nhất 1 lần"
    assert events[-1]["risks"] >= 1                 # đã flag rủi ro
    assert [e["risks"] for e in events] == sorted(e["risks"] for e in events)  # tăng dần


def test_agent_on_progress_optional_default_none(sample_contract):
    # Không truyền callback → hành vi cũ nguyên vẹn (không lỗi).
    ctx = _ctx()
    run = run_agent(sample_contract, "Việt Nam", _stub_llm(), ctx)
    assert run is not None


def test_agent_marks_truncation_of_long_input(sample_contract):
    # Input vượt giới hạn ký tự → phải BÁO truncated, không cắt im lặng.
    run = run_agent(sample_contract + "x" * 9000, "Việt Nam", _stub_llm(), _ctx())
    assert run.truncated is True
    run2 = run_agent(sample_contract, "Việt Nam", _stub_llm(), _ctx())
    assert run2.truncated is False
