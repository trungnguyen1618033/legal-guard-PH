"""Use-case rà soát hợp đồng (application service trong hexagon).

Nối: build retriever (qua provider) → run_agent → human checkpoint → tóm tắt.
Chỉ phụ thuộc PORT, không biết gì về Qwen/Gemini/FastAPI.
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone

from legalguard.domain.agent import run_agent
from legalguard.domain.models import (
    AgentContext,
    AnalysisCase,
    AnalysisResult,
    Feedback,
    NegotiationPosition,
    Outcome,
    SourceMeta,
)
from legalguard.domain.ports import (
    CaseRepositoryPort,
    FeedbackRepositoryPort,
    KnowledgeBaseProvider,
    LLMError,
    LLMPort,
    ObservabilityPort,
    OutcomeRepositoryPort,
)
from legalguard.domain.redaction import redact
from legalguard.domain.tenants import Organization, get_tenant
from legalguard.domain.verification import nli_supports, verify_risks

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
    # Khóa theo (clause, nội dung) — KHÔNG chỉ clause: hai rủi ro KHÁC NHAU trên cùng tên điều khoản
    # (vd "Thanh toán": rủi ro trả-sau VÀ rủi ro phạt) phải giữ cả hai, không nuốt mất.
    seen, out = set(), []
    for it in items:
        key = (it.clause, getattr(it, "risk", "") or getattr(it, "suggestion", ""))
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


_LEGAL_BASIS_MIN_OVERLAP = 3   # số thuật ngữ phải trùng tối thiểu để gắn căn cứ (tránh căn cứ lạc)
_LEGAL_BASIS_MIN_REL = 0.5     # điểm chunk điều luật ≥ 50% top hit mới gắn (điều luật phải thật sự liên quan)


def _terms(text: str) -> set[str]:
    return {t for t in re.findall(r"\w+", unicodedata.normalize("NFC", text).lower()) if len(t) > 2}


def _legal_citation(query: str, retriever, judge: LLMPort | None = None) -> str:
    """Tra KB → căn cứ pháp lý cho 1 mục: 'file#Điều N: <nguyên văn rút gọn>'. Trả '' nếu không có
    điều luật khớp ĐỦ MẠNH. Chống gắn căn cứ lạc (gắn điều luật không liên quan cũng sai như bịa) bằng:
    (1) điểm chunk ≥ 50% top hit, (2) trùng ≥3 thuật ngữ, (3) NLI: nếu có `judge`, điều luật phải THỰC SỰ
    HẬU THUẪN claim (judge nói NO → bỏ, tránh 'citation tồn tại nhưng không hỗ trợ'). Chỉ nhận chunk `#Điều`."""
    try:
        hits = retriever.retrieve(query, top_k=5)
    except Exception:  # noqa: BLE001 — grounding là phụ, lỗi KB không chặn phân tích
        return ""
    if not hits:
        return ""
    q_terms = _terms(query)
    floor = _LEGAL_BASIS_MIN_REL * hits[0].score        # hits đã sắp giảm dần theo điểm
    for h in hits:                                      # lấy điều luật liên quan NHẤT (rank cao) đạt ngưỡng
        if h.score < floor:
            break                                       # còn lại đều thấp hơn → dừng (tránh điều luật nhiễu)
        if "#Điều" in h.source and len(q_terms & _terms(h.text)) >= _LEGAL_BASIS_MIN_OVERLAP:
            if judge is not None and nli_supports(query, h.text, judge) is False:
                continue                                # điều luật KHÔNG hậu thuẫn claim → thử ứng viên kế
            return f"{h.source}: {' '.join(h.text.split())[:200]}…"
    return ""


def _attach_legal_basis(risks: list, fallbacks: list, retriever, judge: LLMPort | None = None) -> int:
    """Gắn căn cứ điều luật cho mỗi risk & fallback. CACHE theo clause: risk và fallback cùng một
    điều khoản chỉ tra KB 1 lần. judge (tùy chọn): bật kiểm NLI — chỉ gắn điều luật THỰC SỰ hậu thuẫn claim.

    Mỗi clause độc lập → tra cứu + NLI cho các clause khác nhau chạy SONG SONG (giảm latency tuyến tính
    theo số clause; NLI mỗi clause là 1 round-trip LLM). Trả số mục gắn được."""
    # clause → query text (risk xử lý trước nên `extra` của risk thắng — giữ nguyên ngữ nghĩa cache cũ).
    queries: dict[str, str] = {}
    for r in risks:
        queries.setdefault(r.clause, r.risk)
    for f in fallbacks:
        queries.setdefault(f.clause, f.suggestion)

    def _cite(clause: str) -> tuple[str, str]:
        return clause, _legal_citation(f"{clause} {queries[clause]}", retriever, judge)

    if len(queries) > 1:                      # >1 clause → song song (mỗi clause 1 NLI round-trip)
        with ThreadPoolExecutor(max_workers=min(6, len(queries))) as pool:
            cache = dict(pool.map(_cite, queries))
    else:
        cache = dict(_cite(c) for c in queries)

    grounded = 0
    for r in risks:
        r.legal_basis = cache.get(r.clause, "")
        grounded += bool(r.legal_basis)
    for f in fallbacks:
        f.legal_basis = cache.get(f.clause, "")
        grounded += bool(f.legal_basis)
    return grounded


class AnalysisService:
    def __init__(self, reasoner: LLMPort, summarizer: LLMPort, kb: KnowledgeBaseProvider,
                 cases: CaseRepositoryPort | None = None,
                 outcomes: OutcomeRepositoryPort | None = None,
                 observer: ObservabilityPort | None = None,
                 legal_basis_grounding: bool = True,
                 feedback: FeedbackRepositoryPort | None = None,
                 nli_verification: bool = True,
                 judge: LLMPort | None = None,
                 lookup_cache_size: int = 256) -> None:
        self.reasoner = reasoner      # Qwen flagship: agent phân tích chính (việc KHÓ)
        self.summarizer = summarizer  # Gemini: >=1 call tóm tắt (ràng buộc XPRIZE)
        # Model NHANH cho việc phụ yes/no (NLI, verify gộp). Mặc định = reasoner (giữ tương thích/stub),
        # prod truyền qwen-flash → cắt mạnh latency khâu hậu-agent mà KHÔNG giảm bước kiểm nào.
        self.judge = judge or reasoner
        self.kb = kb
        self.cases = cases            # persistence (tùy chọn)
        self.outcomes = outcomes      # flywheel kết quả đàm phán (tùy chọn)
        self.observer = observer      # telemetry (tùy chọn)
        self.legal_basis_grounding = legal_basis_grounding   # gắn căn cứ điều luật cho risk/fallback
        self.feedback = feedback      # vòng học: phản hồi người dùng (tùy chọn)
        self.nli_verification = nli_verification  # kiểm entailment (nguồn có hậu thuẫn claim) — chống hallucinate
        # Cache tra cứu (in-process, bounded LRU): câu hỏi lặp → trả tức thì + tiết kiệm token. KB tĩnh
        # trong 1 phiên deploy nên an toàn; redeploy = process mới = cache mới. 0 = tắt.
        self._lookup_cache_size = lookup_cache_size
        self._lookup_cache: OrderedDict[str, tuple] = OrderedDict()

    def record_outcome(self, outcome: Outcome) -> str | None:
        return self.outcomes.record(outcome) if self.outcomes else None

    def tactic_stats(self, org_id: str) -> dict:
        return self.outcomes.win_rates(org_id) if self.outcomes else {}

    def record_feedback(self, fb: Feedback) -> str | None:
        return self.feedback.record(fb) if self.feedback else None

    def list_feedback(self, org_id: str, limit: int = 100) -> list[Feedback]:
        return self.feedback.list_by_org(org_id, limit) if self.feedback else []

    def regulatory_impact(self, doc_id: str, country: str, org_id: str,
                          limit: int = 200) -> list[dict]:
        """Chủ động cảnh báo: VB pháp luật MỚI `doc_id` → case nào của `org_id` viện dẫn văn bản bị
        nó sửa đổi/thay thế/hướng dẫn → cần rà soát lại. Trả [] nếu chưa lưu case hoặc VB không
        tác động lên văn bản đã có trong KB."""
        from legalguard.domain.regulatory import scan_cases

        if self.cases is None:
            return []
        affected = self.kb.affected_files(doc_id, country)
        if not affected:
            return []
        cases = self.cases.list_by_org(org_id, limit)
        impacts = scan_cases(cases, affected, new_doc_id=doc_id.strip())
        if self.observer:
            self.observer.event("regulatory_impact",
                                {"doc_id": doc_id, "org_id": org_id, "hits": len(impacts)})
        return [asdict(i) for i in impacts]

    def dashboard(self, org_id: str, limit: int = 200) -> dict:
        """System-of-record: tổng hợp hoạt động pháp lý của công ty (cases/feedback/outcome). Cô lập org."""
        from legalguard.domain.dashboard import build_dashboard

        cases = self.cases.list_by_org(org_id, limit) if self.cases else []
        feedbacks = self.feedback.list_by_org(org_id, limit) if self.feedback else []
        win_rates = self.outcomes.win_rates(org_id) if self.outcomes else {}
        return build_dashboard(cases, feedbacks, win_rates)

    def draft_counter_clause(self, clause: str, risk: str = "", suggestion: str = "",
                             legal_basis: str = "", leverage: str = "balanced") -> dict:
        """Soạn điều khoản phản-đề song ngữ (dán vào HĐ) cho 1 điều khoản rủi ro. Bám căn cứ + vị thế."""
        from legalguard.domain.counter_clause import draft_counter_clause as _draft

        cc = _draft(self.reasoner, clause=clause, risk=risk, suggestion=suggestion,
                    legal_basis=legal_basis, leverage=leverage)
        if self.observer:
            self.observer.event("counter_clause", {"clause": clause, "grounded": cc.grounded})
        return asdict(cc)

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
        t0 = time.monotonic()
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

        errors: list[LLMError] = []

        def _one(i: int):
            # Lỗi LLM ở 1 cửa sổ KHÔNG được xóa kết quả các cửa sổ khác → trả None, gom lỗi.
            try:
                return run_agent(windows[i], jurisdiction.country, self.reasoner, contexts[i],
                                 lang=lang, position=position, max_iters=route["max_iters"])
            except LLMError as exc:
                _log.warning("Cửa sổ %d lỗi LLM: %s", i, exc)
                errors.append(exc)
                return None

        if len(windows) == 1:
            runs = [_one(0)]
        else:
            with ThreadPoolExecutor(max_workers=min(3, len(windows))) as pool:
                runs = list(pool.map(_one, range(len(windows))))
        _log.info("agent loop (%d window) %dms", len(windows), round((time.monotonic() - t0) * 1000))

        if all(r is None for r in runs):               # TẤT CẢ cửa sổ lỗi → 502 (không có gì để trả)
            raise errors[0] if errors else LLMError(self.reasoner.name, "phân tích thất bại")

        trace, strategies = [], []
        truncated, failed_windows = False, 0
        for run, wctx in zip(runs, contexts):          # merge theo thứ tự cửa sổ
            if run is None:                            # cửa sổ lỗi → bỏ qua, đánh dấu cần người duyệt
                failed_windows += 1
                continue
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
        if failed_windows:
            notes.append(f"⚠️ {failed_windows} phân đoạn lỗi LLM — CHƯA rà soát hết, cần chuyên gia duyệt.")
            ctx.needs_human_review = True
        if not self.reasoner.available:
            notes.append("⚠️ Đang chạy ở chế độ STUB (chưa cấu hình QWEN_API_KEY).")

        # BA việc hậu-agent ĐỘC LẬP (mỗi việc ghi trường khác nhau: verify→`verified`,
        # summary→chỉ đọc, legal_basis→`legal_basis`) → chạy SONG SONG thay vì 3 chặng tuần tự.
        # Đây là phần nặng latency nhất sau agent (mỗi NLI là 1 round-trip LLM).
        summary = strategy
        judge = self.judge if self.nli_verification else None        # NLI (model nhanh): điều luật hậu thuẫn claim
        do_basis = self.legal_basis_grounding and (ctx.risks or ctx.fallbacks)
        t_post = time.monotonic()
        with ThreadPoolExecutor(max_workers=3) as pool:
            f_verify = (pool.submit(verify_risks, ctx.risks, contract_text, retriever, self.judge)
                        if ctx.risks else None)
            f_summary = pool.submit(self._summarize, ctx.risks, lang) if ctx.risks else None
            f_basis = (pool.submit(_attach_legal_basis, ctx.risks, ctx.fallbacks, retriever, judge)
                       if do_basis else None)
        if f_verify is not None:
            notes += f_verify.result()
        if f_summary is not None:
            text, err = f_summary.result()
            if err:
                notes.append(err)
            else:
                summary = text
        if f_basis is not None and (grounded := f_basis.result()):
            notes.append(f"📎 Gắn căn cứ pháp lý (điều luật còn hiệu lực) cho {grounded} mục.")
        _log.info("post-agent (verify∥summary∥legal_basis) %dms", round((time.monotonic() - t_post) * 1000))

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

        duration_ms = round((time.monotonic() - t0) * 1000)
        _log.info("analyze tenant=%s risks=%d review=%s windows=%d failed=%d %dms",
                  result.tenant, len(result.risks), result.needs_human_review,
                  len(windows), failed_windows, duration_ms)
        if self.observer is not None:
            self.observer.event("analysis", {
                "tenant": result.tenant, "lang": lang, "risks": len(result.risks),
                "needs_human_review": result.needs_human_review, "case_id": result.case_id,
                "duration_ms": duration_ms, "failed_windows": failed_windows,
            })
        return result

    def lookup(self, question: str, org: Organization, lang: str = "vi", top_k: int = 5):
        """Tra cứu pháp luật có grounding (khác `analyze` — không cần hợp đồng).

        Retrieve KB của org (đã gồm lọc hiệu lực + citation-closure theo cấu hình) → tổng hợp câu trả lời
        BUỘC dẫn đúng Điều/Khoản, chỉ dùng căn cứ truy được. Trả (answer, snippets).

        Cache theo (country, org, lang, câu-hỏi-chuẩn-hóa-đã-redact): hỏi lặp → trả tức thì."""
        q, _ = redact(question)
        ckey = f"{org.country}:{org.id}:{lang}:{' '.join(unicodedata.normalize('NFC', q).lower().split())}"
        if self._lookup_cache_size and ckey in self._lookup_cache:
            self._lookup_cache.move_to_end(ckey)        # LRU: vừa dùng → mới nhất
            return self._lookup_cache[ckey]
        snippets = self.kb.for_org(org).retrieve(q, top_k)
        if not snippets:
            return ("Chưa đủ căn cứ trong cơ sở tri thức để trả lời câu hỏi này."
                    if lang == "vi" else
                    "Not enough grounding in the knowledge base to answer this."), []
        sources = "\n---\n".join(f"[nguồn: {s.source}] {s.text}" for s in snippets)
        tail = " Trả lời tiếng Việt." if lang == "vi" else " Answer in English."
        prompt = (
            "Bạn là LUẬT SƯ tư vấn. CHỈ dùng các đoạn căn cứ dưới đây, KHÔNG bịa. Giọng CHUYÊN NGHIỆP, "
            "súc tích, KHÔNG mở bài rườm rà. Trả lời theo ĐÚNG định dạng sau:\n"
            "**Trả lời:** <1–3 câu trực tiếp; nêu rõ số liệu/mức trần nếu có>\n"
            "**Căn cứ:** mỗi dòng một căn cứ — Điều/Khoản + tên văn bản + ý chính ngắn "
            "(chỉ dùng căn cứ có bên dưới; nếu không đủ ghi 'Chưa đủ căn cứ trong cơ sở tri thức').\n\n"
            f"Căn cứ:\n{sources}\n\nCâu hỏi: {question}" + tail)
        try:
            answer = self.reasoner.complete(prompt)
        except LLMError as exc:
            return f"Chưa trả lời được: {exc}", snippets
        # NLI (model nhanh): câu trả lời có được CHÍNH các nguồn hậu thuẫn không? Không → cảnh báo.
        if self.nli_verification and nli_supports(answer, sources, self.judge) is False:
            answer += ("\n\n⚠️ Lưu ý: câu trả lời có thể CHƯA được nguồn hậu thuẫn đầy đủ — hãy kiểm chứng "
                       "với văn bản gốc." if lang == "vi" else
                       "\n\n⚠️ Note: this answer may not be fully supported by the cited sources — verify.")
        if self.observer is not None:
            self.observer.event("lookup", {"tenant": get_tenant(org.country).id,
                                           "lang": lang, "hits": len(snippets)})
        result = (answer, snippets)
        if self._lookup_cache_size:                      # chỉ cache câu trả lời THÀNH CÔNG (không cache lỗi)
            self._lookup_cache[ckey] = result
            if len(self._lookup_cache) > self._lookup_cache_size:
                self._lookup_cache.popitem(last=False)   # đẩy mục cũ nhất ra (LRU evict)
        return result
