from fastapi.testclient import TestClient

from legalguard.adapters.inbound.http import build_api
from legalguard.adapters.outbound.document_parser import PdfDocxParser
from legalguard.adapters.outbound.gemini import GeminiAdapter
from legalguard.adapters.outbound.knowledge_base import FileKnowledgeBaseProvider
from legalguard.adapters.outbound.revenue_log import CsvRevenueLog
from legalguard.config.container import build_service
from legalguard.domain.analysis import AnalysisService
from legalguard.domain.evidence import EvidenceService
from legalguard.domain.models import ChatTurn
from legalguard.domain.ports import LLMError, LLMPort


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    # Trong test, key bị blank → cả hai provider ở chế độ stub.
    assert body["qwen_ready"] is False
    assert body["gemini_ready"] is False


def test_analyze_returns_structured_result(client, sample_contract):
    r = client.post("/analyze", data={"text": sample_contract}, headers={"x-tenant-id": "VN"})
    assert r.status_code == 200
    d = r.json()
    assert d["tenant"] == "VN"
    assert len(d["risks"]) == 3
    assert len(d["fallbacks"]) == 3                      # mỗi rủi ro có fallback
    assert d["fallbacks"][0]["english_reply"]            # kèm câu đàm phán tiếng Anh
    assert d["needs_human_review"] is True
    assert [s["tool"] for s in d["trace"]]  # có execution trace


def test_analyze_requires_input(client):
    assert client.post("/analyze").status_code == 400


def test_ask_returns_grounded_answer_with_sources(client):
    r = client.post("/ask", json={"question": "thời điểm lập hóa đơn", "lang": "vi"})
    assert r.status_code == 200
    d = r.json()
    assert "answer" in d and isinstance(d["sources"], list)
    assert d["sources"]                                  # có nguồn KB (tra cứu thật)


def test_ask_requires_question(client):
    assert client.post("/ask", json={"question": "   "}).status_code == 400


def test_ready_probe(client):
    r = client.get("/ready")
    assert r.status_code == 200 and r.json() == {"ready": True}


def test_demo_app_page_served(client):
    r = client.get("/app")
    assert r.status_code == 200
    assert "checkpoint" in r.text.lower()      # UI có human checkpoint (Autopilot Agent)


def test_analyze_persists_case_and_can_fetch(client, sample_contract):
    d = client.post("/analyze", data={"text": sample_contract},
                    headers={"x-tenant-id": "VN"}).json()
    case_id = d["case_id"]
    assert case_id                                  # đã lưu

    got = client.get(f"/cases/{case_id}")
    assert got.status_code == 200
    assert got.json()["tenant"] == "VN"
    assert got.json()["contract_excerpt"]           # có trích đoạn

    listing = client.get("/cases", params={"tenant": "VN"}).json()
    assert any(c["id"] == case_id for c in listing)


def test_get_unknown_case_404(client):
    assert client.get("/cases/doesnotexist").status_code == 404


def test_landing_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Legal Guard PH" in r.text


def test_analyze_report_format_default_english(client, sample_contract):
    r = client.post("/analyze", data={"text": sample_contract, "format": "report"},
                    headers={"x-tenant-id": "VN"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert "Contract Review Report" in r.text       # mặc định EN


def test_analyze_report_vietnamese(client, sample_contract):
    r = client.post("/analyze", data={"text": sample_contract, "format": "report", "lang": "vi"},
                    headers={"x-tenant-id": "VN"})
    assert r.status_code == 200
    assert "Báo cáo Rà soát Hợp đồng" in r.text      # chế độ VN


def test_evidence_endpoints(tmp_path, sample_contract):
    evidence = EvidenceService(CsvRevenueLog(str(tmp_path / "rev.csv")))
    api = build_api(build_service(), PdfDocxParser(), evidence)
    c = TestClient(api)

    assert c.post("/evidence/revenue", json={
        "customer": "SME A", "date": "2026-06-10", "amount_usd": 50,
        "testimonial": "Hữu ích",
    }).json() == {"ok": True}

    s = c.get("/evidence/summary").json()
    assert s["total_usd"] == 50.0
    assert s["paying_customers"] == 1
    assert s["by_month"]["2026-06"] == 50.0


def test_analyze_unknown_tenant(client, sample_contract):
    r = client.post("/analyze", data={"text": sample_contract}, headers={"x-tenant-id": "ZZ"})
    assert r.status_code == 400  # tenant chưa hỗ trợ → lỗi client, không crash


class _BoomLLM(LLMPort):
    """Reasoner giả luôn ném LLMError để test xử lý lỗi provider."""
    name = "qwen"

    @property
    def available(self) -> bool:
        return True

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        return ""

    def chat(self, messages, *, tools=None) -> ChatTurn:
        raise LLMError("qwen", "HTTP 429")


def test_analyze_llm_error_returns_502_without_leaking_key(tmp_path, sample_contract):
    service = AnalysisService(
        reasoner=_BoomLLM(),
        summarizer=GeminiAdapter("", "gemini-2.0-flash"),
        kb=FileKnowledgeBaseProvider("knowledge_base"),
    )
    evidence = EvidenceService(CsvRevenueLog(str(tmp_path / "rev.csv")))
    api = build_api(service, PdfDocxParser(), evidence)
    r = TestClient(api).post("/analyze", data={"text": sample_contract}, headers={"x-tenant-id": "VN"})
    assert r.status_code == 502
    detail = r.json()["detail"].lower()
    assert "qwen" in detail and "http" in detail
    assert "key" not in detail  # KHÔNG lộ key/URL
