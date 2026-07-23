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

    def get(self, case_id):   # noqa: ANN001 — delete_case nạp case trước khi xóa (erasure theo đối tác)
        return None

    def list_by_org(self, org_id, limit=20):   # noqa: ANN001
        return []


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


def test_briefing_scopes_to_counterparty_no_cross_leak():
    """Brief 'Về đối tác này' KHÔNG được lẫn tình tiết đối tác khác (recall boost-không-filter → lọc lại)."""
    from legalguard.domain.analysis import _counterparty_briefing
    from legalguard.domain.models import MemoryEpisode

    def ep(cp, clause, content):
        return MemoryEpisode(id="", org_id="o", counterparty=cp, kind="outcome", clause=clause,
                             content=content, created_at="2026-07-01", case_id="c")

    mem = InMemoryMemory()
    mem.remember(ep("ACME", "Điều khoản Thanh toán", "ACME phạt 15%, ta giữ 8%"))
    mem.remember(ep("GLOBEX", "Điều khoản Trọng tài", "GLOBEX muốn trọng tài Singapore, ta chốt VIAC"))
    # HĐ với ACME có điều khoản trọng tài → recall(cp=ACME) lọt cả tình tiết GLOBEX (boost, không filter).
    got = mem.recall("o", "điều khoản trọng tài của hợp đồng", counterparty="ACME", k=5)
    assert any(e.counterparty == "GLOBEX" for e in got)   # recall THẬT trả lẫn (đúng bản chất boost)
    brief = _counterparty_briefing("ACME", got)            # nhưng brief phải CÔ LẬP về ACME
    assert brief and all("GLOBEX" not in line for line in brief)
    assert any("ACME" in line for line in brief)


def test_briefing_empty_when_no_episode_for_that_counterparty():
    """Recall trả tình tiết đối tác khác nhưng KHÔNG có gì của cp hỏi → brief rỗng (không bịa)."""
    from legalguard.domain.analysis import _counterparty_briefing
    from legalguard.domain.models import MemoryEpisode
    eps = [MemoryEpisode(id="g", org_id="o", counterparty="GLOBEX", kind="outcome",
                         clause="Trọng tài", content="VIAC", created_at="2026-07-01", case_id="c")]
    assert _counterparty_briefing("ACME", eps) == []
