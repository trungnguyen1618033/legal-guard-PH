"""Regulatory change intelligence: VB mới → case nào viện dẫn VB bị tác động → cảnh báo."""
from legalguard.adapters.outbound.knowledge_base import affected_doc_files
from legalguard.domain.models import AnalysisCase
from legalguard.domain.regulatory import (
    format_impact_alert,
    norm_article,
    parse_basis,
    parse_basis_file,
    scan_cases,
)


def _aff(relation, *articles):
    return {"relation": relation, "articles": list(articles)}


def test_parse_basis():
    assert parse_basis("nd_123_2020_hoa_don.md#Điều 9: nội dung…") == ("nd_123_2020_hoa_don.md", "điều 9")
    assert parse_basis("file.md#Điều 5") == ("file.md", "điều 5")
    assert parse_basis("không có dấu thăng") == ("", "")
    assert parse_basis_file("file.md#Điều 5") == "file.md"
    assert norm_article("Điều  9 khoản 2") == "điều 9"


def _case(cid="c1", org="acme", risks=None, fallbacks=None):
    return AnalysisCase(id=cid, org_id=org, tenant="VN", created_at="2026-06-25T00:00:00Z",
                        lang="vi", contract_excerpt="", summary="", needs_human_review=False,
                        risks=risks or [], fallbacks=fallbacks or [], trace=[])


def test_scan_cases_matches_risk_and_fallback():
    affected = {"nd_123_2020_hoa_don.md": _aff("amends")}      # articles rỗng → doc-level
    case = _case(
        risks=[{"clause": "Hóa đơn", "legal_basis": "nd_123_2020_hoa_don.md#Điều 9: …"}],
        fallbacks=[{"clause": "Hóa đơn", "legal_basis": "nd_123_2020_hoa_don.md#Điều 9: …"}])
    impacts = scan_cases([case], affected, new_doc_id="70/2025/NĐ-CP")
    assert {i.kind for i in impacts} == {"risk", "fallback"}
    assert all(i.relation == "amends" and i.new_doc_id == "70/2025/NĐ-CP" for i in impacts)
    assert all(i.affected_file == "nd_123_2020_hoa_don.md" for i in impacts)


def test_scan_cases_ignores_unaffected_files():
    affected = {"nd_123_2020_hoa_don.md": _aff("amends")}
    case = _case(risks=[{"clause": "Phạt", "legal_basis": "luat_thuong_mai_2005_che_tai.md#Điều 301: …"}])
    assert scan_cases([case], affected) == []


def test_scan_cases_article_level_filters_unchanged_article():
    # VB mới chỉ sửa Điều 9 → case viện dẫn Điều 5 KHÔNG bị cảnh báo (article-level, giảm báo giả).
    affected = {"f.md": _aff("amends", "Điều 9")}
    cited5 = _case(risks=[{"clause": "A", "legal_basis": "f.md#Điều 5: x"}])
    cited9 = _case(cid="c9", risks=[{"clause": "B", "legal_basis": "f.md#Điều 9: y"}])
    assert scan_cases([cited5], affected) == []
    hit = scan_cases([cited9], affected)
    assert len(hit) == 1 and hit[0].affected_article == "điều 9"


def test_scan_cases_dedup_per_clause_file():
    # legal_basis VÀ source cùng trỏ file bị tác động → chỉ báo 1 lần cho (case, kind, clause, file).
    affected = {"f.md": _aff("replaces")}
    case = _case(risks=[{"clause": "X", "legal_basis": "f.md#Điều 1: a", "source": "f.md#Điều 1"}])
    assert len(scan_cases([case], affected)) == 1


def test_scan_cases_empty_affected():
    assert scan_cases([_case()], {}) == []


def test_scan_cases_reads_source_when_no_legal_basis():
    affected = {"f.md": _aff("guides")}
    case = _case(fallbacks=[{"clause": "Y", "source": "f.md#Điều 2: b"}])
    impacts = scan_cases([case], affected)
    assert len(impacts) == 1 and impacts[0].kind == "fallback"


def test_regulatory_impact_endpoint(tmp_path):
    # End-to-end: lưu 1 case viện dẫn NĐ 123/2020 → GET /impact/70/2025 cảnh báo case đó.
    from fastapi.testclient import TestClient

    from legalguard.adapters.inbound.http import build_api
    from legalguard.adapters.outbound.document_parser import PdfDocxParser
    from legalguard.adapters.outbound.revenue_log import CsvRevenueLog
    from legalguard.config.container import build_service
    from legalguard.config.settings import settings
    from legalguard.domain.evidence import EvidenceService

    cfg = settings.model_copy(update={"database_url": f"sqlite:///{tmp_path / 'cases.db'}"})
    service = build_service(cfg)
    service.cases.save(_case(cid="case-x", org="default", risks=[
        {"clause": "Hóa đơn", "risk": "...", "severity": "low",
         "legal_basis": "nd_123_2020_hoa_don.md#Điều 9: thời điểm lập hóa đơn…"}]))
    evidence = EvidenceService(CsvRevenueLog(str(tmp_path / "r.csv")))
    c = TestClient(build_api(service, PdfDocxParser(), evidence, api_orgs={}))

    r = c.get("/impact/70/2025/NĐ-CP")
    assert r.status_code == 200
    body = r.json()
    assert body["impacted_cases"] == 1 and body["case_ids"] == ["case-x"]
    assert body["items"][0]["relation"] == "amends"
    assert body["items"][0]["affected_article"] == "điều 9"   # article-level (NĐ 70 sửa Điều 9)

    # VB không tác động văn bản nào trong KB → rỗng.
    assert c.get("/impact/999/9999/NĐ-CP").json()["impacted_cases"] == 0


def test_format_impact_alert():
    assert format_impact_alert("70/2025/NĐ-CP", []) == ""
    impacts = [
        {"case_id": "c1", "clause": "Hóa đơn", "kind": "risk",
         "affected_file": "nd_123_2020_hoa_don.md", "relation": "amends"},
        {"case_id": "c1", "clause": "Thanh toán", "kind": "fallback",
         "affected_file": "nd_123_2020_hoa_don.md", "relation": "amends"},
        {"case_id": "c2", "clause": "X", "kind": "risk",
         "affected_file": "nd_123_2020_hoa_don.md", "relation": "amends"}]
    impacts[0]["affected_article"] = "điều 9"
    text = format_impact_alert("70/2025/NĐ-CP", impacts)
    assert "70/2025/NĐ-CP" in text
    assert "2 hợp đồng" in text                 # gom theo case (c1+c2)
    assert "Hóa đơn, Thanh toán" in text        # c1 gộp 2 điều khoản 1 dòng
    assert "sửa đổi" in text                    # relation việt hóa
    assert "điều 9" in text                     # điều bị tác động (article-level)


class _FakeSender:
    name = "slack"
    available = True

    def __init__(self):
        self.sent = []

    def send(self, conversation_id, text, thread_ts=None, blocks=None):
        self.sent.append((conversation_id, text))


def test_regulatory_notify_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    from legalguard.adapters.inbound.http import build_api
    from legalguard.adapters.outbound.document_parser import PdfDocxParser
    from legalguard.adapters.outbound.revenue_log import CsvRevenueLog
    from legalguard.config.container import build_service
    from legalguard.config.settings import settings
    from legalguard.domain.evidence import EvidenceService

    cfg = settings.model_copy(update={"database_url": f"sqlite:///{tmp_path / 'cases.db'}"})
    service = build_service(cfg)
    service.cases.save(_case(cid="case-x", org="default", risks=[
        {"clause": "Hóa đơn", "risk": "...", "severity": "low",
         "legal_basis": "nd_123_2020_hoa_don.md#Điều 9: …"}]))
    fake = _FakeSender()
    evidence = EvidenceService(CsvRevenueLog(str(tmp_path / "r.csv")))
    c = TestClient(build_api(service, PdfDocxParser(), evidence, api_orgs={},
                             senders={"slack": fake}))

    r = c.post("/impact/70/2025/NĐ-CP/notify", json={"via": "slack", "channel": "C123"})
    assert r.status_code == 200 and r.json()["sent"] is True
    assert len(fake.sent) == 1 and fake.sent[0][0] == "C123"
    assert "case-x" in fake.sent[0][1]

    # VB không ảnh hưởng → không gửi.
    r2 = c.post("/impact/999/9999/NĐ-CP/notify", json={"via": "slack", "channel": "C123"})
    assert r2.json()["sent"] is False and len(fake.sent) == 1

    # Kênh chưa cấu hình → 400.
    assert c.post("/impact/70/2025/NĐ-CP/notify",
                  json={"via": "zalo", "channel": "U1"}).status_code == 400


def test_affected_doc_files_live_kb():
    # NĐ 70/2025 sửa NĐ 123/2020 → file 123 bị tác động (amends) + điều bị sửa từ front-matter.
    aff = affected_doc_files("knowledge_base", "VN", "70/2025/NĐ-CP")
    info = aff.get("nd_123_2020_hoa_don.md")
    assert info["relation"] == "amends"
    assert "Điều 9" in info["articles"]               # amends_articles khai trong front-matter
    # VB không có trong KB → {}
    assert affected_doc_files("knowledge_base", "VN", "999/9999/NĐ-CP") == {}
