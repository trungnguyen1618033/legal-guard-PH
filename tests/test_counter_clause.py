"""Counter-clause: sinh điều khoản phản-đề song ngữ từ risk/fallback (bám căn cứ + vị thế)."""
from legalguard.domain.counter_clause import _parse_counter, draft_counter_clause


class _LLM:
    name = "qwen"

    def __init__(self, out, available=True):
        self._out, self._a = out, available

    @property
    def available(self):
        return self._a

    def complete(self, prompt, *, system=None):
        return self._out


def test_parse_counter_fenced_json():
    raw = 'Đây:\n```json\n{"vi": "Điều khoản VN", "en": "EN clause", "rationale": "vì A"}\n```'
    assert _parse_counter(raw) == {"vi": "Điều khoản VN", "en": "EN clause", "rationale": "vì A"}


def test_parse_counter_bare_json():
    assert _parse_counter('{"vi":"a","en":"b","rationale":"c"}') == {"vi": "a", "en": "b", "rationale": "c"}


def test_parse_counter_garbage_falls_back_to_vi():
    d = _parse_counter("không phải json gì cả")
    assert d["vi"] == "không phải json gì cả" and d["en"] == ""


def test_draft_offline_returns_safe_scaffold():
    # Chưa có key (stub) → khung an toàn, grounded=False, KHÔNG bịa luật.
    cc = draft_counter_clause(_LLM("", available=False), clause="Phạt vi phạm 15%",
                              suggestion="giảm về 8%", legal_basis="ltm.md#Điều 301: …")
    assert cc.grounded is False
    assert "Phạt vi phạm 15%" in cc.vi and "giảm về 8%" in cc.vi
    assert "Điều 301" in cc.vi                 # căn cứ được nhắc lại, không bịa thêm
    assert cc.en == ""


def test_draft_online_parses_llm_json():
    llm = _LLM('{"vi": "Hai bên thỏa thuận phạt tối đa 8%.", '
               '"en": "Penalty capped at 8%.", "rationale": "Theo Điều 301 LTM 2005."}')
    cc = draft_counter_clause(llm, clause="Phạt 15%", risk="quá mức luật cho phép",
                              suggestion="giảm 8%", legal_basis="ltm.md#Điều 301", leverage="strong")
    assert cc.grounded is True
    assert cc.vi == "Hai bên thỏa thuận phạt tối đa 8%."
    assert cc.en == "Penalty capped at 8%."
    assert cc.legal_basis == "ltm.md#Điều 301"


def test_counter_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    from legalguard.adapters.inbound.http import build_api
    from legalguard.adapters.outbound.document_parser import PdfDocxParser
    from legalguard.adapters.outbound.revenue_log import CsvRevenueLog
    from legalguard.config.container import build_service
    from legalguard.domain.evidence import EvidenceService

    evidence = EvidenceService(CsvRevenueLog(str(tmp_path / "r.csv")))
    c = TestClient(build_api(build_service(), PdfDocxParser(), evidence, api_orgs={}))
    r = c.post("/counter", json={"clause": "Phạt vi phạm 15%", "suggestion": "giảm về 8%",
                                 "legal_basis": "ltm.md#Điều 301: …"})
    assert r.status_code == 200
    body = r.json()
    assert "vi" in body and "en" in body and "grounded" in body
    assert "Phạt vi phạm 15%" in body["vi"]    # stub mode → khung chứa điều khoản gốc
