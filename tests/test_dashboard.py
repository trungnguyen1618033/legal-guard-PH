"""System-of-record dashboard: tổng hợp cases/feedback/outcome của 1 org (THUẦN + endpoint)."""
from legalguard.domain.dashboard import build_dashboard
from legalguard.domain.models import AnalysisCase, Feedback


def _case(cid, review=False, risks=None):
    return AnalysisCase(id=cid, org_id="acme", tenant="VN", created_at="2026-06-25T00:00:00Z",
                        lang="vi", contract_excerpt="", summary="", needs_human_review=review,
                        risks=risks or [], fallbacks=[], trace=[])


def _fb(rating, ref):
    return Feedback(id="x", org_id="acme", kind="lookup", ref=ref, rating=rating, note="",
                    created_at="2026-06-25T00:00:00Z")


def test_dashboard_empty():
    d = build_dashboard([], [])
    assert d["cases"]["total"] == 0 and d["feedback"]["total"] == 0
    assert d["top_risky_clauses"] == [] and d["top_tactics"] == []


def test_dashboard_aggregates_cases_and_risks():
    cases = [
        _case("c1", review=True, risks=[{"clause": "Phạt vi phạm", "severity": "high"},
                                        {"clause": "Trọng tài", "severity": "medium"}]),
        _case("c2", risks=[{"clause": "Phạt vi phạm", "severity": "high"}])]
    d = build_dashboard(cases, [])
    assert d["cases"]["total"] == 2 and d["cases"]["needs_review"] == 1
    assert d["cases"]["total_risks"] == 3
    assert d["cases"]["risk_by_severity"] == {"high": 2, "medium": 1}
    assert d["top_risky_clauses"][0] == {"clause": "Phạt vi phạm", "count": 2}   # hay gặp nhất đầu bảng


def test_dashboard_feedback_and_gaps():
    fbs = [_fb("helpful", "A"), _fb("wrong", "B"), _fb("incomplete", "B"), _fb("wrong", "C")]
    d = build_dashboard([], fbs)
    assert d["feedback"]["by_rating"] == {"helpful": 1, "wrong": 2, "incomplete": 1}
    assert d["feedback"]["kb_gaps"] == 2          # câu yếu duy nhất: B, C (B khử trùng)


def test_dashboard_top_tactics_sorted_by_winrate():
    wr = {"Trọng tài": {"rate": 0.9, "total": 10}, "Phạt": {"rate": 0.4, "total": 5}}
    d = build_dashboard([], [], wr)
    assert d["top_tactics"][0]["clause"] == "Trọng tài" and d["top_tactics"][0]["win_rate"] == 0.9


def test_dashboard_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    from legalguard.adapters.inbound.http import build_api
    from legalguard.adapters.outbound.document_parser import PdfDocxParser
    from legalguard.adapters.outbound.revenue_log import CsvRevenueLog
    from legalguard.config.container import build_service
    from legalguard.config.settings import settings
    from legalguard.domain.evidence import EvidenceService

    cfg = settings.model_copy(update={"database_url": f"sqlite:///{tmp_path / 'd.db'}"})
    service = build_service(cfg)
    case = _case("c1", risks=[{"clause": "Phạt", "severity": "high"}])
    case.org_id = "default"                       # endpoint (auth off) dùng org 'default'
    service.cases.save(case)
    evidence = EvidenceService(CsvRevenueLog(str(tmp_path / "r.csv")))
    c = TestClient(build_api(service, PdfDocxParser(), evidence, api_orgs={}))
    body = c.get("/insights/dashboard").json()
    assert body["cases"]["total"] == 1 and body["cases"]["total_risks"] == 1
    assert body["top_risky_clauses"][0]["clause"] == "Phạt"
