"""E2E FLYWHEEL theo-đối-tác (Option B) — kiểm CẢ vòng: analyze(counterparty) → case lưu counterparty →
Chốt (record_outcome gắn cp) → consolidation → analyze lại CÙNG đối tác → mục 'Về đối tác này'.
Đây là checkpoint tích hợp CHUNG (S1 schema+wiring + S2 analyze-set+consolidate). Offline (stub LLM + KB thật)."""
from __future__ import annotations

from legalguard.adapters.inbound.channels import _record_deal_outcome
from legalguard.adapters.outbound.knowledge_base import FileKnowledgeBaseProvider
from legalguard.adapters.outbound.memory_store import InMemoryMemory
from legalguard.adapters.outbound.qwen import QwenAdapter
from legalguard.domain.analysis import AnalysisService
from legalguard.domain.models import NegotiationPosition
from legalguard.domain.tenants import default_org


class _Cases:
    """Case repo tối giản in-process (get/save) — đủ cho vòng flywheel."""
    def __init__(self):
        self.d = {}

    def save(self, case):   # noqa: ANN001
        self.d[case.id] = case
        return case.id

    def get(self, cid):   # noqa: ANN001
        return self.d.get(cid)


def _svc(mem):
    return AnalysisService(reasoner=QwenAdapter(api_key="", base_url="http://x", model="qwen-plus"),
                           kb=FileKnowledgeBaseProvider("knowledge_base"),
                           cases=_Cases(), memory=mem, agentic_memory=True)


_CONTRACT = "Bên B chịu phạt vi phạm hợp đồng 15% giá trị. Tranh chấp tại Bắc Kinh."


def test_analyze_persists_counterparty_to_case():
    """analyze(position.counterparty) → case lưu counterparty (để record_outcome suy ra). Live từ `6f6687f`."""
    mem = InMemoryMemory()
    svc = _svc(mem)
    res = svc.analyze(_CONTRACT, default_org("VN"), lang="vi",
                      position=NegotiationPosition(counterparty="ACME Corp"))
    case = svc.get_case(res.case_id)
    assert case is not None and case.counterparty == "ACME Corp"


def test_full_flywheel_loop_counterparty_memory():
    """Vòng đầy đủ: analyze → Chốt (outcome gắn cp) → analyze lại → 'Về đối tác này' xuất hiện."""
    org = default_org("VN")
    mem = InMemoryMemory()
    svc = _svc(mem)
    # 1) Rà lần 1 với đối tác ACME
    r1 = svc.analyze(_CONTRACT, org, lang="vi", position=NegotiationPosition(counterparty="ACME Corp"))
    # 2) Chốt → ghi outcome cho mọi điều khoản, gắn ĐÚNG đối tác (suy từ case)
    n = _record_deal_outcome(svc, org.id, r1.case_id, "accepted")
    assert n >= 1
    got = svc.recall_memory(org.id, "phạt", counterparty="ACME Corp")
    assert got and any(e.counterparty == "ACME Corp" for e in got)
    # 3) Rà lần 2 CÙNG đối tác → briefing 'Về đối tác này' có nội dung (recall tình tiết trước)
    r2 = svc.analyze(_CONTRACT, org, lang="vi", position=NegotiationPosition(counterparty="ACME Corp"))
    assert r2.counterparty_notes, "lần rà thứ 2 phải recall tình tiết đối tác từ deal trước"
