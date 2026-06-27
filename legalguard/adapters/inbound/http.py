"""Inbound (driving) adapter: HTTP API bằng FastAPI.

Bảo mật: API key (X-API-Key) → Organization (công ty); mọi truy vấn cases bị ràng theo
`org_id` của caller (cô lập THEO CÔNG TY, không theo quốc gia). api_orgs rỗng = auth tắt (dev),
khi đó dùng org "default" (quốc gia lấy từ header X-Tenant-Id).
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel

from legalguard.domain.analysis import AnalysisService
from legalguard.domain.evidence import EvidenceService
from legalguard.domain.models import (
    Feedback,
    NegotiationPosition,
    Outcome,
    RevenueEntry,
    SourceMeta,
)
from legalguard.domain.ports import DocumentParserPort, LLMError
from legalguard.domain.redline import change_ratio, redline
from legalguard.domain.reporting import render_markdown_report
from legalguard.domain.tenants import Organization, default_org, get_tenant

_LANDING = Path("web/index.html")
_APP = Path("web/app.html")
_LOOKUP = Path("web/lookup.html")
_DASHBOARD = Path("web/dashboard.html")


class RevenueIn(BaseModel):
    customer: str
    date: str
    amount_usd: float
    contract_ref: str = ""
    testimonial: str = ""
    related_party: bool = False


class OutcomeIn(BaseModel):
    clause: str
    tactic: str = ""
    result: str = "pending"     # accepted | partial | rejected | pending


class AskIn(BaseModel):
    question: str
    lang: str = "vi"            # vi | en


class RedlineIn(BaseModel):
    old: str                    # phiên bản cũ
    new: str                    # phiên bản mới


class CounterIn(BaseModel):
    clause: str                 # điều khoản gốc (đối tác áp)
    risk: str = ""              # rủi ro với DN Việt
    suggestion: str = ""        # hướng thỏa hiệp mong muốn
    legal_basis: str = ""       # căn cứ pháp lý (nếu đã có từ /analyze)
    leverage: str = "balanced"  # vị thế đàm phán: strong | balanced | weak


class AlertIn(BaseModel):
    via: str                    # slack | zalo
    channel: str                # Slack channel ID hoặc Zalo user_id nhận cảnh báo
    limit: int = 200            # số case quét tối đa


class FeedbackIn(BaseModel):
    kind: str = "lookup"        # analysis | lookup
    ref: str = ""               # case_id (analysis) hoặc câu hỏi (lookup)
    rating: str                 # helpful | wrong | incomplete
    note: str = ""


def build_api(service: AnalysisService, parser: DocumentParserPort, evidence: EvidenceService,
              default_tenant: str = "VN", api_orgs: dict[str, Organization] | None = None,
              max_upload_bytes: int = 10 * 1024 * 1024, rate_limit_per_min: int = 60,
              max_input_chars: int = 50_000,
              senders: dict | None = None) -> FastAPI:
    app = FastAPI(title="Legal Guard PH", version="0.6.0")
    orgs = api_orgs or {}
    _senders = senders or {}        # {"slack": ChatSenderPort, "zalo": ChatSenderPort} — gửi cảnh báo chủ động
    _hits: dict[tuple, int] = {}   # rate limit in-process (prod → Redis; per-worker)
    _hits_lock = threading.Lock()

    def _rate_ok(key: str) -> bool:
        if rate_limit_per_min <= 0:
            return True
        window = int(time.monotonic() // 60)
        with _hits_lock:
            for k in list(_hits):          # snapshot → tránh "dict changed during iteration"
                if k[1] != window:
                    del _hits[k]
            _hits[(key, window)] = _hits.get((key, window), 0) + 1
            return _hits[(key, window)] <= rate_limit_per_min

    def require_auth(x_api_key: str = Header(default=None),
                     x_tenant_id: str = Header(default=None)) -> Organization:
        """Trả Organization của caller + rate limit. Auth bật → từ API key (401 nếu sai)."""
        if not _rate_ok(x_api_key or "anon"):
            raise HTTPException(status_code=429, detail="Quá nhiều yêu cầu, thử lại sau.")
        if orgs:
            org = orgs.get(x_api_key or "")
            if org is None:
                raise HTTPException(status_code=401, detail="API key không hợp lệ.")
            return org
        return default_org(x_tenant_id or default_tenant)

    @app.get("/", response_class=HTMLResponse)
    def landing():
        if _LANDING.exists():
            return FileResponse(_LANDING)
        return HTMLResponse("<h1>Legal Guard PH</h1><p>API: /docs</p>")

    @app.get("/app", response_class=HTMLResponse)
    def demo_app():
        # UI demo: upload → risk → fallback → human checkpoint (Approve/Reject).
        if _APP.exists():
            return FileResponse(_APP)
        return HTMLResponse("<h1>Legal Guard PH</h1><p>UI chưa được cài. API: /docs</p>")

    @app.get("/lookup", response_class=HTMLResponse)
    def lookup_ui():
        # UI tra cứu luật: câu hỏi → /ask → câu trả lời dẫn điều/khoản còn hiệu lực + nguồn.
        if _LOOKUP.exists():
            return FileResponse(_LOOKUP)
        return HTMLResponse("<h1>Legal Guard PH</h1><p>UI tra cứu chưa được cài. API: /ask</p>")

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard_ui():
        # UI system-of-record: tổng hợp hoạt động pháp lý của công ty → /insights/dashboard.
        if _DASHBOARD.exists():
            return FileResponse(_DASHBOARD)
        return HTMLResponse("<h1>Legal Guard PH</h1><p>UI bảng điều khiển chưa cài. API: /insights/dashboard</p>")

    @app.get("/health")
    def health() -> dict:           # liveness
        return service.health()

    @app.get("/ready")
    def ready() -> dict:            # readiness (DB) — cho LB/k8s
        if service.ready():
            return {"ready": True}
        raise HTTPException(status_code=503, detail="DB chưa sẵn sàng.")

    @app.post("/analyze")
    async def analyze(
        text: str | None = Form(default=None),
        file: UploadFile | None = File(default=None),
        format: str = Form(default="json"),
        lang: str = Form(default="en"),
        leverage: str = Form(default="balanced"),
        urgency: str = Form(default="low"),
        relationship: str = Form(default="new"),
        alternatives: bool = Form(default=False),
        protected_party: str = Form(default=""),
        org: Organization = Depends(require_auth),
    ):
        lang = lang if lang in ("en", "vi") else "en"
        position = NegotiationPosition(leverage=leverage, urgency=urgency,
                                       relationship=relationship, alternatives=alternatives,
                                       protected_party=protected_party[:120])

        source = None
        if file is not None:
            data = await file.read()
            if len(data) > max_upload_bytes:
                raise HTTPException(status_code=413, detail="File quá lớn.")
            source = SourceMeta.of(data, file.filename or "")   # audit: hash file gốc
            try:
                contract_text = parser.extract_text(data, file.filename or "")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from None
        elif text:
            contract_text = text
        else:
            raise HTTPException(status_code=400, detail="Cần cung cấp `text` hoặc `file`.")

        if not contract_text.strip():
            raise HTTPException(status_code=400, detail="Không trích được nội dung hợp đồng.")
        if len(contract_text) > max_input_chars:
            raise HTTPException(status_code=413,
                                detail=f"Nội dung quá dài (>{max_input_chars} ký tự).")

        try:
            # service.analyze ĐỒNG BỘ (HTTP blocking + ThreadPool) → đẩy sang threadpool để KHÔNG
            # chặn event loop (handler async vì phải await file.read()). 1 phân tích chậm không treo worker.
            result = await run_in_threadpool(service.analyze, contract_text, org, lang=lang,
                                             position=position, source=source)
        except ValueError as exc:        # quốc gia chưa hỗ trợ
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except LLMError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None

        if format == "report":
            tenant = get_tenant(org.country)
            return PlainTextResponse(render_markdown_report(result, tenant, lang),
                                     media_type="text/markdown")
        return result.__dict__

    @app.post("/ask")
    def ask(body: AskIn, org: Organization = Depends(require_auth)) -> dict:
        """Tra cứu pháp luật có grounding (không cần hợp đồng): câu hỏi → câu trả lời dẫn đúng
        điều/khoản còn hiệu lực + danh sách nguồn."""
        lang = body.lang if body.lang in ("en", "vi") else "vi"
        if not body.question.strip():
            raise HTTPException(status_code=400, detail="Cần cung cấp `question`.")
        if len(body.question) > max_input_chars:
            raise HTTPException(status_code=413, detail=f"Câu hỏi quá dài (>{max_input_chars} ký tự).")
        try:
            answer, snippets = service.lookup(body.question, org, lang=lang)
        except LLMError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        return {"answer": answer, "sources": [s.source for s in snippets]}

    @app.post("/evidence/revenue")
    def record_revenue(body: RevenueIn, _: Organization = Depends(require_auth)) -> dict:
        evidence.record_revenue(RevenueEntry(**body.model_dump()))
        return {"ok": True}

    @app.get("/evidence/summary")
    def evidence_summary(_: Organization = Depends(require_auth)) -> dict:
        return evidence.summary()

    @app.get("/cases")
    def list_cases(limit: int = 20, org: Organization = Depends(require_auth)) -> list[dict]:
        return [asdict(c) for c in service.list_cases(org.id, limit)]

    @app.get("/cases/{case_id}")
    def get_case(case_id: str, org: Organization = Depends(require_auth)) -> dict:
        case = service.get_case(case_id)
        if case is None or case.org_id != org.id:        # cô lập theo công ty
            raise HTTPException(status_code=404, detail="Không tìm thấy case.")
        return asdict(case)

    @app.delete("/cases/{case_id}")
    def delete_case(case_id: str, org: Organization = Depends(require_auth)) -> dict:
        case = service.get_case(case_id)
        if case is None or case.org_id != org.id:        # chỉ xóa case của chính công ty
            raise HTTPException(status_code=404, detail="Không tìm thấy case.")
        return {"deleted": service.delete_case(case_id)}

    @app.post("/cases/{case_id}/outcome")
    def record_outcome(case_id: str, body: OutcomeIn,
                       org: Organization = Depends(require_auth)) -> dict:
        # Flywheel: ghi kết quả đàm phán thực tế (dữ liệu độc quyền).
        if body.result not in ("accepted", "partial", "rejected", "pending"):
            raise HTTPException(status_code=400, detail="result không hợp lệ.")
        case = service.get_case(case_id)
        if case is None or case.org_id != org.id:
            raise HTTPException(status_code=404, detail="Không tìm thấy case.")
        service.record_outcome(Outcome(
            id=uuid.uuid4().hex, org_id=org.id, case_id=case_id,
            clause=body.clause, tactic=body.tactic, result=body.result,
            created_at=datetime.now(timezone.utc).isoformat(),
        ))
        return {"ok": True}

    @app.get("/insights/tactics")
    def tactic_insights(org: Organization = Depends(require_auth)) -> dict:
        # Win-rate theo điều khoản từ flywheel kết quả đàm phán của công ty.
        return service.tactic_stats(org.id)

    @app.get("/insights/dashboard")
    async def org_dashboard(limit: int = 200, org: Organization = Depends(require_auth)) -> dict:
        # System-of-record: tổng hợp HĐ đã rà soát, rủi ro hay gặp, tín hiệu feedback, win-rate chiến thuật.
        return await run_in_threadpool(service.dashboard, org.id, limit)

    @app.post("/feedback")
    def submit_feedback(body: FeedbackIn, org: Organization = Depends(require_auth)) -> dict:
        # Vòng học: phản hồi người dùng về câu trả lời → gom golden set + tìm lỗ hổng KB.
        if body.rating not in ("helpful", "wrong", "incomplete"):
            raise HTTPException(status_code=400, detail="rating không hợp lệ.")
        fid = service.record_feedback(Feedback(
            id=uuid.uuid4().hex, org_id=org.id, kind=body.kind, ref=body.ref[:500],
            rating=body.rating, note=body.note[:1000],
            created_at=datetime.now(timezone.utc).isoformat(),
        ))
        return {"recorded": fid is not None, "id": fid}

    @app.get("/feedback")
    def list_feedback(limit: int = 100, org: Organization = Depends(require_auth)) -> list[dict]:
        # Xuất phản hồi của công ty (để build golden set / rà lỗ hổng).
        return [asdict(f) for f in service.list_feedback(org.id, limit)]

    @app.get("/changes/{doc_id:path}")
    def doc_changes(doc_id: str, org: Organization = Depends(require_auth)) -> dict:
        # "What changed" cấp văn bản: VB này được sửa đổi/thay thế bởi (hoặc của) VB nào, khi nào.
        cl = service.kb.changelog(doc_id, org.country)
        if cl is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy văn bản trong KB.")
        return cl

    @app.get("/graph/{doc_id:path}")
    def doc_graph(doc_id: str, depth: int = 1, org: Organization = Depends(require_auth)) -> dict:
        # Lược đồ văn bản (như TVPL): {nodes, edges} mở rộng quan hệ tới `depth` hop (giới hạn 1-3).
        g = service.kb.graph(doc_id, org.country, depth=max(1, min(depth, 3)))
        if g is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy văn bản trong KB.")
        return g

    @app.get("/latest/{doc_id:path}")
    def doc_latest(doc_id: str, org: Organization = Depends(require_auth)) -> dict:
        # Map tới VĂN BẢN MỚI NHẤT (theo chuỗi replaced_by) — VB cũ → bản thay thế hiện hành.
        lv = service.kb.latest(doc_id, org.country)
        if lv is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy văn bản trong KB.")
        return lv

    @app.get("/articles-changed/{doc_id:path}")
    def doc_articles_changed(doc_id: str, org: Organization = Depends(require_auth)) -> dict:
        # 'Bôi vàng' kiểu TVPL: đọc luật này → ĐIỀU nào đã bị VB khác sửa + bởi VB nào.
        aa = service.kb.amended_articles(doc_id, org.country)
        if aa is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy văn bản trong KB.")
        return aa

    @app.get("/impact/{doc_id:path}")
    def regulatory_impact(doc_id: str, limit: int = 200,
                          org: Organization = Depends(require_auth)) -> dict:
        # Chủ động: VB pháp luật MỚI `doc_id` → case nào của công ty viện dẫn văn bản nó vừa
        # sửa đổi/thay thế/hướng dẫn → cần rà soát lại. [] = không ảnh hưởng / chưa có case.
        impacts = service.regulatory_impact(doc_id, org.country, org.id, limit=limit)
        cases = sorted({i["case_id"] for i in impacts})
        return {"doc_id": doc_id.strip(), "impacted_cases": len(cases),
                "case_ids": cases, "items": impacts}

    @app.post("/impact/{doc_id:path}/notify")
    def regulatory_notify(doc_id: str, body: AlertIn,
                          org: Organization = Depends(require_auth)) -> dict:
        # Quét ảnh hưởng VB mới + GỬI cảnh báo chủ động qua Slack/Zalo (nếu có hợp đồng bị ảnh hưởng).
        from legalguard.domain.regulatory import format_impact_alert

        sender = _senders.get(body.via)
        if sender is None or not getattr(sender, "available", False):
            raise HTTPException(status_code=400, detail=f"Kênh '{body.via}' chưa cấu hình.")
        impacts = service.regulatory_impact(doc_id, org.country, org.id, limit=body.limit)
        cases = sorted({i["case_id"] for i in impacts})
        if not cases:
            return {"doc_id": doc_id.strip(), "impacted_cases": 0, "sent": False}
        text = format_impact_alert(doc_id, impacts)
        try:
            sender.send(body.channel, text)
        except Exception as exc:  # noqa: BLE001 — gửi lỗi không nên 500, báo rõ cho caller
            raise HTTPException(status_code=502, detail=f"Gửi {body.via} thất bại: {exc}") from exc
        return {"doc_id": doc_id.strip(), "impacted_cases": len(cases),
                "case_ids": cases, "sent": True, "via": body.via}

    @app.post("/counter")
    async def counter_clause(body: CounterIn, _: Organization = Depends(require_auth)) -> dict:
        # Soạn điều khoản phản-đề song ngữ VN/EN (dán vào HĐ) cho 1 điều khoản rủi ro.
        if len(body.clause) > max_input_chars:
            raise HTTPException(status_code=413, detail="Nội dung quá dài.")
        try:
            return await run_in_threadpool(
                service.draft_counter_clause, body.clause, body.risk, body.suggestion,
                body.legal_basis, body.leverage)
        except LLMError as exc:
            raise HTTPException(status_code=502, detail=f"LLM lỗi: {exc}") from exc

    @app.post("/redline")
    def text_redline(body: RedlineIn, _: Organization = Depends(require_auth)) -> dict:
        # So 2 phiên bản text → redline ([+thêm+]/[-bỏ-]) + tỉ lệ giống nhau. Tất định, không LLM.
        if len(body.old) > max_input_chars or len(body.new) > max_input_chars:
            raise HTTPException(status_code=413, detail="Nội dung quá dài.")
        return {"redline": redline(body.old, body.new), "similarity": change_ratio(body.old, body.new)}

    return app
