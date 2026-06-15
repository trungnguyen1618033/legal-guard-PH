"""Use-case rà soát hợp đồng (application service trong hexagon).

Nối: build retriever (qua provider) → run_agent → human checkpoint → tóm tắt.
Chỉ phụ thuộc PORT, không biết gì về Qwen/Gemini/FastAPI.
"""
from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone

from legalguard.domain.agent import run_agent
from legalguard.domain.models import (
    AgentContext,
    AnalysisCase,
    AnalysisResult,
    NegotiationPosition,
    Outcome,
    SourceMeta,
)
from legalguard.domain.ports import (
    CaseRepositoryPort,
    KnowledgeBaseProvider,
    LLMError,
    LLMPort,
    ObservabilityPort,
    OutcomeRepositoryPort,
)
from legalguard.domain.redaction import redact
from legalguard.domain.tenants import Organization, get_tenant
from legalguard.domain.verification import verify_risks

_log = logging.getLogger(__name__)

_CHUNK = 6000        # ký tự / cửa sổ cho hợp đồng dài
_OVERLAP = 400       # chồng lấn để không cắt mất điều khoản ở biên
_SIMPLE_MAX = 1500   # ngưỡng "đơn giản" cho adaptive routing


def _windows(text: str) -> list[str]:
    if len(text) <= _CHUNK:
        return [text]
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + _CHUNK])
        i += _CHUNK - _OVERLAP
    return out


def _route(text: str) -> dict:
    """Adaptive routing: hợp đồng ngắn → đường rẻ (ít vòng); dài/phức tạp → full agentic."""
    return {"label": "fast", "max_iters": 3} if len(text) <= _SIMPLE_MAX \
        else {"label": "full", "max_iters": 6}


def _dedupe(items: list) -> list:
    seen, out = set(), []
    for it in items:
        if it.clause not in seen:
            seen.add(it.clause)
            out.append(it)
    return out


class AnalysisService:
    def __init__(self, reasoner: LLMPort, summarizer: LLMPort, kb: KnowledgeBaseProvider,
                 cases: CaseRepositoryPort | None = None,
                 outcomes: OutcomeRepositoryPort | None = None,
                 observer: ObservabilityPort | None = None) -> None:
        self.reasoner = reasoner      # Qwen: agent phân tích chính
        self.summarizer = summarizer  # Gemini: >=1 call tóm tắt (ràng buộc XPRIZE)
        self.kb = kb
        self.cases = cases            # persistence (tùy chọn)
        self.outcomes = outcomes      # flywheel kết quả đàm phán (tùy chọn)
        self.observer = observer      # telemetry (tùy chọn)

    def record_outcome(self, outcome: Outcome) -> str | None:
        return self.outcomes.record(outcome) if self.outcomes else None

    def tactic_stats(self, org_id: str) -> dict:
        return self.outcomes.win_rates(org_id) if self.outcomes else {}

    def get_case(self, case_id: str) -> AnalysisCase | None:
        return self.cases.get(case_id) if self.cases else None

    def list_cases(self, org_id: str, limit: int = 20) -> list[AnalysisCase]:
        return self.cases.list_by_org(org_id, limit) if self.cases else []

    def delete_case(self, case_id: str) -> bool:
        return self.cases.delete(case_id) if self.cases else False

    def health(self) -> dict:
        return {
            "status": "ok",
            "qwen_ready": self.reasoner.available,
            "gemini_ready": self.summarizer.available,
        }

    def ready(self) -> bool:
        """Readiness: DB truy cập được (cho LB/k8s probe)."""
        if self.cases is None:
            return True
        try:
            self.cases.list_by_org("__ready__", 1)
            return True
        except Exception:  # noqa: BLE001 — probe: lỗi DB → chưa sẵn sàng
            return False

    def _summarize(self, risks: list, lang: str) -> tuple[str, str | None]:
        """Gemini tóm tắt cho chủ SME. Trả (text, note-lỗi-nếu-có) — không ném exception
        (chạy trong thread pool, lỗi phải trả về tường minh)."""
        bullet = "\n".join(f"- {r.clause}: {r.risk} [{r.severity}]" for r in risks)
        prompt = (
            f"Summarize these contract risks briefly for an SME owner:\n{bullet}" if lang == "en"
            else f"Tóm tắt ngắn gọn, dễ hiểu cho chủ SME các rủi ro hợp đồng sau:\n{bullet}"
        )
        try:
            return self.summarizer.complete(prompt), None
        except LLMError as exc:
            return "", f"⚠️ Không tạo được tóm tắt ({exc.provider}); dùng kết quả agent."

    def analyze(self, contract_text: str, org: Organization, lang: str = "en",
                position: NegotiationPosition | None = None,
                source: SourceMeta | None = None) -> AnalysisResult:
        jurisdiction = get_tenant(org.country)   # quốc gia → KB luật + bối cảnh

        # Audit fingerprint TRƯỚC redact: hash khớp với văn bản khách đưa (file đã hash
        # ở inbound adapter; text dán trực tiếp → hash tại đây). Không lưu nội dung.
        source = source or SourceMeta.of(contract_text.encode("utf-8"))
        text_chars = len(contract_text)

        # Redact PII TRƯỚC khi gửi LLM / lưu / log (data minimization, OWASP LLM02).
        contract_text, redacted_n = redact(contract_text)

        retriever = self.kb.for_org(org)         # KB quốc gia + overlay riêng công ty
        ctx = AgentContext(retriever=retriever)

        # Adaptive routing + chunking hợp đồng dài. Các cửa sổ ĐỘC LẬP → chạy SONG SONG
        # (mỗi cửa sổ ctx riêng, merge theo thứ tự — kết quả tất định, ~3× nhanh hơn tuần tự).
        route = _route(contract_text)
        windows = _windows(contract_text)
        contexts = [AgentContext(retriever=retriever) for _ in windows]

        def _one(i: int):
            return run_agent(windows[i], jurisdiction.country, self.reasoner, contexts[i],
                             lang=lang, position=position, max_iters=route["max_iters"])

        if len(windows) == 1:
            runs = [_one(0)]
        else:
            with ThreadPoolExecutor(max_workers=min(3, len(windows))) as pool:
                runs = list(pool.map(_one, range(len(windows))))

        trace, strategies = [], []
        truncated = False
        for run, wctx in zip(runs, contexts):          # merge theo thứ tự cửa sổ
            trace += run.trace
            truncated = truncated or run.truncated
            if run.final_message:                      # gom chiến lược mọi cửa sổ (không bỏ sót)
                strategies.append(run.final_message)
            ctx.risks += wctx.risks
            ctx.fallbacks += wctx.fallbacks
            ctx.needs_human_review = ctx.needs_human_review or wctx.needs_human_review
            ctx.review_reasons += wctx.review_reasons
        strategy = "\n\n".join(strategies)
        ctx.risks = _dedupe(ctx.risks)
        ctx.fallbacks = _dedupe(ctx.fallbacks)

        # Outcome-aware ranking: gắn win-rate lịch sử (flywheel toàn cục) cho mỗi fallback.
        if self.outcomes is not None:
            rates = self.outcomes.win_rates()
            for f in ctx.fallbacks:
                if f.clause in rates:
                    f.win_rate = rates[f.clause]["rate"]

        notes: list[str] = [f"🧭 Route: {route['label']}"
                            + (f" · chia {len(windows)} đoạn" if len(windows) > 1 else "")]
        notes.append(f"🔐 Vân tay văn bản (SHA-256): {source.sha256[:16]}…")
        if redacted_n:
            notes.append(f"🔒 Đã ẩn {redacted_n} thông tin nhạy cảm trước khi gửi AI.")
        if truncated:
            notes.append("⚠️ Hợp đồng vượt giới hạn phân tích — phần cuối CHƯA được rà soát.")
            ctx.needs_human_review = True
        if not self.reasoner.available:
            notes.append("⚠️ Đang chạy ở chế độ STUB (chưa cấu hình QWEN_API_KEY).")

        # Verification (judge) ∥ Gemini summary: hai việc độc lập (summary chỉ đọc
        # clause/risk/severity, verification chỉ ghi cờ verified) → chạy song song.
        summary = strategy
        if ctx.risks:
            with ThreadPoolExecutor(max_workers=2) as pool:
                f_verify = pool.submit(verify_risks, ctx.risks, contract_text,
                                       retriever, self.reasoner)
                f_summary = pool.submit(self._summarize, ctx.risks, lang)
            notes += f_verify.result()
            text, err = f_summary.result()
            if err:
                notes.append(err)
            else:
                summary = text
        if any(not r.verified for r in ctx.risks):
            ctx.needs_human_review = True
        # Lời hứa sản phẩm: rủi ro HIGH luôn cần người duyệt — ép tất định ở domain,
        # không phụ thuộc LLM có nhớ gọi request_human_review hay không.
        if any(r.severity == "high" for r in ctx.risks) and not ctx.needs_human_review:
            ctx.needs_human_review = True
            ctx.review_reasons.append("Có rủi ro mức cao — tự động yêu cầu chuyên gia duyệt.")

        result = AnalysisResult(
            tenant=jurisdiction.id,
            risks=[asdict(r) for r in ctx.risks],
            fallbacks=[asdict(f) for f in ctx.fallbacks],
            needs_human_review=ctx.needs_human_review,
            review_reasons=ctx.review_reasons,
            summary=summary,
            trace=[asdict(s) for s in trace],
            strategy=strategy,
            notes=notes,
        )

        # Persist case (audit + lịch sử + evidence). Lỗi DB không làm hỏng phân tích.
        if self.cases is not None:
            case = AnalysisCase(
                id=uuid.uuid4().hex,
                org_id=org.id,
                tenant=jurisdiction.id,
                created_at=datetime.now(timezone.utc).isoformat(),
                lang=lang,
                contract_excerpt=contract_text[:280],
                summary=result.summary,
                needs_human_review=result.needs_human_review,
                risks=result.risks, fallbacks=result.fallbacks, trace=result.trace,
                source_sha256=source.sha256, source_name=source.filename,
                source_bytes=source.size_bytes, text_chars=text_chars,
            )
            try:
                result.case_id = self.cases.save(case)
            except Exception:  # noqa: BLE001 — persistence là phụ, không chặn kết quả
                _log.exception("Không lưu được case (org=%s)", org.id)
                result.notes.append("⚠️ Không lưu được case (DB).")

        if self.observer is not None:
            self.observer.event("analysis", {
                "tenant": result.tenant, "lang": lang, "risks": len(result.risks),
                "needs_human_review": result.needs_human_review, "case_id": result.case_id,
            })
        return result
