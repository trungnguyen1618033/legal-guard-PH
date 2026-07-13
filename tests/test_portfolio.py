"""Portfolio — danh mục HĐ hành-động-được (thuần build_portfolio + endpoint). Offline."""
from datetime import date, timedelta

from legalguard.domain.models import AnalysisCase, Obligation
from legalguard.domain.portfolio import build_portfolio


def _case(cid, risks=None, needs_review=False, name=""):
    return AnalysisCase(id=cid, org_id="A", tenant="VN", created_at="t", lang="vi",
                        contract_excerpt="excerpt", summary="", needs_human_review=needs_review,
                        risks=risks or [], fallbacks=[], trace=[], source_name=name)


def test_build_portfolio_ranks_by_urgency():
    today = date(2026, 8, 1)
    soon = (today + timedelta(days=5)).isoformat()
    cases = [
        _case("A", risks=[{"priority": "must_fix", "legal_status": "illegal"},
                          {"priority": "must_fix"}], needs_review=True, name="HĐ A"),
        _case("B"),                                             # nhẹ, nhưng có hạn gần
        _case("C", risks=[{"priority": "must_fix"}]),
    ]
    obs = [Obligation(id="o1", org_id="A", case_id="B", kind="payment", description="x", due_date=soon)]
    rows = build_portfolio(cases, obs, today)
    ids = [r["case_id"] for r in rows]
    assert ids == ["B", "A", "C"]          # B (hạn 5 ngày→55) > A (2mf+1ill+review=31) > C (1mf=8)
    a = next(r for r in rows if r["case_id"] == "A")
    assert a["must_fix"] == 2 and a["illegal"] == 1 and a["needs_review"] is True
    b = next(r for r in rows if r["case_id"] == "B")
    assert b["next_due"] == soon and b["days_to_due"] == 5


def test_build_portfolio_degrades_without_obligations():
    # Chưa bật obligation_tracking → không có hạn, vẫn xếp theo must_fix/duyệt (không lỗi).
    today = date(2026, 8, 1)
    rows = build_portfolio([_case("A", risks=[{"priority": "must_fix"}])], [], today)
    assert rows[0]["case_id"] == "A" and rows[0]["next_due"] == "" and rows[0]["days_to_due"] is None


def test_portfolio_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    from legalguard.adapters.inbound.http import build_api
    from legalguard.adapters.outbound.document_parser import PdfDocxParser
    from legalguard.adapters.outbound.revenue_log import CsvRevenueLog
    from legalguard.config.container import build_service
    from legalguard.domain.evidence import EvidenceService

    evidence = EvidenceService(CsvRevenueLog(str(tmp_path / "r.csv")))
    c = TestClient(build_api(build_service(), PdfDocxParser(), evidence, api_orgs={}))
    r = c.get("/portfolio")
    assert r.status_code == 200 and "portfolio" in r.json() and "count" in r.json()
