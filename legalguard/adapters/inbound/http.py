"""Inbound (driving) adapter: HTTP API bằng FastAPI.

Bảo mật: API key (X-API-Key) → Organization (công ty); mọi truy vấn cases bị ràng theo
`org_id` của caller (cô lập THEO CÔNG TY, không theo quốc gia). api_orgs rỗng = auth tắt (dev),
khi đó dùng org "default" (quốc gia lấy từ header X-Tenant-Id).
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
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

_log = logging.getLogger(__name__)

# Cache KẾT QUẢ phân tích nền (async_mode) — {case_id: (org_id, result_dict)} để client poll lấy FULL
# result shape (strategy/english_reply/notes — case DB không lưu). In-memory: hợp 1 instance (deploy hiện
# tại); mất khi restart (case vẫn ở DB cho audit). Đa-instance/bền → chuyển Redis.
_async_results: "OrderedDict[str, tuple]" = OrderedDict()
_async_lock = threading.Lock()


def _async_put(cid: str, org_id: str, result: dict) -> None:
    with _async_lock:
        _async_results[cid] = (org_id, result)
        while len(_async_results) > 50:          # cap — giữ 50 job gần nhất
            _async_results.popitem(last=False)


def _async_get(cid: str, org_id: str) -> dict | None:
    with _async_lock:
        v = _async_results.get(cid)
    return v[1] if v and v[0] == org_id else None   # cô lập theo org


_LANDING = Path("web/index.html")
_APP = Path("web/app.html")
_LOOKUP = Path("web/lookup.html")
_DASHBOARD = Path("web/dashboard.html")
_TRUST = Path("web/trust.html")
_DOCS = Path("web/docs.html")
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


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


class CompileIn(BaseModel):
    items: list[dict]           # điều khoản đã chọn (risk/fallback, có thể sửa tay): clause/issue/...
    title: str = ""
    protected_party: str = ""


class EscalateIn(BaseModel):
    case_id: str = ""           # case cần chuyển (nếu có) — kèm số rủi ro/illegal
    reason: str = ""            # vì sao escalate (reviewer reject / illegal / nghi ngờ)
    via: str = "slack"
    channel: str = ""           # rỗng → dùng kênh chuyên gia cấu hình sẵn (EXPERT_CHANNEL)


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


class NegoStateIn(BaseModel):
    """Sổ nhượng-bộ vòng trước — caller thread qua các vòng (web/API) để agent nhớ đã nhượng/chốt gì."""
    red_lines: list[str] = []       # điểm must-fix KHÔNG nhượng (seed từ /analyze)
    secured: list[str] = []         # đối tác đã đồng ý
    conceded: list[str] = []        # ta đã nhượng
    open_items: list[str] = []      # còn tranh chấp


class NegotiateIn(BaseModel):
    deal_context: str               # bối cảnh deal (chiến lược/rủi ro từ /analyze hoặc vòng trước)
    partner_message: str            # tin nhắn đối tác vừa gửi (counter-offer / phản hồi)
    lang: str = "vi"
    leverage: str = "balanced"
    urgency: str = "low"
    relationship: str = "new"
    alternatives: bool = False
    protected_party: str = ""
    state: NegoStateIn | None = None   # sổ nhượng-bộ vòng trước (trả lại ở response → thread vòng sau)


class AlertIn(BaseModel):
    via: str                    # slack | zalo
    channel: str                # Slack channel ID hoặc Zalo user_id nhận cảnh báo
    limit: int = 200            # số case quét tối đa


class MonitorIn(BaseModel):
    since: str                  # mốc ISO 'YYYY-MM-DD' — quét VB có hiệu lực TỪ ngày này (luật mới)
    via: str | None = None      # slack | zalo (tùy chọn) — gửi digest nếu có
    channel: str | None = None  # kênh nhận digest
    limit: int = 200


class FeedbackIn(BaseModel):
    kind: str = "lookup"        # analysis | lookup
    ref: str = ""               # case_id (analysis) hoặc câu hỏi (lookup)
    rating: str                 # helpful | wrong | incomplete
    note: str = ""


class MonitorFeedbackIn(BaseModel):
    doc_id: str                 # VB mới gây cảnh báo
    case_id: str                # case bị cảnh báo nhầm
    reason: str = ""            # vì sao là báo nhầm (tùy chọn)


def build_api(service: AnalysisService, parser: DocumentParserPort, evidence: EvidenceService,
              default_tenant: str = "VN", api_orgs: dict[str, Organization] | None = None,
              max_upload_bytes: int = 10 * 1024 * 1024, rate_limit_per_min: int = 60,
              max_input_chars: int = 50_000,
              senders: dict | None = None, expert_channel: str = "") -> FastAPI:
    app = FastAPI(title="Legal Guard", version="0.7.0")
    orgs = api_orgs or {}
    _senders = senders or {}        # {"slack": ChatSenderPort, "zalo": ChatSenderPort} — gửi cảnh báo chủ động
    _expert_channel = expert_channel   # kênh chuyên gia nhận case escalation
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
        return HTMLResponse("<h1>Legal Guard</h1><p>API: /docs</p>")

    @app.get("/app", response_class=HTMLResponse)
    def demo_app():
        # UI demo: upload → risk → fallback → human checkpoint (Approve/Reject).
        if _APP.exists():
            return FileResponse(_APP)
        return HTMLResponse("<h1>Legal Guard</h1><p>UI chưa được cài. API: /docs</p>")

    @app.get("/lookup", response_class=HTMLResponse)
    def lookup_ui():
        # UI tra cứu luật: câu hỏi → /ask → câu trả lời dẫn điều/khoản còn hiệu lực + nguồn.
        if _LOOKUP.exists():
            return FileResponse(_LOOKUP)
        return HTMLResponse("<h1>Legal Guard</h1><p>UI tra cứu chưa được cài. API: /ask</p>")

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard_ui():
        # UI system-of-record: tổng hợp hoạt động pháp lý của công ty → /insights/dashboard.
        if _DASHBOARD.exists():
            return FileResponse(_DASHBOARD)
        return HTMLResponse("<h1>Legal Guard</h1><p>UI bảng điều khiển chưa cài. API: /insights/dashboard</p>")

    @app.get("/trust", response_class=HTMLResponse)
    def trust_ui():
        # Trang CÔNG BỐ ĐỘ TIN CẬY (phương pháp + số đo) — gửi cho luật sư/đối tác/giám khảo.
        if _TRUST.exists():
            return FileResponse(_TRUST)
        return HTMLResponse("<h1>Legal Guard</h1><p>Độ tin cậy: /trust.json</p>")

    @app.get("/tai-lieu", response_class=HTMLResponse)
    def docs_page():
        # Hồ sơ tài liệu (tóm tắt + mục lục gập-mở) — gửi luật sư/đồng đội xem trên trình duyệt.
        # Path /tai-lieu (KHÔNG /docs — /docs là Swagger UI mặc định của FastAPI).
        if _DOCS.exists():
            return FileResponse(_DOCS)
        raise HTTPException(status_code=404, detail="Chưa có trang tài liệu.")

    @app.get("/trust.json")
    def trust_data() -> dict:       # nguồn số liệu chung cho trang /trust + Slack (không cần auth)
        from legalguard.domain.trust import trust_report
        return trust_report()

    @app.get("/help", response_class=HTMLResponse)
    def help_page():
        # HƯỚNG DẪN sử dụng + xử lý sự cố (web) — cùng nguồn `domain/help.py` với Slack (_is_help_query).
        from html import escape

        from legalguard.domain.help import help_sections
        s = help_sections()

        def block(title: str, items: list) -> str:
            rows = "".join(
                f'<div class="row"><span class="ic">{escape(i)}</span>'
                f'<div><b>{escape(t)}</b><p>{escape(d)}</p></div></div>'
                for i, t, d in items)
            return f"<h2>{escape(title)}</h2>{rows}"

        html = f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Legal Guard — Giới thiệu, Chức năng &amp; Hướng dẫn</title>
<style>body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:760px;margin:0 auto;
padding:24px;line-height:1.55;color:#1a1a2e}}h1{{font-size:1.5rem}}h2{{font-size:1.1rem;margin-top:1.6rem;
border-top:1px solid #eee;padding-top:1rem}}.row{{display:flex;gap:12px;margin:.8rem 0}}.ic{{font-size:1.4rem;
flex:0 0 1.6rem}}p{{margin:.2rem 0;color:#333}}nav a{{margin-right:14px}}.intro{{background:#f5f7ff;
border-left:3px solid #4a5cff;padding:12px 16px;border-radius:6px}}.note{{color:#666;font-size:.9rem;
margin-top:2rem;border-top:1px solid #eee;padding-top:1rem}}</style></head><body>
<nav><a href="/">← Trang giới thiệu</a><a href="/app">Rà soát</a><a href="/lookup">Tra cứu</a><a href="/trust">Độ tin cậy</a></nav>
<h1>🤝 Legal Guard — Giới thiệu &amp; Hướng dẫn</h1>
<p class="intro">{escape(s["intro"])}</p>
{block("Chức năng chính", s["features"])}
{block("Bắt đầu thế nào", s["usage"])}
{block("Gặp sự cố", s["trouble"])}
<p class="note">🤖 AI hỗ trợ — không thay thế tư vấn pháp lý chính thức. Trên Slack/Zalo: gõ
<b>help</b> để xem hướng dẫn này.</p>
</body></html>"""
        return HTMLResponse(html)

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
        async_mode: bool = Form(default=False),   # HĐ dài → chạy NỀN, trả case_id ngay, client poll /cases/{id}
        background: BackgroundTasks = None,
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

        # Async mode: HĐ dài (~vài phút flagship) vượt timeout HTTP/proxy/client → chạy NỀN, trả case_id
        # NGAY, client poll GET /cases/{case_id} (404=đang xử lý, 200=xong). BackgroundTask chạy threadpool
        # (analyze đồng bộ) → không chặn worker + hoàn tất dù client ngắt.
        if async_mode:
            cid = uuid.uuid4().hex

            def _bg():
                try:
                    res = service.analyze(contract_text, org, lang=lang, position=position,
                                          source=source, case_id=cid)
                    _async_put(cid, org.id, res.__dict__)        # full result shape cho UI poll
                except Exception as exc:  # noqa: BLE001 — lỗi nền: lưu để client poll thấy, vẫn log
                    _async_put(cid, org.id, {"error": str(exc)})
                    _log.exception("Phân tích nền lỗi (case=%s)", cid)

            background.add_task(_bg)
            return {"case_id": cid, "status": "processing",
                    "message": "Đang phân tích nền — poll GET /analyze/result/{case_id} tới khi trả 200."}

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

    @app.get("/analyze/result/{case_id}")
    def analyze_result(case_id: str, org: Organization = Depends(require_auth)) -> dict:
        """Poll kết quả phân tích NỀN (async_mode): 404 = đang xử lý / không thấy; 200 = full result;
        502 = lỗi phân tích. Client gọi lặp tới khi 200. (Kết quả đầy đủ — khác /cases/{id} chỉ có core.)"""
        res = _async_get(case_id, org.id)
        if res is None:
            raise HTTPException(status_code=404, detail="Đang xử lý hoặc không tìm thấy kết quả.")
        if res.get("error"):
            raise HTTPException(status_code=502, detail=f"Phân tích lỗi: {res['error']}")
        return res

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

    @app.get("/runs")
    def list_runs(limit: int = 50, org: Organization = Depends(require_auth)) -> dict:
        # Feed hoạt động agent (evidence AI-Native cho track Autopilot Agent): mỗi run = 1 case +
        # số tool-call agent đã gọi + risk + cờ cần-duyệt. Cô lập org. Tổng hợp cho giám khảo NHÌN THẤY.
        from legalguard.domain.runs import execution_summary, runs_feed

        cases = service.list_cases(org.id, limit)
        feed = runs_feed(cases, limit)
        totals = {"runs": len(feed), "tool_calls": sum(r["tool_calls"] for r in feed),
                  "risks": sum(r["risks"] for r in feed),
                  "needs_review": sum(1 for r in feed if r["needs_human_review"])}
        # đếm gộp tool-call theo loại (toàn bộ run đang hiển thị)
        agg = execution_summary([s for c in cases for s in (getattr(c, "trace", None) or [])])
        return {"totals": {**totals, "by_tool": agg}, "runs": feed}

    @app.get("/cases/{case_id}")
    def get_case(case_id: str, org: Organization = Depends(require_auth)) -> dict:
        case = service.get_case(case_id)
        if case is None or case.org_id != org.id:        # cô lập theo công ty
            raise HTTPException(status_code=404, detail="Không tìm thấy case.")
        return asdict(case)

    @app.get("/cases/{case_id}/audit", response_class=PlainTextResponse)
    def case_audit(case_id: str, reviewer: str = "", note: str = "",
                   org: Organization = Depends(require_auth)) -> str:
        # Chế độ luật sư: HỒ SƠ KIỂM CHỨNG AI (markdown) đính kèm hồ sơ — chứng minh đã đối chiếu
        # (chuẩn ABA 512 / SG MinLaw). Cô lập theo công ty.
        case = service.get_case(case_id)
        if case is None or case.org_id != org.id:
            raise HTTPException(status_code=404, detail="Không tìm thấy case.")
        from legalguard.domain.audit import compile_audit_trail
        return compile_audit_trail(asdict(case), reviewer=reviewer, note=note)

    @app.get("/lawyer/consent", response_class=PlainTextResponse)
    def lawyer_consent(party_a: str = "", party_b: str = "", date: str = "", matter: str = "",
                       org: Organization = Depends(require_auth)) -> str:
        # Chế độ luật sư: sinh MẪU VĂN BẢN ĐỒNG Ý điền sẵn (khách cho phép luật sư dùng AI) — PDPL 91/2025
        # + Điều 9 Luật Luật sư. Văn bản luật sư ký với khách; công cụ chỉ sinh bản draft để rà.
        from legalguard.domain.consent import compile_consent
        return compile_consent(party_a=party_a[:200], party_b=party_b[:200], org_name=org.name,
                               date=date[:40], matter=matter[:300])

    @app.delete("/cases/{case_id}")
    def delete_case(case_id: str, org: Organization = Depends(require_auth)) -> dict:
        case = service.get_case(case_id)
        if case is None or case.org_id != org.id:        # chỉ xóa case của chính công ty
            raise HTTPException(status_code=404, detail="Không tìm thấy case.")
        return {"deleted": service.delete_case(case_id)}

    @app.post("/cases/{case_id}/outcome")
    def record_outcome(case_id: str, body: OutcomeIn,
                       org: Organization = Depends(require_auth)) -> dict:
        # Flywheel: ghi kết quả đàm phán thực tế (dữ liệu tích lũy riêng org).
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

    @app.post("/escalate")
    def escalate(body: EscalateIn, org: Organization = Depends(require_auth)) -> dict:
        # Escalation chuyên gia THẬT: reviewer Reject / có illegal → gửi case cho luật sư qua Slack/Zalo.
        # Hoàn tất "human checkpoint": không chỉ gắn cờ, mà CHUYỂN tới người thật.
        channel = (body.channel or _expert_channel).strip()
        sender = _senders.get(body.via)
        if not channel or sender is None or not getattr(sender, "available", False):
            # Không cấu hình kênh → vẫn nhận yêu cầu (đánh dấu) nhưng báo chưa gửi được.
            return {"ok": True, "sent": False, "reason": "Chưa cấu hình kênh chuyên gia (EXPERT_CHANNEL)."}
        ref = f" (case {body.case_id})" if body.case_id else ""
        text = (f"🧑‍⚖️ *Cần luật sư duyệt*{ref} — org {org.id}\n"
                f"Lý do: {body.reason or 'reviewer chuyển chuyên gia'}\n"
                f"Xem: /app (case) hoặc /cases/{body.case_id}" if body.case_id else
                f"🧑‍⚖️ *Cần luật sư duyệt* — org {org.id}\nLý do: {body.reason or 'reviewer chuyển chuyên gia'}")
        try:
            sender.send(channel, text)
        except Exception as exc:  # noqa: BLE001 — gửi lỗi không nên 500
            raise HTTPException(status_code=502, detail=f"Gửi {body.via} thất bại: {exc}") from exc
        return {"ok": True, "sent": True, "via": body.via}

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

    @app.post("/monitor/run")
    def monitor_run(body: MonitorIn, org: Organization = Depends(require_auth)) -> dict:
        # AUTOPILOT: tự quét VB luật MỚI (hiệu lực >= since) → hợp đồng nào bị ảnh hưởng. Có via+channel
        # thì GỬI digest. Hợp với cron (ECS crontab gọi hằng ngày → 'agent làm việc khi bạn ngủ').
        from legalguard.domain.regulatory import format_monitor_digest

        res = service.monitor(org.id, org.country, body.since.strip(), limit=body.limit)
        res["sent"] = False
        if body.via and body.channel and res["affected"]:
            sender = _senders.get(body.via)
            if sender is None or not getattr(sender, "available", False):
                raise HTTPException(status_code=400, detail=f"Kênh '{body.via}' chưa cấu hình.")
            text = format_monitor_digest(res["affected"], res["since"])
            try:
                sender.send(body.channel, text)
                res["sent"] = True
            except Exception as exc:  # noqa: BLE001 — gửi lỗi không nên 500
                raise HTTPException(status_code=502, detail=f"Gửi {body.via} thất bại: {exc}") from exc
        return res

    @app.post("/monitor/feedback")
    def monitor_feedback(body: MonitorFeedbackIn, org: Organization = Depends(require_auth)) -> dict:
        # Vòng phản hồi Autopilot (#3): user báo cảnh báo monitor là NHẦM → ghi lại để digest sau tự lọc
        # (chống alert fatigue). Tái dùng Feedback repo: kind=monitor, ref=<doc>|<case>, rating=wrong.
        from legalguard.domain.regulatory import monitor_ref

        fid = service.record_feedback(Feedback(
            id=uuid.uuid4().hex, org_id=org.id, kind="monitor",
            ref=monitor_ref(body.doc_id, body.case_id), rating="wrong", note=body.reason[:1000],
            created_at=datetime.now(timezone.utc).isoformat(),
        ))
        return {"recorded": fid is not None, "id": fid}

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

    @app.post("/negotiate")
    async def negotiate(body: NegotiateIn, org: Organization = Depends(require_auth)) -> dict:
        # VÒNG đàm phán đa phiên: bối cảnh deal + tin đối tác → đánh giá + chiến lược + câu trả lời + status.
        if len(body.deal_context) > max_input_chars or len(body.partner_message) > max_input_chars:
            raise HTTPException(status_code=413, detail="Nội dung quá dài.")
        pos = NegotiationPosition(leverage=body.leverage, urgency=body.urgency,
                                  relationship=body.relationship, alternatives=body.alternatives,
                                  protected_party=body.protected_party[:120])
        from legalguard.domain.negotiation import NegotiationState
        st = NegotiationState(**body.state.model_dump()) if body.state else None
        lang = body.lang if body.lang in ("en", "vi") else "vi"
        try:
            return await run_in_threadpool(
                service.negotiate_round, body.deal_context, body.partner_message, pos, st, lang, org.id)
        except LLMError as exc:
            raise HTTPException(status_code=502, detail=f"LLM lỗi: {exc}") from exc

    @app.post("/amendments/compile")
    def amendments_compile(body: CompileIn, _: Organization = Depends(require_auth)) -> dict:
        # Phase C: gộp điều khoản đã chọn → Bản ghi nhớ sửa đổi (markdown + rows) cho luật sư. Tất định.
        if len(body.items) > 200:
            raise HTTPException(status_code=413, detail="Quá nhiều mục.")
        return service.compile_memo(body.items, title=body.title, protected_party=body.protected_party)

    @app.post("/amendments/compile.docx")
    def amendments_compile_docx(body: CompileIn, _: Organization = Depends(require_auth)):
        # Phase C: xuất Bản ghi nhớ ra Word .docx (cần group `export`). Thiếu lib → 501 + dùng markdown.
        from legalguard.adapters.outbound.docx_export import DocxUnavailable, memo_to_docx

        memo = service.compile_memo(body.items, title=body.title, protected_party=body.protected_party)
        try:
            data = memo_to_docx(memo)
        except DocxUnavailable as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        return Response(content=data, media_type=_DOCX_MIME,
                        headers={"Content-Disposition": 'attachment; filename="ban-ghi-nho-sua-doi.docx"'})

    @app.post("/redline")
    def text_redline(body: RedlineIn, _: Organization = Depends(require_auth)) -> dict:
        # So 2 phiên bản text → redline ([+thêm+]/[-bỏ-]) + tỉ lệ giống nhau. Tất định, không LLM.
        if len(body.old) > max_input_chars or len(body.new) > max_input_chars:
            raise HTTPException(status_code=413, detail="Nội dung quá dài.")
        return {"redline": redline(body.old, body.new), "similarity": change_ratio(body.old, body.new)}

    return app
