from fastapi.testclient import TestClient

from legalguard.adapters.inbound.http import build_api
from legalguard.adapters.outbound.document_parser import PdfDocxParser
from legalguard.adapters.outbound.revenue_log import CsvRevenueLog
from legalguard.config.container import build_service
from legalguard.domain.agent import _SYSTEM
from legalguard.domain.evidence import EvidenceService
from legalguard.domain.redaction import redact
from legalguard.domain.tenants import Organization


def _client(tmp_path, api_orgs=None, max_upload_bytes=10 * 1024 * 1024, rate_limit_per_min=60):
    evidence = EvidenceService(CsvRevenueLog(str(tmp_path / "r.csv")))
    return TestClient(build_api(build_service(), PdfDocxParser(), evidence,
                                api_orgs=api_orgs or {}, max_upload_bytes=max_upload_bytes,
                                rate_limit_per_min=rate_limit_per_min))


# ---- Redaction PII ----
def test_redact_masks_contact_pii_but_keeps_business_terms():
    text = "Liên hệ a@b.com, ĐT 0901234567. Arbitration in Beijing, T/T 60 days."
    out, n = redact(text)
    assert "[EMAIL]" in out and "[SỐ]" in out
    assert n >= 2
    assert "a@b.com" not in out and "0901234567" not in out
    assert "Arbitration" in out and "60 days" in out      # từ nghiệp vụ + số ngắn giữ nguyên


def test_redact_covers_vn_personal_identifiers():
    # Guarantee PDPL: định danh cá nhân VN (CCCD 12 số, MST, số TK) bị che TRƯỚC khi gửi mô hình;
    # số pháp lý (Điều, %, số ngày) KHÔNG bị che → không hỏng phân tích. Xem docs/internal/compliance-pdpl/.
    out, n = redact("CCCD 079201001234, MST 0312345678-001, STK 19001234567890. Điều 301, phạt 8%, 60 ngày.")
    assert "079201001234" not in out and "0312345678" not in out and "19001234567890" not in out
    assert n >= 3
    assert "Điều 301" in out and "8%" in out and "60 ngày" in out


def test_analyze_notes_redaction(tmp_path):
    c = _client(tmp_path)
    d = c.post("/analyze", data={"text": "Email x@y.com. Arbitration in Beijing."},
               headers={"x-tenant-id": "VN"}).json()
    assert any("ẩn" in n for n in d["notes"])             # có ghi nhận đã ẩn PII


# ---- Auth + tenant scoping ----
def test_auth_rejects_missing_and_wrong_key(tmp_path):
    c = _client(tmp_path, api_orgs={"acmekey": Organization(id="acme", country="VN")})
    assert c.get("/evidence/summary").status_code == 401                       # thiếu key
    assert c.get("/evidence/summary", headers={"x-api-key": "bad"}).status_code == 401
    assert c.get("/evidence/summary", headers={"x-api-key": "acmekey"}).status_code == 200


def test_company_scoping_blocks_cross_company_read(tmp_path):
    # Hai công ty cùng quốc gia VN — phải cô lập theo công ty.
    c = _client(tmp_path, api_orgs={"acmekey": Organization(id="acme", country="VN"),
                                    "globexkey": Organization(id="globex", country="VN")})
    d = c.post("/analyze", data={"text": "Arbitration in Beijing."},
               headers={"x-api-key": "acmekey"}).json()
    cid = d["case_id"]
    assert c.get(f"/cases/{cid}", headers={"x-api-key": "acmekey"}).status_code == 200
    assert c.get(f"/cases/{cid}", headers={"x-api-key": "globexkey"}).status_code == 404  # chống đọc chéo


# ---- /ask (tra cứu luật) auth + redaction ----
def test_ask_requires_auth(tmp_path):
    c = _client(tmp_path, api_orgs={"acmekey": Organization(id="acme", country="VN")})
    assert c.post("/ask", json={"question": "phạt vi phạm hợp đồng"}).status_code == 401   # thiếu key
    assert c.post("/ask", json={"question": "phạt vi phạm hợp đồng"},
                  headers={"x-api-key": "acmekey"}).status_code == 200


def test_lookup_redacts_pii_in_question():
    # Câu hỏi pháp lý có PII → redact TRƯỚC khi tra/đưa LLM (data minimization).
    from legalguard.domain.analysis import _legal_citation  # noqa: F401 (đảm bảo import được)
    out, n = redact("Tôi là a@b.com hỏi về phạt vi phạm hợp đồng")
    assert "[EMAIL]" in out and n >= 1


# ---- Fail-closed khi require_auth + API_KEYS rỗng ----
def test_require_auth_fail_closed_refuses_open_boot(monkeypatch):
    from legalguard.config import container
    from legalguard.config.settings import Settings
    cfg = Settings(api_keys="", require_auth=True)
    import pytest
    with pytest.raises(RuntimeError):
        container.build_app(cfg)        # API_KEYS rỗng + require_auth → từ chối khởi động


# ---- Cap độ dài input (chống abuse chi phí) ----
def test_input_length_cap(tmp_path):
    c = _client(tmp_path, max_upload_bytes=10 * 1024 * 1024)
    big = "x" * 60000
    # /analyze text quá dài → 413
    r1 = c.post("/analyze", data={"text": big}, headers={"x-tenant-id": "VN"})
    assert r1.status_code == 413
    # /ask câu hỏi quá dài → 413
    r2 = c.post("/ask", json={"question": big}, headers={"x-tenant-id": "VN"})
    assert r2.status_code == 413


# ---- File upload limit ----
def test_upload_size_limit(tmp_path):
    c = _client(tmp_path, max_upload_bytes=10)
    r = c.post("/analyze", files={"file": ("c.txt", b"x" * 50, "text/plain")},
               headers={"x-tenant-id": "VN"})
    assert r.status_code == 413


# ---- Right-to-erasure ----
def test_delete_case_erasure(tmp_path):
    c = _client(tmp_path)
    cid = c.post("/analyze", data={"text": "Arbitration in Beijing."},
                 headers={"x-tenant-id": "VN"}).json()["case_id"]
    assert c.delete(f"/cases/{cid}").json() == {"deleted": True}
    assert c.get(f"/cases/{cid}").status_code == 404


def test_delete_case_cascades_outcomes_and_feedback(tmp_path):
    # Right-to-erasure (PDPD): xóa case → CASCADE outcomes + feedback, không để orphan dữ liệu cá nhân.
    from legalguard.config.settings import settings
    from legalguard.domain.models import AnalysisCase, Feedback, Outcome

    svc = build_service(settings.model_copy(
        update={"database_url": f"sqlite:///{tmp_path / 'erase.db'}"}))
    svc.cases.save(AnalysisCase(id="c1", org_id="default", tenant="VN", created_at="t", lang="vi",
                   contract_excerpt="", summary="", needs_human_review=False, risks=[],
                   fallbacks=[{"clause": "X"}], trace=[]))
    svc.record_outcome(Outcome(id="o1", org_id="default", case_id="c1", clause="X", tactic="",
                               result="accepted", created_at="t"))
    svc.record_feedback(Feedback(id="f1", org_id="default", kind="analysis", ref="c1",
                                 rating="helpful", note="", created_at="t"))
    assert svc.tactic_stats("default") and svc.list_feedback("default")   # có dữ liệu trước xóa
    assert svc.delete_case("c1") is True
    assert svc.tactic_stats("default") == {} and svc.list_feedback("default") == []  # sạch orphan
    assert svc.get_case("c1") is None


# ---- Rate limiting ----
def test_rate_limit_returns_429(tmp_path):
    c = _client(tmp_path, rate_limit_per_min=2)
    assert c.get("/evidence/summary").status_code == 200
    assert c.get("/evidence/summary").status_code == 200
    assert c.get("/evidence/summary").status_code == 429   # vượt giới hạn


# ---- Prompt-injection hardening ----
def test_system_prompt_marks_contract_untrusted():
    assert "UNTRUSTED" in _SYSTEM["en"]
    assert "KHÔNG TIN CẬY" in _SYSTEM["vi"]
