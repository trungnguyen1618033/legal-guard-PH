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
from legalguard.domain.models import NegotiationPosition, Outcome, RevenueEntry, SourceMeta
from legalguard.domain.ports import DocumentParserPort, LLMError
from legalguard.domain.reporting import render_markdown_report
from legalguard.domain.tenants import Organization, default_org, get_tenant

_LANDING = Path("web/index.html")
_APP = Path("web/app.html")


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


def build_api(service: AnalysisService, parser: DocumentParserPort, evidence: EvidenceService,
              default_tenant: str = "VN", api_orgs: dict[str, Organization] | None = None,
              max_upload_bytes: int = 10 * 1024 * 1024, rate_limit_per_min: int = 60,
              max_input_chars: int = 50_000) -> FastAPI:
    app = FastAPI(title="Legal Guard PH", version="0.6.0")
    orgs = api_orgs or {}
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
        org: Organization = Depends(require_auth),
    ):
        lang = lang if lang in ("en", "vi") else "en"
        position = NegotiationPosition(leverage=leverage, urgency=urgency,
                                       relationship=relationship, alternatives=alternatives)

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

    return app
