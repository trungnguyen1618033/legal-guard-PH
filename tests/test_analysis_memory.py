"""Test wiring bộ nhớ agent vào AnalysisService — ghi khi record_outcome, gating flag, cascade erasure."""
from __future__ import annotations

from legalguard.adapters.outbound.memory_store import InMemoryMemory
from legalguard.domain.analysis import AnalysisService
from legalguard.domain.models import Outcome


class _DummyLLM:
    available = False

    def embed(self, texts):   # noqa: ANN001
        return None


class _RoundLLM:
    """Reasoner giả available=True → negotiate_round trả grounded=True (để nhớ vòng đàm phán)."""
    name = "qwen"
    available = True

    def complete(self, prompt, *, system=None):   # noqa: ANN001
        return ""       # _parse_round("") → khung fallback, grounded vẫn True


class _FakeCases:
    def delete(self, case_id):   # noqa: ANN001
        return True


def _svc(memory=None, flag=False, cases=None):
    return AnalysisService(reasoner=_DummyLLM(), kb=object(), cases=cases,
                           memory=memory, agentic_memory=flag)


def _outcome(clause="Thanh toán", tactic="giữ trần 8%", result="accepted", case_id="c1"):
    return Outcome(id="o1", org_id="org1", case_id=case_id, clause=clause, tactic=tactic,
                   result=result, created_at="2026-07-21")


def test_record_outcome_remembers_when_flag_on():
    mem = InMemoryMemory()
    svc = _svc(memory=mem, flag=True)
    svc.record_outcome(_outcome())
    got = svc.recall_memory("org1", "trần thanh toán")
    assert got and got[0].kind == "outcome" and "8%" in got[0].content


def test_no_remember_when_flag_off():
    mem = InMemoryMemory()
    svc = _svc(memory=mem, flag=False)             # flag OFF
    svc.record_outcome(_outcome())
    assert svc.recall_memory("org1", "trần thanh toán") == []   # không ghi + recall tắt


def test_recall_memory_org_isolated():
    mem = InMemoryMemory()
    svc = _svc(memory=mem, flag=True)
    svc.record_outcome(_outcome())
    assert svc.recall_memory("orgX", "trần thanh toán") == []    # org khác → rỗng


def test_delete_case_cascades_to_memory():
    mem = InMemoryMemory()
    svc = _svc(memory=mem, flag=True, cases=_FakeCases())
    svc.record_outcome(_outcome(case_id="caseZ"))
    assert svc.recall_memory("org1", "trần thanh toán")          # có trước khi xóa
    svc.delete_case("caseZ")
    assert svc.recall_memory("org1", "trần thanh toán") == []    # cascade xóa sạch


def test_remember_failure_never_breaks_outcome():
    class _BoomMemory:
        def remember(self, ep):   # noqa: ANN001
            raise RuntimeError("boom")

        def recall(self, *a, **k):
            return []

        def delete_by_case(self, cid):   # noqa: ANN001
            return 0

    svc = _svc(memory=_BoomMemory(), flag=True)
    svc.record_outcome(_outcome())        # KHÔNG được ném lỗi (failure-safe)


def test_negotiate_remembers_by_counterparty():
    from legalguard.domain.models import NegotiationPosition
    mem = InMemoryMemory()
    svc = AnalysisService(reasoner=_RoundLLM(), kb=object(), memory=mem, agentic_memory=True)
    svc.negotiate_round("bối cảnh deal", "chúng tôi đòi phạt 15%",
                        position=NegotiationPosition(counterparty="ACME"), org_id="org1")
    got = svc.recall_memory("org1", "phạt", counterparty="ACME")
    assert got and got[0].kind == "negotiation" and got[0].counterparty == "ACME"


def test_negotiate_no_remember_when_flag_off():
    from legalguard.domain.models import NegotiationPosition
    mem = InMemoryMemory()
    svc = AnalysisService(reasoner=_RoundLLM(), kb=object(), memory=mem, agentic_memory=False)
    svc.negotiate_round("bối cảnh", "đòi phạt 15%",
                        position=NegotiationPosition(counterparty="ACME"), org_id="org1")
    assert svc.recall_memory("org1", "phạt", counterparty="ACME") == []   # flag OFF → không ghi
