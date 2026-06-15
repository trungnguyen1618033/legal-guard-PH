from legalguard.adapters.outbound.knowledge_base import KeywordRetriever
from legalguard.adapters.outbound.qwen import QwenAdapter
from legalguard.domain.agent import run_agent
from legalguard.domain.models import AgentContext, AnalysisResult
from legalguard.domain.reporting import render_markdown_report
from legalguard.domain.tenants import get_tenant


def _run(lang, sample_contract):
    ctx = AgentContext(retriever=KeywordRetriever("knowledge_base", "VN"))
    run_agent(sample_contract, "Việt Nam", QwenAdapter("", "http://x", "qwen-plus"), ctx, lang=lang)
    return ctx


def test_agent_default_english(sample_contract):
    ctx = _run("en", sample_contract)
    assert ctx.risks[0].clause == "Arbitration clause"          # mặc định EN
    assert all(f.english_reply for f in ctx.fallbacks)


def test_agent_vietnamese_mode(sample_contract):
    ctx = _run("vi", sample_contract)
    assert ctx.risks[0].clause == "Điều khoản trọng tài"        # chế độ VN
    # Câu gửi đối tác vẫn tiếng Anh dù output tiếng Việt.
    assert ctx.fallbacks[0].english_reply.startswith("We propose")


def _result():
    return AnalysisResult("VN", [{"clause": "X", "risk": "r", "severity": "low"}],
                          [], False, [], "s", [], [])


def test_report_english_default():
    md = render_markdown_report(_result(), get_tenant("VN"), "en")
    assert "Contract Review Report" in md and "Risks found" in md


def test_report_vietnamese():
    md = render_markdown_report(_result(), get_tenant("VN"), "vi")
    assert "Báo cáo Rà soát Hợp đồng" in md and "Rủi ro phát hiện" in md
