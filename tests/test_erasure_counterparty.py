"""Right-to-erasure #1: tình tiết TỔNG-HỢP theo-đối-tác (negotiation/profile lưu case_id="") phải bị xóa
khi KHÔNG còn case nào của đối tác — trước đây `delete_by_case` bỏ sót → sống mãi sau erasure (vi phạm
PDPD/GDPR). GIỮ nếu còn deal khác của đối tác. Cô lập org."""
from __future__ import annotations

from legalguard.adapters.outbound.memory_store import InMemoryMemory
from legalguard.adapters.outbound.sql_memory_store import SqlMemory
from legalguard.domain.analysis import AnalysisService
from legalguard.domain.models import AnalysisCase, MemoryEpisode


class _LLM:
    available = False

    def embed(self, t):   # noqa: ANN001
        return None


class _Cases:
    def __init__(self, cases):
        self.d = {c.id: c for c in cases}

    def get(self, cid):   # noqa: ANN001
        return self.d.get(cid)

    def delete(self, cid):   # noqa: ANN001
        return self.d.pop(cid, None) is not None

    def list_by_org(self, org_id, limit=20):   # noqa: ANN001
        return [c for c in self.d.values() if c.org_id == org_id][:limit]


def _case(cid, cp="ACME Corp", org="org1"):
    return AnalysisCase(id=cid, org_id=org, tenant="VN", created_at="2026-07-22", lang="vi",
                        contract_excerpt="", summary="", needs_human_review=False,
                        risks=[], fallbacks=[], trace=[], counterparty=cp)


def _seed(mem, org="org1", cp="ACME Corp"):
    # 3 loại: outcome (gắn case), negotiation (case_id=""), profile (case_id="")
    mem.remember(MemoryEpisode(id="", org_id=org, counterparty=cp, kind="outcome",
                               clause="Phạt", content="chốt 8%", created_at="t", case_id="c1"))
    mem.remember(MemoryEpisode(id="", org_id=org, counterparty=cp, kind="negotiation",
                               clause="", content="đối tác ép phạt 15%", created_at="t", case_id=""))
    mem.remember(MemoryEpisode(id=f"profile:{org}:{cp.lower()}", org_id=org, counterparty=cp,
                               kind="profile", clause="", content="hồ sơ đối tác", created_at="t", case_id=""))


def test_erasure_purges_counterparty_memory_when_no_case_left():
    mem = InMemoryMemory()
    _seed(mem)
    svc = AnalysisService(reasoner=_LLM(), kb=object(), cases=_Cases([_case("c1")]),
                          memory=mem, agentic_memory=True)
    assert svc.recall_memory("org1", "phạt", counterparty="ACME Corp")     # có trước khi xóa
    assert svc.delete_case("c1") is True
    # KHÔNG còn case ACME → purge SẠCH (gồm negotiation + profile case_id="")
    assert svc.recall_memory("org1", "phạt", counterparty="ACME Corp") == []
    assert mem.list_by_counterparty("org1", "ACME Corp", include_history=True) == []


def test_erasure_keeps_counterparty_memory_when_another_case_remains():
    mem = InMemoryMemory()
    _seed(mem)
    # 2 case cùng đối tác; xóa 1 → GIỮ bộ nhớ tổng-hợp (còn deal khác backing)
    svc = AnalysisService(reasoner=_LLM(), kb=object(), cases=_Cases([_case("c1"), _case("c2")]),
                          memory=mem, agentic_memory=True)
    assert svc.delete_case("c1") is True
    left = mem.list_by_counterparty("org1", "ACME Corp", include_history=True)
    kinds = {e.kind for e in left}
    assert "negotiation" in kinds and "profile" in kinds     # tổng-hợp còn nguyên
    # outcome gắn c1 vẫn bị dọn theo case
    assert not any(e.kind == "outcome" and e.case_id == "c1" for e in left)


def test_delete_by_counterparty_store_org_isolated():
    for mem in (InMemoryMemory(), SqlMemory("sqlite://")):
        _seed(mem, org="org1")
        _seed(mem, org="org2")
        n = mem.delete_by_counterparty("org1", "ACME Corp")
        assert n == 3
        assert mem.list_by_counterparty("org1", "ACME Corp", include_history=True) == []
        assert len(mem.list_by_counterparty("org2", "ACME Corp", include_history=True)) == 3  # org khác nguyên
