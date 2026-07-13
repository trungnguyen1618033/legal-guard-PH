"""Nghĩa vụ & hạn chót (SAU KÝ) — domain thuần + repo + service (offline, không cần DB/LLM thật)."""
from datetime import date, timedelta

from legalguard.adapters.outbound.sql_obligation_repository import InMemoryObligationRepository
from legalguard.domain.analysis import AnalysisService
from legalguard.domain.models import Obligation
from legalguard.domain.obligations import (
    _parse_obligations,
    extract_obligations,
    format_obligation_digest,
    resolve_due_date,
    upcoming,
)


class _LLM:
    name = "qwen"

    def __init__(self, out, available=True):
        self._out, self._a = out, available

    @property
    def available(self):
        return self._a

    def complete(self, prompt, *, system=None):
        return self._out


# ---- parse ----
def test_parse_obligations_fenced_and_garbage():
    raw = ('nội dung:\n```json\n[{"kind":"payment","description":"Thanh toán đợt 2 40%",'
           '"due_date":"2026-09-01","party":"Bên Mua","consequence":"phạt 0,05%/ngày"}]\n```')
    out = _parse_obligations(raw)
    assert len(out) == 1 and out[0]["kind"] == "payment" and out[0]["due_date"] == "2026-09-01"
    assert _parse_obligations("không phải json") == []
    assert _parse_obligations("") == []


def test_parse_obligations_normalizes_kind_and_date():
    raw = '[{"kind":"weird","description":"x","due_date":"01/09/2026"}]'   # kind lạ + ngày sai format
    out = _parse_obligations(raw)
    assert out[0]["kind"] == "other"          # kind ngoài whitelist → other
    assert out[0]["due_date"] == ""           # ngày không phải ISO → rỗng


# ---- resolve mốc tương đối ----
def test_resolve_due_date_relative():
    end = date(2026, 9, 1)
    assert resolve_due_date("30 ngày trước ngày hết hạn hợp đồng", contract_end=end) == "2026-08-02"
    assert resolve_due_date("30 ngày trước khi hết hạn", contract_end=None) == ""   # thiếu dữ kiện
    assert resolve_due_date("thanh toán ngay", contract_end=end) == ""              # không phải mốc tương đối


# ---- extract (fake LLM) ----
def test_extract_obligations_offline_returns_empty():
    assert extract_obligations(_LLM("", available=False), "HĐ...") == []
    assert extract_obligations(_LLM("[...]"), "") == []       # không có contract_text


def test_extract_obligations_parses_and_resolves():
    llm = _LLM('[{"kind":"termination_notice","description":"Báo không gia hạn",'
               '"due_date":"","rule":"30 ngày trước ngày hết hạn","party":"Bên Mua",'
               '"consequence":"HĐ tự gia hạn 12 tháng"}]')
    out = extract_obligations(llm, "hợp đồng...", contract_end=date(2026, 9, 1))
    assert len(out) == 1
    assert out[0]["due_date"] == "2026-08-02"     # rule tương đối → quy ra ngày


def test_extract_obligations_resolves_from_llm_contract_end():
    # LLM tự trả ngày hết hạn HĐ (object form) → quy mốc tương đối KHÔNG cần caller truyền contract_end
    llm = _LLM('{"contract_end":"2026-09-01","obligations":['
               '{"kind":"termination_notice","description":"Báo không gia hạn","due_date":"",'
               '"rule":"30 ngày trước ngày hết hạn"}]}')
    out = extract_obligations(llm, "hợp đồng...")     # KHÔNG truyền contract_end
    assert out[0]["due_date"] == "2026-08-02"


# ---- upcoming + digest ----
def _obl(due, status="pending", desc="X", cons=""):
    return Obligation(id="i", org_id="o", case_id="c", kind="payment", description=desc,
                      due_date=due, consequence=cons, status=status)


def test_upcoming_filters_and_sorts():
    today = date(2026, 8, 1)
    items = [
        _obl("2026-08-05"), _obl("2026-08-02"),           # trong 14 ngày
        _obl("2026-09-30"),                               # ngoài 14 ngày
        _obl("2026-08-03", status="done"),                # done → loại
        _obl(""),                                          # không có ngày → loại khỏi nhắc
    ]
    ups = upcoming(items, today, within_days=14)
    assert [o.due_date for o in ups] == ["2026-08-02", "2026-08-05"]   # lọc + sắp tăng dần


def test_format_digest():
    today = date(2026, 8, 1)
    txt = format_obligation_digest([_obl("2026-08-08", desc="Báo không gia hạn", cons="tự gia hạn")], today)
    assert "Báo không gia hạn" in txt and "còn 7 ngày" in txt and "tự gia hạn" in txt
    assert format_obligation_digest([], today) == ""


# ---- repo (in-memory) ----
def test_repo_org_scope_within_and_cascade():
    repo = InMemoryObligationRepository()
    soon = (date.today() + timedelta(days=5)).isoformat()
    far = (date.today() + timedelta(days=90)).isoformat()
    repo.add_many([
        Obligation(id="1", org_id="A", case_id="cA", kind="payment", description="a", due_date=soon),
        Obligation(id="2", org_id="A", case_id="cA", kind="payment", description="b", due_date=far),
        Obligation(id="3", org_id="B", case_id="cB", kind="payment", description="c", due_date=soon),
    ])
    assert len(repo.list_by_org("A")) == 2                       # cô lập org
    assert len(repo.list_by_org("B")) == 1
    assert [o.id for o in repo.list_by_org("A", within_days=14)] == ["1"]   # chỉ 'soon' trong 14 ngày
    repo.set_status("1", "A", "done")
    assert len(repo.list_by_org("A", status="pending")) == 1
    repo.set_status("2", "B", "done")                            # sai org → KHÔNG đổi
    assert repo.list_by_org("A", status="pending")[0].id == "2"
    assert repo.delete_by_case("cA") == 2                        # cascade: cả id 1 & 2 (đều case_id=cA)
    assert repo.list_by_org("A") == []                           # A rỗng sau cascade


# ---- service (fake reasoner + in-memory repo) ----
def _svc(reasoner, repo):
    return AnalysisService(reasoner=reasoner, kb=object(), obligations=repo, obligation_tracking=True)


def test_service_extract_store_list_digest():
    repo = InMemoryObligationRepository()
    llm = _LLM('[{"kind":"payment","description":"Thanh toán đợt 2","due_date":"%s"}]'
               % (date.today() + timedelta(days=3)).isoformat())
    svc = _svc(llm, repo)
    n = svc.extract_and_store_obligations("hợp đồng...", "orgX", "case1")
    assert n == 1
    stored = repo.list_by_org("orgX")
    assert stored[0].org_id == "orgX" and stored[0].case_id == "case1" and stored[0].id   # gắn id/org/case
    items, text = svc.obligation_digest("orgX", within_days=14)
    assert len(items) == 1 and "Thanh toán đợt 2" in text


def test_service_extract_offline_stores_nothing():
    repo = InMemoryObligationRepository()
    svc = _svc(_LLM("", available=False), repo)
    assert svc.extract_and_store_obligations("hợp đồng...", "orgX", "case1") == 0
    assert repo.list_by_org("orgX") == []


# ---- endpoints (SQL path, DB file của conftest) ----
def test_obligation_endpoints(tmp_path):
    from fastapi.testclient import TestClient

    from legalguard.adapters.inbound.http import build_api
    from legalguard.adapters.outbound.document_parser import PdfDocxParser
    from legalguard.adapters.outbound.revenue_log import CsvRevenueLog
    from legalguard.config.container import build_service
    from legalguard.domain.evidence import EvidenceService

    evidence = EvidenceService(CsvRevenueLog(str(tmp_path / "r.csv")))
    c = TestClient(build_api(build_service(), PdfDocxParser(), evidence, api_orgs={}))
    assert c.get("/obligations").json() == {"obligations": [], "count": 0}
    assert c.post("/obligations/run", json={"within_days": 14}).json()["upcoming"] == 0
    assert c.post("/obligations/x/status", json={"status": "weird"}).status_code == 400   # validate
    assert c.post("/obligations/x/status", json={"status": "done"}).status_code == 200
