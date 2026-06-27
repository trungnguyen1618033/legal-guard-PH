"""Phase A — rà soát cho luật sư: phân loại illegal/unfavorable + 'bên mình bảo vệ'."""
from legalguard.adapters.outbound.knowledge_base import KeywordRetriever
from legalguard.config.container import build_service
from legalguard.domain.agent import run_agent
from legalguard.domain.models import AgentContext, ChatTurn, NegotiationPosition
from legalguard.domain.tenants import default_org

ORG = default_org("VN")
SAMPLE = "Hợp đồng: phạt vi phạm 15% giá trị, trọng tài tại Bắc Kinh, thanh toán T/T 60 ngày."


def test_analyze_classifies_illegal_vs_unfavorable():
    res = build_service().analyze(SAMPLE, ORG, lang="vi")
    statuses = {r["legal_status"] for r in res.risks}
    assert "illegal" in statuses and "unfavorable" in statuses     # tách 2 nhóm
    illegal = [r for r in res.risks if r["legal_status"] == "illegal"]
    assert illegal and illegal[0]["violated_law"]                  # illegal kèm điều luật bị vi phạm


def test_every_risk_has_valid_legal_status():
    res = build_service().analyze(SAMPLE, ORG, lang="vi")
    assert all(r["legal_status"] in ("illegal", "unfavorable") for r in res.risks)


class _Spy:
    name = "qwen"

    def __init__(self):
        self.system = ""

    @property
    def available(self):
        return True

    def chat(self, messages, *, tools=None):
        self.system = messages[0]["content"]
        return ChatTurn(content="done")


def test_protected_party_in_agent_prompt():
    spy = _Spy()
    ctx = AgentContext(retriever=KeywordRetriever("knowledge_base", "VN"))
    run_agent("Hợp đồng vay", "Việt Nam", spy, ctx, lang="vi",
              position=NegotiationPosition(protected_party="Bên Vay"))
    assert "Bên Vay" in spy.system                                 # bên bảo vệ vào prompt


def test_default_protected_party_falls_back_to_sme():
    spy = _Spy()
    ctx = AgentContext(retriever=KeywordRetriever("knowledge_base", "VN"))
    run_agent("x", "Việt Nam", spy, ctx, lang="vi")                # không khai → mặc định
    assert "SME client in Việt Nam" in spy.system
