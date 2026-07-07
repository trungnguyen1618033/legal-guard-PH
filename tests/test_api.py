from fastapi.testclient import TestClient

from legalguard.adapters.inbound.http import build_api
from legalguard.adapters.outbound.document_parser import PdfDocxParser
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
    # Trong test, key bị blank → provider ở chế độ stub.
    assert body["qwen_ready"] is False


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


def test_trust_endpoints(client):
    assert client.get("/trust").status_code == 200             # trang công bố
    j = client.get("/trust.json").json()                        # nguồn số liệu (không cần auth)
    assert j["methodology"] and j["metrics"] and j["disclaimer"]


def test_lawyer_consent_endpoint(client):
    # Chế độ luật sư: sinh mẫu văn bản đồng ý điền sẵn (khách cho phép luật sư dùng AI).
    r = client.get("/lawyer/consent", params={"party_a": "Cty ABC", "party_b": "LS An"},
                   headers={"x-tenant-id": "VN"})
    assert r.status_code == 200
    assert "Cty ABC" in r.text and "LS An" in r.text and "VĂN BẢN ĐỒNG Ý" in r.text


def test_amendments_compile_endpoint(client):
    # Phase C: gộp điều khoản đã chọn → memo markdown (illegal lên đầu).
    r = client.post("/amendments/compile", json={"items": [
        {"clause": "Điều 2 phạt 15%", "risk": "vượt trần", "legal_status": "illegal",
         "violated_law": "Điều 301 LTM", "priority": "must_fix"}], "protected_party": "Bên Mua"})
    assert r.status_code == 200
    d = r.json()
    assert d["illegal_count"] == 1 and "TRÁI LUẬT" in d["markdown"] and len(d["rows"]) == 1


def test_negotiate_endpoint(client):
    # Vòng đàm phán đa phiên: bối cảnh deal + tin đối tác → round có status hợp lệ.
    r = client.post("/negotiate", json={"deal_context": "phạt 15% trái Điều 301",
                    "partner_message": "Chúng tôi chỉ giảm phạt còn 12%.", "leverage": "weak",
                    "protected_party": "Bên Mua"}, headers={"x-tenant-id": "VN"})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] in ("continue", "close", "walk_away") and "assessment" in d
    assert "state" in d and "walk_away_recommended" in d          # trả sổ nhượng-bộ + cờ walk-away


def test_negotiate_threads_state_across_rounds(client):
    # Caller truyền state vòng trước → response mang state (agent nhớ đã chốt/nhượng gì qua các vòng).
    r = client.post("/negotiate", json={
        "deal_context": "deal", "partner_message": "ok trọng tài VN",
        "state": {"red_lines": ["trọng tài VN"], "secured": ["phạt 8%"], "conceded": ["gia hạn 5 ngày"]},
    }, headers={"x-tenant-id": "VN"})
    assert r.status_code == 200
    st = r.json()["state"]                                        # stub offline giữ nguyên state đã truyền
    assert "phạt 8%" in st["secured"] and "trọng tài VN" in st["red_lines"]


def test_graph_endpoint_returns_nodes_and_edges(client):
    r = client.get("/graph/123/2020/NĐ-CP", headers={"x-tenant-id": "VN"})
    assert r.status_code == 200
    g = r.json()
    assert g["root"] == "123/2020/NĐ-CP"
    assert any(n["doc_id"] == "70/2025/NĐ-CP" for n in g["nodes"])
    assert g["edges"]


def test_graph_endpoint_404_for_unknown(client):
    assert client.get("/graph/999/9999/NĐ-CP", headers={"x-tenant-id": "VN"}).status_code == 404


def test_latest_endpoint_maps_to_replacement(client):
    r = client.get("/latest/39/2014/TT-BTC", headers={"x-tenant-id": "VN"})
    assert r.status_code == 200
    body = r.json()
    assert body["replaced"] is True and body["latest"] == "123/2020/NĐ-CP"


def test_articles_changed_endpoint(client):
    r = client.get("/articles-changed/123/2020/NĐ-CP", headers={"x-tenant-id": "VN"})
    assert r.status_code == 200
    art = r.json()["amended_articles"]
    assert "Điều 9" in art and "70/2025/NĐ-CP" in art["Điều 9"]


def test_analyze_accepts_protected_party_and_returns_legal_status(client):
    # Phase A: /analyze nhận 'protected_party', mỗi risk có legal_status hợp lệ + tách illegal.
    contract = "Phạt vi phạm 15% giá trị hợp đồng. Trọng tài tại Bắc Kinh. Thanh toán T/T 60 ngày."
    r = client.post("/analyze", data={"text": contract, "protected_party": "Bên Vay"},
                    headers={"x-tenant-id": "VN"})
    assert r.status_code == 200
    risks = r.json()["risks"]
    assert risks and all(x["legal_status"] in ("illegal", "unfavorable") for x in risks)
    illegal = [x for x in risks if x["legal_status"] == "illegal"]
    assert illegal and illegal[0]["violated_law"]        # stub có 1 điều khoản trái luật kèm điều luật


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


def test_lookup_ui_page_served(client):
    r = client.get("/lookup")
    assert r.status_code == 200
    assert "tra cứu" in r.text.lower()         # trang tra cứu luật
    assert "Lược đồ văn bản" in r.text and "loadGraph" in r.text   # section lược đồ (graph UI)


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


def test_analyze_returns_execution_summary(client, sample_contract):
    # Evidence AI-Native: phản hồi /analyze kèm đếm tool-call agent đã gọi.
    d = client.post("/analyze", data={"text": sample_contract}, headers={"x-tenant-id": "VN"}).json()
    es = d["execution_summary"]
    assert es["total_tool_calls"] >= 1
    assert es["risks_flagged"] == 3                 # 3 risk → 3 lần gọi flag_risk
    assert es["total_tool_calls"] == len(d["trace"])  # khớp số bước trong trace


def test_runs_feed_lists_agent_activity(client, sample_contract):
    # /runs = feed hoạt động agent (cho giám khảo NHÌN THẤY agent chạy & ra quyết định).
    case_id = client.post("/analyze", data={"text": sample_contract},
                          headers={"x-tenant-id": "VN"}).json()["case_id"]
    runs = client.get("/runs").json()
    assert runs["totals"]["runs"] >= 1
    assert runs["totals"]["tool_calls"] >= 1
    assert runs["totals"]["by_tool"]["risks_flagged"] >= 3
    assert any(r["case_id"] == case_id and r["tool_calls"] >= 1 for r in runs["runs"])


def test_analyze_async_mode_returns_case_id_then_pollable(client, sample_contract):
    # HĐ dài → async_mode: trả case_id + status 'processing' NGAY (không chờ phân tích);
    # chạy nền → poll GET /cases/{id} ra 200. (TestClient chạy BackgroundTask sau response.)
    r = client.post("/analyze", data={"text": sample_contract, "async_mode": "true"},
                    headers={"x-tenant-id": "VN"})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "processing" and d["case_id"]
    # poll /analyze/result/{id} → full result shape (risks + strategy...). TestClient chạy BG sau response.
    got = client.get(f"/analyze/result/{d['case_id']}")
    assert got.status_code == 200
    assert got.json()["case_id"] == d["case_id"] and "risks" in got.json()
    # case cũng lưu DB với ĐÚNG case_id (audit)
    assert client.get(f"/cases/{d['case_id']}").status_code == 200


def test_landing_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Legal Guard" in r.text


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
        kb=FileKnowledgeBaseProvider("knowledge_base"),
    )
    evidence = EvidenceService(CsvRevenueLog(str(tmp_path / "rev.csv")))
    api = build_api(service, PdfDocxParser(), evidence)
    r = TestClient(api).post("/analyze", data={"text": sample_contract}, headers={"x-tenant-id": "VN"})
    assert r.status_code == 502
    detail = r.json()["detail"].lower()
    assert "qwen" in detail and "http" in detail
    assert "key" not in detail  # KHÔNG lộ key/URL


def test_docs_page_served(client):
    r = client.get("/tai-lieu")
    assert r.status_code == 200 and "Legal Guard" in r.text
