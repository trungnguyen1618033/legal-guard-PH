"""Memory-aware /analyze: rà HĐ MỚI với đối tác đã từng làm việc → recall tình tiết deal trước làm brief
THAM KHẢO (`AnalysisResult.counterparty_notes`). ISOLATED khỏi vòng agent → accuracy KHÔNG đổi.
Trước đây recall CHỈ có ở negotiate_round; analyze (entry chính) memory-BLIND — đây là mảnh vá."""
from __future__ import annotations

from legalguard.adapters.outbound.knowledge_base import FileKnowledgeBaseProvider
from legalguard.adapters.outbound.memory_store import InMemoryMemory
from legalguard.adapters.outbound.qwen import QwenAdapter
from legalguard.domain.analysis import AnalysisService, _counterparty_briefing
from legalguard.domain.models import MemoryEpisode, NegotiationPosition
from legalguard.domain.tenants import default_org


# ---- Pure helper: _counterparty_briefing ---------------------------------------------------------
def _ep(kind="outcome", clause="Thanh toán", content="giữ trần 8% → accepted"):
    return MemoryEpisode(id="e", org_id="o", counterparty="ACME", kind=kind,
                         clause=clause, content=content, created_at="2026-07-21")


def test_briefing_empty_when_no_counterparty_or_episodes():
    assert _counterparty_briefing("", [_ep()]) == []
    assert _counterparty_briefing("ACME", []) == []


def test_briefing_profile_goes_first():
    eps = [_ep(kind="outcome", content="giữ trần 8%"),
           _ep(kind="profile", clause="", content="Đối tác hay ép phạt cao")]
    out = _counterparty_briefing("ACME", eps)
    assert out[0].startswith("[Hồ sơ]") and "ép phạt cao" in out[0]


def test_briefing_skips_empty_content_and_caps_limit():
    eps = [_ep(content=""), *[_ep(content=f"tình tiết {i}") for i in range(10)]]
    out = _counterparty_briefing("ACME", eps, limit=3)
    assert len(out) == 3
    assert all("tình tiết" in line for line in out)


# ---- End-to-end: analyze() populates counterparty_notes ------------------------------------------
def _stub_llm():
    return QwenAdapter(api_key="", base_url="http://x", model="qwen-plus")   # available=False → stub


def _svc(memory, flag):
    return AnalysisService(reasoner=_stub_llm(), kb=FileKnowledgeBaseProvider("knowledge_base"),
                           memory=memory, agentic_memory=flag)


_CONTRACT = "Bên B chịu phạt vi phạm hợp đồng 15% giá trị hợp đồng. Tranh chấp giải quyết tại Bắc Kinh."


def _seed(mem, org_id, cp="ACME"):
    mem.remember(MemoryEpisode(id="", org_id=org_id, counterparty=cp, kind="outcome",
                               clause="Phạt vi phạm", content="deal trước ép phạt 15% → ta chốt 8%",
                               created_at="2026-07-20"))


def test_analyze_recalls_counterparty_notes_when_flag_on():
    org = default_org("VN")
    mem = InMemoryMemory()
    _seed(mem, org.id)
    res = _svc(mem, flag=True).analyze(
        _CONTRACT, org, lang="vi", position=NegotiationPosition(counterparty="ACME"))
    assert res.counterparty_notes, "phải recall tình tiết đối tác ACME"
    assert any("8%" in n or "15%" in n for n in res.counterparty_notes)
    assert any("đối tác" in note.lower() and "ACME" in note for note in res.notes)


def test_analyze_no_notes_when_flag_off():
    org = default_org("VN")
    mem = InMemoryMemory()
    _seed(mem, org.id)
    res = _svc(mem, flag=False).analyze(
        _CONTRACT, org, lang="vi", position=NegotiationPosition(counterparty="ACME"))
    assert res.counterparty_notes == []


def test_analyze_no_notes_without_counterparty():
    org = default_org("VN")
    mem = InMemoryMemory()
    _seed(mem, org.id)
    res = _svc(mem, flag=True).analyze(_CONTRACT, org, lang="vi")   # không position/counterparty
    assert res.counterparty_notes == []


def test_analyze_memory_failure_never_breaks_result():
    class _BoomMemory:
        def recall(self, *a, **k):
            raise RuntimeError("boom")

        def remember(self, ep):   # noqa: ANN001
            return None

    org = default_org("VN")
    res = _svc(_BoomMemory(), flag=True).analyze(
        _CONTRACT, org, lang="vi", position=NegotiationPosition(counterparty="ACME"))
    assert res.counterparty_notes == []          # nuốt lỗi, KHÔNG chặn phân tích
    assert res.risks or res.summary or res.notes  # kết quả vẫn dựng
