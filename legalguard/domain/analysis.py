"""Use-case rà soát hợp đồng (application service trong hexagon).

Nối: build retriever (qua provider) → run_agent → human checkpoint → tóm tắt.
Chỉ phụ thuộc PORT, không biết gì về Qwen/FastAPI.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
import uuid
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from legalguard.domain.agent import run_agent
from legalguard.domain.models import (
    AgentContext,
    AnalysisCase,
    AnalysisResult,
    Feedback,
    NegotiationPosition,
    Obligation,
    OrgPolicy,
    Outcome,
    SourceMeta,
)
from legalguard.domain.ports import (
    CaseRepositoryPort,
    FeedbackRepositoryPort,
    KnowledgeBaseProvider,
    LLMError,
    LLMPort,
    ObligationRepositoryPort,
    ObservabilityPort,
    OrgPolicyRepositoryPort,
    OutcomeRepositoryPort,
)
from legalguard.domain.redaction import redact
from legalguard.domain.regulatory import dismissed_pairs, filter_affected
from legalguard.domain.runs import execution_summary
from legalguard.domain.tenants import Organization, get_tenant
from legalguard.domain.verification import (
    elbow_cutoff, nli_contradicts, nli_supports, sources_answer_question, verify_risks,
)

if TYPE_CHECKING:
    from legalguard.domain.negotiation import NegotiationState

_log = logging.getLogger(__name__)

_CHUNK = 6000        # ký tự / cửa sổ cho hợp đồng dài
_OVERLAP = 400       # chồng lấn để không cắt mất điều khoản ở biên
_SIMPLE_MAX = 1500   # ngưỡng "đơn giản" cho adaptive routing
_FAST_MAX = 12000    # trần ký tự cho fast-path (1 call, không cửa sổ) — HĐ dài hơn nên dùng deep
# Câu hỏi point-in-time (có năm 19xx/20xx hoặc ngày d/m/y) cần suy luận thời điểm → dùng flagship,
# không dùng model nhanh (qwen-plus yếu hơn ở reasoning thời điểm — đã đo). Hybrid lookup.
_PIT_RE = re.compile(r"\b(?:19|20)\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")
# Câu hỏi LIỆT KÊ (nhiều mục/hình thức/trường hợp) → answer phải kể ĐỦ, không nén "1-3 câu" gây sót
# (ca FDI 'những ưu đãi đầu tư nào' flaky vì LLM nén, bỏ hình thức miễn/giảm thuế). Bắt "những/các …nào",
# "hình thức", "trường hợp", "liệt kê", "gồm/bao gồm".
_ENUM_RE = re.compile(
    r"(?:những|các).{0,40}\bnào\b|hình thức|trường hợp|liệt kê|gồm những|bao gồm|"
    r"list of|types of|forms of|which .{0,30}(?:apply|available)", re.IGNORECASE)

# Viết tắt pháp lý phổ biến (người dùng gõ) → cụm đầy đủ (văn bản luật viết). Chỉ các viết tắt KHÔNG
# nhập nhằng. Mở rộng CỘNG THÊM vào query retrieval (không thay) → tăng recall (vd "TNHH" khớp Điều
# "công ty trách nhiệm hữu hạn"), rủi ro regression thấp. Không dùng cho prompt/gate (giữ câu gốc).
_LEGAL_ABBREV = {
    "tnhh": "trách nhiệm hữu hạn", "shtt": "sở hữu trí tuệ", "gtgt": "giá trị gia tăng",
    "tndn": "thu nhập doanh nghiệp", "bhxh": "bảo hiểm xã hội", "sxkd": "sản xuất kinh doanh",
    "vphc": "vi phạm hành chính", "blds": "bộ luật dân sự", "bllđ": "bộ luật lao động",
}
_ABBREV_RE = re.compile(r"\b(" + "|".join(_LEGAL_ABBREV) + r")\b", re.IGNORECASE)


def _expand_abbrev(query: str) -> str:
    """Cộng thêm cụm đầy đủ cho mỗi viết tắt pháp lý có trong query (chỉ để RETRIEVAL, không đổi câu gốc)."""
    seen = {m.group(1).lower() for m in _ABBREV_RE.finditer(query)}
    extra = " ".join(_LEGAL_ABBREV[a] for a in seen)
    return f"{query} {extra}" if extra else query


def _extract_json_obj(raw: str) -> dict:
    """Rút object JSON đầu tiên từ output LLM (chịu được ```json fence / văn bản thừa). Lỗi → {}."""
    import json
    s = (raw or "").strip()
    if "```" in s:                       # bỏ hàng rào ```json … ```
        s = re.sub(r"```(?:json)?", "", s).strip("` \n")
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        obj = json.loads(s[start:end + 1])
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _norm_ws(s: object) -> str:
    """Gộp MỌI khoảng trắng (kể cả xuống dòng) → 1 dấu cách + strip. Chống quote nhiều dòng làm vỡ format."""
    return " ".join(str(s or "").split())


def _format_drafting_issue(it: object) -> str:
    """1 lỗi soạn thảo / khác biệt VN–EN → CÂU văn xuôi kiểu 'thư gửi khách':
      'Tại <vị trí>, <vấn đề>; đề xuất sửa thành: <fix>'  hoặc song ngữ (Tiếng Việt:/Tiếng Anh:).
    Bỏ mục no-op (đề xuất y hệt nội dung sai). Chấp nhận cả schema cũ {quote,fix}. THUẦN — test offline."""
    if isinstance(it, str):
        return _norm_ws(it)
    if not isinstance(it, dict):
        return ""
    loc = _norm_ws(it.get("location"))
    issue = _norm_ws(it.get("issue") or it.get("quote"))       # 'quote' = schema cũ (tương thích ngược)
    fix = _norm_ws(it.get("fix"))
    fix_vi, fix_en = _norm_ws(it.get("fix_vi")), _norm_ws(it.get("fix_en"))
    head = (f"Tại {loc}, {issue}" if loc and issue else (issue or loc)).rstrip(" .;")
    if fix_vi or fix_en:                                       # sửa SONG NGỮ → tách dòng (kiểu demo)
        parts = [(head + "; đề xuất sửa như sau:") if head else "Đề xuất sửa như sau:"]
        if fix_vi:
            parts.append(f"Tiếng Việt: {fix_vi}")
        if fix_en:
            parts.append(f"Tiếng Anh: {fix_en}")
        return "\n".join(parts)
    if fix:
        if issue and issue.lower() == fix.lower():             # đề xuất y hệt nội dung sai → no-op, bỏ
            return ""
        return f"{head}; đề xuất sửa thành: {fix}" if head else f"Đề xuất sửa thành: {fix}"
    return head


_HYDE_PROMPT = (
    "Cho câu hỏi pháp lý sau, liệt kê 5-8 THUẬT NGỮ / cụm từ PHÁP LÝ có KHẢ NĂNG XUẤT HIỆN trong điều luật "
    "trả lời câu hỏi (danh từ pháp lý, tên thủ tục, chế định). CHỈ liệt kê cách nhau bởi dấu phẩy, KHÔNG "
    "giải thích, KHÔNG bịa số điều. Câu hỏi: {q}")


def _hyde_expand(query: str, llm: LLMPort | None) -> str:
    """HyDE-lite: LLM sinh THUẬT NGỮ luật cầu nối khoảng-cách 'cách hỏi' vs 'cách luật viết' → cộng vào query
    (chỉ RETRIEVAL). Bắc cầu câu THỦ TỤC ('gồm những bước nào') ↔ điều luật THỰC THỂ (vd 'Hòa giải tại Tòa
    án') → cụm evidence chặt hơn → cổng relevance pass robust (KHÔNG tuning gate). Lỗi/offline → trả query gốc."""
    if llm is None or not getattr(llm, "available", False):
        return query
    try:
        terms = llm.complete(_HYDE_PROMPT.format(q=query[:400]))
    except LLMError:
        return query
    terms = re.sub(r"[^\w\s,]", " ", terms).strip()[:300]   # gom sạch, chặn độ dài
    return f"{query} {terms}" if terms else query


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


def _detect_illegal(risks: list, judge: LLMPort | None) -> int:
    """Phase B — lớp NLI-mâu-thuẫn có grounding: nâng risk `unfavorable` → `illegal` khi điều khoản
    THỰC SỰ TRÁI điều luật đã gắn ở `legal_basis` (điều luật THẬT đã retrieve, không hard-code luật).

    Chỉ CHẠY trên risk đã có `legal_basis`; chỉ NÂNG (không hạ illegal của agent). BẢO THỦ: judge phải
    nói YES rõ ràng (`nli_contradicts` True) mới gắn illegal — nghi ngờ/offline → giữ unfavorable.
    `violated_law` lấy ĐÚNG điều luật từ legal_basis (vd 'Điều 466'). Mỗi risk 1 round-trip judge → song song."""
    if judge is None or not getattr(judge, "available", False):
        return 0
    cands = [r for r in risks if r.legal_status == "unfavorable" and r.legal_basis]
    if not cands:
        return 0

    def _check(r) -> bool:
        clause = r.evidence or f"{r.clause}: {r.risk}"
        return nli_contradicts(clause, r.legal_basis, judge) is True

    if len(cands) > 1:
        with ThreadPoolExecutor(max_workers=min(6, len(cands))) as pool:
            verdicts = list(pool.map(_check, cands))
    else:
        verdicts = [_check(cands[0])]

    upgraded = 0
    for r, is_illegal in zip(cands, verdicts):
        if is_illegal:
            r.legal_status = "illegal"
            # violated_law = phần điều luật trong legal_basis: 'file#Điều N: ...' → 'Điều N'
            head = r.legal_basis.split(":", 1)[0]
            r.violated_law = head.split("#", 1)[1] if "#" in head else head
            upgraded += 1
    return upgraded


def _attach_counter_clauses(risks: list, fallbacks: list, reasoner: LLMPort | None,
                            max_n: int = 6) -> int:
    """Sinh điều khoản mới dán-được-ngay (song ngữ) INLINE cho rủi ro TRÁI LUẬT / must_fix — hậu-agent,
    SONG SONG, bounded (chỉ rủi ro quan trọng → tiết kiệm quota; rủi ro nhẹ giữ nút 'Đồng ý sửa').
    CHẠY SAU _detect_illegal (cần nhãn illegal chốt) + _attach_legal_basis (cần legal_basis cho căn cứ).
    Dùng NGUYÊN VĂN evidence (trích HĐ) làm điều khoản gốc → LLM viết lại chính đoạn đó. Gắn r.counter_clause.
    Lỗi 1 rủi ro → bỏ qua rủi ro đó (không làm hỏng cả reply).
    TRẦN `max_n` (mặc định 6, 0 = không trần): HĐ dài nhiều điều khoản → chỉ auto TOP `max_n`, ƯU TIÊN illegal
    (điều khoản có thể VÔ HIỆU — giá trị nhất) trước must_fix; phần dôi rơi về nút 'Đồng ý sửa' (không mất
    chức năng) → chặn spike quota flagship lúc đông user."""
    if reasoner is None or not getattr(reasoner, "available", False):
        return 0
    cands = [r for r in risks if r.legal_status == "illegal" or r.priority == "must_fix"]
    if not cands:
        return 0
    # Ưu tiên illegal trước must_fix (sort ỔN ĐỊNH giữ thứ tự gốc trong mỗi nhóm), rồi cắt theo trần.
    cands.sort(key=lambda r: 0 if r.legal_status == "illegal" else 1)
    if max_n and max_n > 0:
        cands = cands[:max_n]
    from legalguard.domain.counter_clause import draft_counter_clause as _draft
    fb_by_clause = {f.clause: f for f in fallbacks}

    def _gen(r) -> dict:
        try:
            original = (r.evidence or "").strip() or r.clause
            fb = fb_by_clause.get(r.clause)
            cc = _draft(reasoner, clause=original, risk=r.risk,
                        suggestion=(fb.suggestion if fb else ""),
                        legal_basis=(r.legal_basis or (fb.legal_basis if fb else "")))
            return asdict(cc)
        except Exception:  # noqa: BLE001 — 1 rủi ro lỗi soạn không được làm hỏng cả reply
            _log.exception("Không sinh được counter_clause cho '%s'", getattr(r, "clause", "?"))
            return {}

    if len(cands) > 1:
        with ThreadPoolExecutor(max_workers=min(4, len(cands))) as pool:
            results = list(pool.map(_gen, cands))
    else:
        results = [_gen(cands[0])]
    attached = 0
    for r, cc in zip(cands, results):
        if cc:
            r.counter_clause = cc
            attached += 1
    return attached


class AnalysisService:
    def __init__(self, reasoner: LLMPort, kb: KnowledgeBaseProvider,
                 cases: CaseRepositoryPort | None = None,
                 outcomes: OutcomeRepositoryPort | None = None,
                 observer: ObservabilityPort | None = None,
                 legal_basis_grounding: bool = True,
                 feedback: FeedbackRepositoryPort | None = None,
                 obligations: "ObligationRepositoryPort | None" = None,
                 obligation_tracking: bool = False,
                 org_policies: "OrgPolicyRepositoryPort | None" = None,
                 org_playbook: bool = False,
                 nli_verification: bool = True,
                 judge: LLMPort | None = None,
                 lookup_cache_size: int = 256,
                 lookup_llm: LLMPort | None = None,
                 lookup_pit_llm: LLMPort | None = None,
                 fast_review_llm: LLMPort | None = None,
                 illegal_detection: bool = True,
                 coverage_gated_abstain: bool = True,
                 hyde_query_expansion: bool = False,
                 auto_counter_on_analyze: bool = True,
                 auto_counter_max: int = 6,
                 fast_auto_counter: bool = False) -> None:
        self.reasoner = reasoner      # Qwen flagship: agent phân tích chính (việc KHÓ)
        # Model NHANH cho việc phụ yes/no (NLI, verify gộp) + tóm tắt SME (_summarize). Mặc định = reasoner (giữ tương thích/stub),
        # prod truyền qwen-flash → cắt mạnh latency khâu hậu-agent mà KHÔNG giảm bước kiểm nào.
        self.judge = judge or reasoner
        self.kb = kb
        self.cases = cases            # persistence (tùy chọn)
        self.outcomes = outcomes      # flywheel kết quả đàm phán (tùy chọn)
        self.observer = observer      # telemetry (tùy chọn)
        self.legal_basis_grounding = legal_basis_grounding   # gắn căn cứ điều luật cho risk/fallback
        self.feedback = feedback      # vòng học: phản hồi người dùng (tùy chọn)
        self.obligations = obligations   # nghĩa vụ & hạn chót (SAU KÝ) — system-of-record riêng org
        self.obligation_tracking = obligation_tracking   # flag OFF: trích nghĩa vụ khi analyze
        self.org_policies = org_policies   # playbook công ty (chính sách bền cấp org)
        self.org_playbook = org_playbook   # flag OFF: đối chiếu HĐ với chính sách khi analyze
        self.nli_verification = nli_verification  # kiểm entailment (nguồn có hậu thuẫn claim) — chống hallucinate
        # Phase B: lớp NLI-mâu-thuẫn nâng unfavorable→illegal khi điều khoản TRÁI điều luật đã grounding.
        self.illegal_detection = illegal_detection
        # Sinh INLINE điều khoản mới (song ngữ) cho rủi ro illegal/must_fix ngay khi rà (bounded, song song).
        self.auto_counter_on_analyze = auto_counter_on_analyze
        self.auto_counter_max = auto_counter_max      # trần số điều khoản auto/lần (chặn spike quota HĐ dài)
        # Auto-counter trong mode=fast: TẮT mặc định (counter flagship ~40s nuốt lợi thế tốc độ fast); deep
        # luôn bật. Bật lại qua env FAST_AUTO_COUNTER nếu muốn counter soạn sẵn trong fast.
        self.fast_auto_counter = fast_auto_counter
        # Coverage-Gated Abstention: cổng relevance quyết trên cụm evidence tập trung (elbow) → chống over-abstain.
        self.coverage_gated_abstain = coverage_gated_abstain
        # HyDE-lite: LLM sinh thuật ngữ luật cầu nối cách-hỏi vs cách-luật-viết → cụm evidence chặt hơn
        # (nâng CHẤT LƯỢNG retrieval cho câu borderline, không tuning gate). Opt-in (thêm 1 call/lookup).
        self.hyde_query_expansion = hyde_query_expansion
        # Cache tra cứu (in-process, bounded LRU): câu hỏi lặp → trả tức thì + tiết kiệm token. KB tĩnh
        # trong 1 phiên deploy nên an toàn; redeploy = process mới = cache mới. 0 = tắt.
        self._lookup_cache_size = lookup_cache_size
        self._lookup_cache: OrderedDict[str, tuple] = OrderedDict()
        # Model trả lời tra cứu: mặc định = reasoner (flagship); prod có thể dùng qwen-plus cho nhanh.
        self.lookup_llm = lookup_llm or reasoner
        # Model tra cứu point-in-time (câu có năm/ngày): flagship (suy luận thời điểm). Container dựng ở
        # temperature=0 → câu trả lời TRA CỨU tất định (hết flaky must_say do sampling). Mặc định = reasoner.
        self.lookup_pit_llm = lookup_pit_llm or reasoner
        # Model RÀ SOÁT NHANH (mode=fast, 1-call). A/B thật (evaluation/fast_ab.py): flash mặc định (nhanh
        # nhất + illegal_recall = plus + 0 over-flag); đổi flagship khi ưu tiên 0 bỏ sót trái luật. Mặc
        # định = judge (flash) → cùng model nhanh; rỗng/stub → reasoner (giữ tương thích).
        self.fast_review_llm = fast_review_llm or self.judge

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

    def monitor(self, org_id: str, country: str, since: str, limit: int = 200) -> dict:
        """AUTOPILOT giám sát chủ động: TỰ quét VB luật MỚI (effective_date >= `since`) → case nào của
        org bị ảnh hưởng (viện dẫn VB bị sửa/thay/hướng dẫn). Không cần người chỉ định từng VB.
        Trả digest {since, new_laws_scanned, affected:[{doc_id,title,effective_date,cases,impacts}]}."""
        if self.cases is None:
            return {"since": since, "new_laws_scanned": 0, "affected": []}
        laws = self.kb.recent(country, since)
        affected = []
        for law in laws:
            impacts = self.regulatory_impact(law["doc_id"], country, org_id, limit)
            if impacts:
                affected.append({"doc_id": law["doc_id"], "title": law["title"],
                                 "effective_date": law["effective_date"],
                                 "cases": sorted({i["case_id"] for i in impacts}), "impacts": impacts})
        # Vòng phản hồi (#3): bỏ cảnh báo đã bị 'báo nhầm' trước đó → chống alert fatigue (autopilot tự hiệu chỉnh).
        dismissed = dismissed_pairs(self.feedback.list_by_org(org_id, 500)) if self.feedback else set()
        affected, suppressed = filter_affected(affected, dismissed)
        if self.observer:
            self.observer.event("monitor", {"org_id": org_id, "since": since, "scanned": len(laws),
                                            "affected": len(affected), "suppressed": suppressed})
        return {"since": since, "new_laws_scanned": len(laws), "affected": affected,
                "suppressed": suppressed}

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

    def negotiate_round(self, deal_context: str, partner_message: str,
                        position: NegotiationPosition | None = None,
                        state: "NegotiationState | None" = None, lang: str = "vi",
                        org_id: str | None = None) -> dict:
        """Một VÒNG đàm phán đa phiên: bối cảnh deal + SỔ nhượng-bộ + tin đối tác → đánh giá + chiến lược
        vòng tới + câu trả lời song ngữ + status (continue/close/walk_away) + sổ nhượng-bộ ĐÃ cập nhật.
        `state` mang qua các vòng (agent nhớ đã nhượng/chốt gì). Lõi 'Autopilot Agent' dẫn đàm phán."""
        from legalguard.domain.negotiation import format_tactics_context
        from legalguard.domain.negotiation import negotiate_round as _round

        # Living flywheel: nạp win-rate lịch sử (kết quả đàm phán THẬT) → agent ưu tiên nước đi từng thành công.
        # CÔ LẬP org (privacy): chỉ dùng outcome của CHÍNH công ty này, không rò từ công ty khác.
        rates = self.outcomes.win_rates(org_id) if self.outcomes else {}
        r = _round(self.reasoner, deal_context=deal_context, partner_message=partner_message,
                   position=position, state=state, tactics_context=format_tactics_context(rates), lang=lang)
        if self.observer:
            self.observer.event("negotiate_round", {"status": r.status, "grounded": r.grounded})
        return asdict(r)

    def compile_memo(self, items: list[dict], title: str = "", protected_party: str = "") -> dict:
        """Phase C: gộp điều khoản đã chọn → bản ghi nhớ sửa đổi (markdown + rows) cho luật sư. Thuần."""
        from legalguard.domain.amendments import compile_memo as _compile

        memo = _compile(items, title=title, protected_party=protected_party)
        if self.observer:
            self.observer.event("compile_memo", {"rows": len(memo.rows), "illegal": memo.illegal_count})
        return asdict(memo)

    def compile_redline(self, items: list[dict], title: str = "", protected_party: str = "") -> dict:
        """Bản ĐỐI CHIẾU sửa đổi (cũ→mới) để xuất .docx (sửa-file Mức 1). Thuần, isolated → accuracy KHÔNG đổi."""
        from legalguard.domain.amendments import compile_redline as _compile

        rl = _compile(items, title=title, protected_party=protected_party)
        if self.observer:
            self.observer.event("compile_redline", {"rows": len(rl.rows), "illegal": rl.illegal_count})
        return asdict(rl)

    def get_case(self, case_id: str) -> AnalysisCase | None:
        return self.cases.get(case_id) if self.cases else None

    def list_cases(self, org_id: str, limit: int = 20) -> list[AnalysisCase]:
        return self.cases.list_by_org(org_id, limit) if self.cases else []

    def delete_case(self, case_id: str) -> bool:
        """Right-to-erasure (PDPD/GDPR): xóa case + CASCADE outcomes & feedback liên quan (không để
        orphan dữ liệu cá nhân). Trả True nếu case tồn tại & đã xóa."""
        if self.cases is None:
            return False
        deleted = self.cases.delete(case_id)
        if deleted:                                  # chỉ cascade khi case thực sự bị xóa
            if self.outcomes is not None:
                self.outcomes.delete_by_case(case_id)
            if self.feedback is not None:
                self.feedback.delete_by_ref(case_id)   # feedback analysis: ref = case_id
            if self.obligations is not None:
                self.obligations.delete_by_case(case_id)
        return deleted

    # ── Nghĩa vụ & hạn chót (SAU KÝ) — API dùng chung cho MỌI kênh (HTTP/Slack/Zalo/MCP) ──
    def extract_and_store_obligations(self, contract_text: str, org_id: str, case_id: str,
                                      contract_end: "date | None" = None) -> int:
        """Trích nghĩa-vụ-có-mốc từ HĐ (thuần domain + reasoner) → gắn id/org/case → lưu. Trả số đã lưu.
        Offline/stub → 0. ISOLATED khỏi vòng agent (không đụng accuracy)."""
        from legalguard.domain.obligations import extract_obligations
        if self.obligations is None:
            return 0
        raw = extract_obligations(self.reasoner, contract_text, contract_end=contract_end)
        now = datetime.now(timezone.utc).isoformat()
        items = [Obligation(id=uuid.uuid4().hex, org_id=org_id, case_id=case_id, created_at=now, **d)
                 for d in raw]
        self.obligations.add_many(items)
        if self.observer:
            self.observer.event("obligations_extracted", {"case_id": case_id, "n": len(items)})
        return len(items)

    def list_obligations(self, org_id: str, within_days: int | None = None,
                         status: str = "pending") -> list[Obligation]:
        return self.obligations.list_by_org(org_id, within_days, status) if self.obligations else []

    def set_obligation_status(self, obligation_id: str, org_id: str, status: str) -> None:
        if self.obligations is not None:
            self.obligations.set_status(obligation_id, org_id, status)

    def obligation_digest(self, org_id: str, within_days: int = 14) -> tuple[list, str]:
        """(danh sách sắp-đến-hạn, digest text KÊNH-AGNOSTIC) — cron/Slack/Zalo/web dùng chung."""
        from legalguard.domain.obligations import format_obligation_digest
        items = self.list_obligations(org_id, within_days=within_days)
        return items, format_obligation_digest(items, date.today())

    def portfolio(self, org_id: str, limit: int = 200) -> list[dict]:
        """Danh mục HĐ hành-động-được (per-HĐ, sắp theo khẩn) — gộp cases + obligations (SẴN CÓ, không LLM).
        Degrade an toàn: chưa bật obligation_tracking → không có 'hạn gần nhất', xếp theo must_fix/duyệt."""
        from legalguard.domain.portfolio import build_portfolio
        cases = self.cases.list_by_org(org_id, limit) if self.cases else []
        obs = self.obligations.list_by_org(org_id, status="pending") if self.obligations else []
        return build_portfolio(cases, obs, date.today())

    # ── Playbook công ty — API dùng chung mọi kênh ──
    def list_policies(self, org_id: str, active_only: bool = True) -> list[OrgPolicy]:
        return self.org_policies.list_by_org(org_id, active_only) if self.org_policies else []

    def upsert_policy(self, policy: OrgPolicy) -> str | None:
        return self.org_policies.upsert(policy) if self.org_policies else None

    def delete_policy(self, policy_id: str, org_id: str) -> bool:
        return self.org_policies.delete(policy_id, org_id) if self.org_policies else False

    def suggest_policies(self, org_id: str, limit: int = 200) -> list[dict]:
        """Gợi ý chính sách từ lịch sử must_fix/illegal của org (người duyệt sửa trước khi lưu)."""
        from legalguard.domain.policy import suggest_policies
        cases = self.cases.list_by_org(org_id, limit) if self.cases else []
        return suggest_policies(cases)

    def health(self) -> dict:
        return {
            "status": "ok",
            "qwen_ready": self.reasoner.available,
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

    def _classify_contract(self, contract_text: str, hint: str, lang: str) -> tuple[str, str, list[str]]:
        """Xác định LOẠI HỢP ĐỒNG + TÊN ĐẦY ĐỦ bên được bảo vệ + LỖI SOẠN THẢO/CHÍNH TẢ trong HĐ (mục cuối
        reply luật sư) — cho dòng đầu reply. 1 call MODEL NHANH (`self.judge`), chạy SONG SONG hậu-agent.
        `hint` = gợi ý bên bảo vệ từ tin chat (vd 'Phu Quoc side') → LLM tinh thành tên pháp lý đầy đủ khớp
        trong HĐ. KHÔNG đụng vòng agent (risk/citation/verify) → KHÔNG ảnh hưởng accuracy golden. Lỗi/offline
        → ('', hint, []) an toàn (không bịa)."""
        hint = (hint or "").strip()
        if not self.judge.available:
            return "", hint, []
        hint_line = f"Gợi ý bên khách muốn bảo vệ (từ người dùng): {hint}\n" if hint else ""
        prompt = (
            "Đọc hợp đồng dưới đây. Trả về DUY NHẤT một JSON (không giải thích thêm) gồm 3 khóa:\n"
            '{"contract_type": "<loại hợp đồng ngắn gọn, vd: hợp đồng mua bán hàng hóa>", '
            '"protected_party": "<TÊN PHÁP LÝ ĐẦY ĐỦ của bên được bảo vệ, lấy đúng trong phần các bên>", '
            '"drafting_issues": [{"location":"<vị trí trong HĐ, vd: Điều 1.2 bản tiếng Anh / Mục (A) Xét rằng>",'
            '"issue":"<mô tả lỗi, nêu rõ đoạn/từ đang SAI>","fix":"<đề xuất sửa 1 ngôn ngữ>",'
            '"fix_vi":"<đề xuất bản tiếng Việt, nếu song ngữ>","fix_en":"<đề xuất bản tiếng Anh, nếu song ngữ>"}]}\n'
            f"{hint_line}"
            "- contract_type/protected_party: nếu có gợi ý → chọn bên KHỚP gợi ý, điền TÊN ĐẦY ĐỦ "
            "(vd 'Công ty Cổ phần …'); không có gợi ý → chọn doanh nghiệp Việt Nam / bên yếu thế hơn; "
            "không xác định được → chuỗi rỗng, KHÔNG bịa.\n"
            "- drafting_issues: LỖI SOẠN THẢO rõ ràng (chính tả, gõ sai/thừa ký tự, sai/thiếu đánh số điều "
            "khoản, tham chiếu để trống, format lộn xộn) VÀ — nếu HĐ có CẢ bản tiếng Việt lẫn tiếng Anh — "
            "điểm KHÔNG THỐNG NHẤT giữa 2 bản (tên bên, tên người, địa chỉ, số liệu, ngày tháng lệch nhau). "
            "KHÔNG liệt kê rủi ro pháp lý ở đây. Mỗi mục nêu `location` (vị trí), `issue` (đoạn sai) + đề xuất "
            "sửa: dùng `fix` cho 1 ngôn ngữ, hoặc `fix_vi`+`fix_en` khi cần sửa cả 2 bản. Đề xuất PHẢI KHÁC "
            "nội dung hiện tại; KHÔNG chép lại đoạn không có lỗi. Không có lỗi → [].\n\n"
            # 12000 (≈ obligations): HĐ SONG NGỮ cần thấy CẢ bản VN lẫn EN để đối chiếu (6000 hay cắt mất
            # nửa EN). Call này chạy riêng qwen-flash, isolated post-agent → không ảnh hưởng accuracy vòng agent.
            f"<<<HỢP ĐỒNG>>>\n{contract_text[:12000]}\n<<<HẾT>>>"
        )
        parsed: dict = {}
        for _ in range(2):        # 1 retry: endpoint dashscope thỉnh thoảng rớt kết nối → thử lại (call rẻ)
            try:
                parsed = _extract_json_obj(self.judge.complete(prompt))
                break
            except LLMError:
                parsed = {}
        ctype = str(parsed.get("contract_type") or "").strip()
        party = str(parsed.get("protected_party") or "").strip() or hint
        notes: list[str] = []
        for it in (parsed.get("drafting_issues") or [])[:10]:     # trần 10 lỗi tránh reply phình
            note = _format_drafting_issue(it)
            if note:
                notes.append(note)
        return ctype, party, notes

    def _summarize(self, risks: list, lang: str) -> tuple[str, str | None]:
        """Tóm tắt rủi ro cho chủ SME bằng MODEL NHANH (`self.judge` = qwen-flash) — task nhẹ, right-size
        như NLI/verify. Trước đây dùng Gemini nhưng đo thấy 1 call Gemini ~12-24s CHIẾM TRỌN post-agent
        (verify+legal_basis chỉ ~1.5s) → nghẽn critical path; Gemini (provider thứ 2 cũ) không còn lý do
        giữ nên đã gỡ. Chuyển flash → post-agent ~24s xuống ~1.5s. Trả (text, note-lỗi-nếu-có) —
        không ném exception (chạy trong thread pool, lỗi phải trả về tường minh)."""
        bullet = "\n".join(f"- {r.clause}: {r.risk} [{r.severity}]" for r in risks)
        prompt = (
            f"Summarize these contract risks briefly for an SME owner:\n{bullet}" if lang == "en"
            else f"Tóm tắt ngắn gọn, dễ hiểu cho chủ SME các rủi ro hợp đồng sau:\n{bullet}"
        )
        try:
            return self.judge.complete(prompt), None
        except LLMError as exc:
            return "", f"⚠️ Không tạo được tóm tắt ({exc.provider}); dùng kết quả agent."

    def analyze(self, contract_text: str, org: Organization, lang: str = "en",
                position: NegotiationPosition | None = None,
                source: SourceMeta | None = None, case_id: str | None = None,
                on_progress: "Callable[[dict], None] | None" = None,
                mode: str = "deep") -> AnalysisResult:
        t0 = time.monotonic()
        jurisdiction = get_tenant(org.country)   # quốc gia → KB luật + bối cảnh

        # Audit fingerprint TRƯỚC redact: hash khớp với văn bản khách đưa (file đã hash
        # ở inbound adapter; text dán trực tiếp → hash tại đây). Không lưu nội dung.
        source = source or SourceMeta.of(contract_text.encode("utf-8"))
        text_chars = len(contract_text)

        # Redact PII TRƯỚC khi gửi LLM / lưu / log (data minimization, OWASP LLM02).
        contract_text, redacted_n = redact(contract_text)

        # Path /analyze: BỎ cross-encoder rerank (rerank=False) — agent chỉ tra chính sách rủi ro/
        # fallback, hybrid RRF (BM25+embedding) là đủ; cắt ~15% latency + giảm tải/request khi đông
        # user. Lookup (Q&A pháp lý cần xếp hạng chính xác) vẫn giữ rerank ở for_org mặc định.
        retriever = self.kb.for_org(org, rerank=False)   # KB quốc gia + overlay riêng công ty
        ctx = AgentContext(retriever=retriever)

        # FAST-PATH (mode="fast"): 1 call fast_review_llm trích rủi ro/fallback (KHÔNG ReAct loop) → end-to-end
        # ~15-18s (fast bỏ auto-counter) thay vì deep ~130s. Ít sâu hơn (không tra KB từng rủi ro) → LUÔN cần
        # luật sư duyệt. Route riêng, post-agent CHUNG → accuracy golden (lookup) KHÔNG đổi. HĐ > _FAST_MAX ký
        # tự → tự về deep (fast 1-call không kham nổi).
        # Dùng fast_review_llm (right-sized qua env): A/B thật (evaluation/fast_ab.py, reps=4) — flash=6s
        # illegal_recall 87.5% + 0 over-flag (MẶC ĐỊNH); plus=18s cùng recall nhưng 25% over-flag; flagship=72s
        # 0 bỏ sót (đổi qua QWEN_FAST_REVIEW_MODEL khi ưu tiên an toàn hơn tốc độ).
        # ĐỘ CHÍNH XÁC: fast NÔNG hơn deep (1-call, KHÔNG tra KB/rủi ro) — model nhanh bỏ sót ~12.5% trái luật
        # → LUÔN needs_human_review; deep vẫn mặc định. _detect_illegal chỉ NÂNG under-flag (hướng bỏ sót có thể
        # được cứu 1 phần nếu grounding tìm ra điều luật), KHÔNG hạ over-flag; lưới an toàn = bắt buộc người duyệt.
        if mode == "fast" and text_chars <= _FAST_MAX:
            from legalguard.domain.fast_review import fast_review
            windows, route = [contract_text], {"label": "nhanh (1-call)", "max_iters": 1}
            trace, truncated, failed_windows = [], False, 0
            strategy = fast_review(self.fast_review_llm, contract_text, jurisdiction.country, lang,
                                   position, ctx, on_progress=on_progress)
            ctx.needs_human_review = True             # màn sàng lọc nhanh → luôn cần người duyệt
            ctx.risks, ctx.fallbacks = _dedupe(ctx.risks), _dedupe(ctx.fallbacks)
            _log.info("fast-path (1 call) %dms", round((time.monotonic() - t0) * 1000))
            return self._finish_analyze(
                ctx=ctx, org=org, jurisdiction=jurisdiction, contract_text=contract_text,
                retriever=retriever, lang=lang, position=position, source=source, case_id=case_id,
                strategy=strategy, trace=trace, truncated=truncated, failed_windows=failed_windows,
                redacted_n=redacted_n, text_chars=text_chars, route=route, windows=windows, t0=t0,
                auto_counter=self.fast_auto_counter)   # fast: BỎ counter flagship (~40s) → ~15-18s

        # Adaptive routing + chunking hợp đồng dài. Các cửa sổ ĐỘC LẬP → chạy SONG SONG
        # (mỗi cửa sổ ctx riêng, merge theo thứ tự — kết quả tất định, ~3× nhanh hơn tuần tự).
        route = _route(contract_text)
        windows = _windows(contract_text)
        contexts = [AgentContext(retriever=retriever) for _ in windows]

        errors: list[LLMError] = []

        # Heartbeat tiến triển: gộp #rủi ro qua các cửa sổ (thread-safe) → báo tổng cho caller (Slack/web).
        # Optional (on_progress None → 0 overhead). KHÔNG đụng nội dung/quyết định agent → accuracy KHÔNG đổi.
        _prog_counts = [0] * len(windows)
        _prog_lock = threading.Lock()

        def _emit(i: int, ev: dict):
            if on_progress is None:
                return
            with _prog_lock:
                _prog_counts[i] = ev.get("risks", 0)
                total = sum(_prog_counts)
            try:
                on_progress({"risks": total, "windows": len(windows)})
            except Exception:  # noqa: BLE001 — progress phụ, không chặn phân tích
                pass

        def _one(i: int):
            # Lỗi LLM ở 1 cửa sổ KHÔNG được xóa kết quả các cửa sổ khác → trả None, gom lỗi.
            try:
                return run_agent(windows[i], jurisdiction.country, self.reasoner, contexts[i],
                                 lang=lang, position=position, max_iters=route["max_iters"],
                                 on_progress=(lambda ev, _i=i: _emit(_i, ev)) if on_progress else None)
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
        return self._finish_analyze(
            ctx=ctx, org=org, jurisdiction=jurisdiction, contract_text=contract_text,
            retriever=retriever, lang=lang, position=position, source=source, case_id=case_id,
            strategy=strategy, trace=trace, truncated=truncated, failed_windows=failed_windows,
            redacted_n=redacted_n, text_chars=text_chars, route=route, windows=windows, t0=t0)

    def _finish_analyze(self, *, ctx: AgentContext, org: Organization, jurisdiction,
                        contract_text: str, retriever, lang: str,
                        position: NegotiationPosition | None, source: SourceMeta,
                        case_id: str | None, strategy: str, trace: list, truncated: bool,
                        failed_windows: int, redacted_n: int, text_chars: int,
                        route: dict, windows: list, t0: float,
                        auto_counter: bool = True) -> AnalysisResult:
        """Hậu-agent CHUNG (deep + fast): win-rate · notes · verify∥summary∥legal_basis · illegal · counter ·
        classify · build result · persist. Tách để fast-path & deep-path dùng CHUNG (một nguồn)."""
        # Outcome-aware ranking: gắn win-rate lịch sử cho mỗi fallback. CÔ LẬP org (privacy + tín hiệu
        # đúng công ty — outcome công ty khác KHÔNG được ảnh hưởng advice công ty này).
        if self.outcomes is not None:
            rates = self.outcomes.win_rates(org.id)
            for f in ctx.fallbacks:
                if f.clause in rates:
                    f.win_rate = rates[f.clause]["rate"]

        notes: list[str] = [f"🧭 Route: {route['label']}"
                            + (f" · chia {len(windows)} đoạn" if len(windows) > 1 else "")]
        # Cảnh báo RÀ NHANH (mode=fast): 1-call nông hơn deep — đo A/B bỏ sót ~12.5% trái luật. Hiện RÕ trên
        # reply mọi kênh (notes + review_reasons) để người dùng KHÔNG nhầm fast với deep; luật sư phải đối chiếu.
        if route.get("max_iters") == 1 and route.get("label", "").startswith("nhanh"):
            notes.append("Bản RÀ NHANH (1-lượt, nông hơn rà Sâu) — có thể BỎ SÓT điều khoản/trái luật; "
                         "luật sư cần đối chiếu bản gốc. Cần chắc chắn hơn → chạy lại chế độ Sâu.")
            ctx.needs_human_review = True
            ctx.review_reasons.append("Bản rà nhanh (nông) — luật sư đối chiếu bản gốc, có thể bỏ sót.")
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
        # Phân loại HĐ + tên đầy đủ bên bảo vệ + lỗi soạn thảo (dòng đầu + mục cuối reply luật sư) —
        # call NHANH, ĐỘC LẬP vòng agent. Chạy TRƯỚC "bão" NLI hậu-agent (verify/basis fire nhiều call
        # qwen-flash đồng thời): nếu để chung pool, dashscope rate-limit/rớt kết nối chính call này (đo
        # thật trên HĐ 18 rủi ro → classify rỗng). Chạy riêng ~1-2s, KHÔNG đáng kể so với vòng agent.
        hint = position.protected_party if position else ""
        contract_type, protected_party, drafting_notes = "", (hint or "").strip(), []
        if self.judge.available:
            contract_type, protected_party, drafting_notes = \
                self._classify_contract(contract_text, hint, lang)
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

        # Phase B — lớp NLI-mâu-thuẫn: nâng unfavorable→illegal khi điều khoản TRÁI điều luật đã grounding
        # (CHẠY SAU legal_basis vì cần `legal_basis`). Bảo thủ: judge nói YES rõ mới gắn 'trái luật'.
        if self.illegal_detection and (upg := _detect_illegal(ctx.risks, self.judge)):
            notes.append(f"⚖️ Phát hiện {upg} điều khoản có dấu hiệu TRÁI LUẬT (đã đối chiếu điều luật) "
                         "— cần luật sư đối chiếu bản gốc.")
            ctx.needs_human_review = True       # illegal là khẳng định mạnh → luôn cần người duyệt
            ctx.review_reasons.append(f"{upg} điều khoản có dấu hiệu trái luật — luật sư đối chiếu bản gốc.")

        # Sinh INLINE điều khoản mới cho rủi ro illegal/must_fix (SAU illegal-detection: nhãn đã chốt +
        # SAU legal_basis: có căn cứ). Song song, bounded, dùng reasoner (flagship). Rủi ro nhẹ → nút.
        # `auto_counter=False` (fast mode) → BỎ để giữ latency ~15-18s; người dùng soạn on-demand qua nút.
        if auto_counter and self.auto_counter_on_analyze and (nc := _attach_counter_clauses(
                ctx.risks, ctx.fallbacks, self.reasoner, self.auto_counter_max)):
            notes.append(f"📝 Đã soạn sẵn điều khoản sửa cho {nc} điều khoản quan trọng (trái luật / bắt buộc sửa).")

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
            contract_type=contract_type,
            protected_party=protected_party,
            drafting_notes=drafting_notes,
            notes=notes,
        )
        result.execution_summary = execution_summary(result.trace)   # bằng chứng agent gọi tool (AI-Native)

        # PLAYBOOK CÔNG TY: đối chiếu HĐ với chính sách org (ISOLATED khỏi vòng agent → accuracy KHÔNG đổi).
        # Flag OFF. TÁCH khỏi "trái luật VN" — đây là "trái CHUẨN công ty" (có thể vẫn hợp pháp).
        if self.org_playbook and self.org_policies is not None:
            try:
                from legalguard.domain.policy import check_policy
                pols = self.org_policies.list_by_org(org.id)
                result.policy_violations = check_policy(result.risks, pols, self.judge)
            except Exception:  # noqa: BLE001 — đối chiếu là phụ, KHÔNG chặn kết quả
                _log.exception("Không đối chiếu được playbook (org=%s)", org.id)

        # Persist case (audit + lịch sử + evidence). Lỗi DB không làm hỏng phân tích.
        if self.cases is not None:
            case = AnalysisCase(
                id=case_id or uuid.uuid4().hex,   # case_id truyền sẵn (async mode) → client poll /cases/{id}
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
            # SAU KÝ: trích nghĩa vụ & hạn chót (ISOLATED khỏi vòng agent → accuracy KHÔNG đổi). Flag OFF.
            if self.obligation_tracking and self.obligations is not None and result.case_id:
                try:
                    self.extract_and_store_obligations(contract_text, org.id, result.case_id)
                except Exception:  # noqa: BLE001 — trích là phụ, KHÔNG chặn kết quả phân tích
                    _log.exception("Không trích được nghĩa vụ (case=%s)", result.case_id)

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
        # overlay=False: /lookup là Q&A DẪN LUẬT → dùng KB quốc gia (điều luật), KHÔNG để lớp tactics moat
        # (premium_tactics.md, phục vụ /analyze) đè điều luật ra khỏi top_k làm hỏng citation accuracy.
        # Mở rộng viết tắt (TNHH→trách nhiệm hữu hạn…) CHỈ cho query retrieval → tăng recall khi luật viết đầy đủ.
        rq = _expand_abbrev(q)
        if self.hyde_query_expansion:            # HyDE-lite: bắc cầu cách-hỏi vs cách-luật-viết (chỉ retrieval)
            rq = _hyde_expand(rq, self.judge)
        snippets = self.kb.for_org(org, overlay=False).retrieve(rq, top_k)
        if not snippets:
            return ("Chưa đủ căn cứ trong cơ sở tri thức để trả lời câu hỏi này."
                    if lang == "vi" else
                    "Not enough grounding in the knowledge base to answer this."), []
        sources = "\n---\n".join(f"[nguồn: {s.source}] {s.text}" for s in snippets)
        # Cổng RELEVANCE (chống over-reach khi KB lớn): nguồn retrieve có THỰC SỰ trả lời câu hỏi không?
        # Judge nói NO rõ → TỪ CHỐI ngay (đừng để LLM "với" sang đoạn cùng từ-vựng nhưng khác chủ đề).
        # Bảo thủ: chỉ abstain khi NO rõ; mơ hồ vẫn trả lời (không giết câu hỏi grounded hợp lệ).
        # COVERAGE-GATED: gate quyết trên cụm evidence TẬP TRUNG (elbow) — không để đoạn nhiễu đuôi pha loãng
        # gây over-abstain (ca point-in-time). Answer vẫn dùng full `sources` (không mất citation).
        # SÀN min_keep=3: cổng relevance KHÔNG được phán "không liên quan" khi chỉ nhìn 1 đoạn — câu trả lời
        # pháp lý thường trải nhiều Điều (vd "thủ tục ly hôn" cần Đ.54 hòa giải + Đ.56 ly hôn theo yêu cầu).
        # elbow thỉnh thoảng cắt còn 1 do điểm embedding hosted dao động ±0.01 → đói bằng chứng → abstain OAN
        # (đo: ca ly hôn lật 6/10 khi keep=1). Giữ ≥ top-3 → judge đủ ngữ cảnh, VẪN cắt đuôi nhiễu (vị trí 4-5).
        # POINT-IN-TIME: câu "văn bản NÀO tại thời điểm T" — bộ lọc in-force/point-in-time ĐÃ chọn đúng VB
        # valid-at-T (làm phần ngữ nghĩa rồi). Gate relevance khi đó second-guess trên nội dung ĐIỀU-KHOẢN của
        # VB (+ đoạn nhiễu đuôi) → phán "không trả lời câu hỏi" → abstain OAN (đo: ca 'Năm 2020 → TT 39/2014'
        # flaky 2/6, gate NO 10/10 dù retrieve đúng rank-1). Bỏ gate cho câu PIT: tin bộ lọc thời gian; answer
        # LLM vẫn tự ghi 'Chưa đủ căn cứ' nếu nguồn thiếu. An toàn: cả 3 ca PIT golden đều abstain=False.
        if self.nli_verification and not _PIT_RE.search(q):
            if self.coverage_gated_abstain:
                keep = elbow_cutoff([s.score for s in snippets], min_keep=3)
                gate_sources = "\n---\n".join(f"[nguồn: {s.source}] {s.text}" for s in snippets[:keep])
            else:
                gate_sources = sources
            if sources_answer_question(q, gate_sources, self.judge) is False:
                return (("Chưa đủ căn cứ trong cơ sở tri thức để trả lời câu hỏi này."
                         if lang == "vi" else
                         "Not enough grounding in the knowledge base to answer this."), [])
        is_enum = bool(_ENUM_RE.search(q))       # câu liệt kê → kể ĐỦ mục (chống sót), không nén 1-3 câu
        if lang == "vi":
            ans_line = ("**Trả lời:** LIỆT KÊ ĐẦY ĐỦ mọi mục/hình thức/trường hợp CÓ trong căn cứ, mỗi mục "
                        "một gạch đầu dòng — KHÔNG bỏ sót mục nào.\n" if is_enum else
                        "**Trả lời:** <1–3 câu trực tiếp; nêu rõ số liệu/mức trần nếu có>\n")
            prompt = (
                "Bạn là LUẬT SƯ tư vấn. CHỈ dùng các đoạn căn cứ dưới đây, KHÔNG bịa. Giọng CHUYÊN NGHIỆP, "
                "súc tích, KHÔNG mở bài rườm rà. Trả lời theo ĐÚNG định dạng sau:\n" + ans_line +
                "**Căn cứ:** mỗi dòng một căn cứ — Điều/Khoản + tên văn bản + ý chính ngắn "
                "(chỉ dùng căn cứ có bên dưới; nếu không đủ ghi 'Chưa đủ căn cứ trong cơ sở tri thức').\n\n"
                f"Căn cứ:\n{sources}\n\nCâu hỏi: {q}\nTrả lời tiếng Việt.")     # q = đã redact (PII)
        else:
            ans_line = ("**Answer:** LIST ALL items/forms/cases present in the sources, one bullet each — "
                        "do NOT omit any.\n" if is_enum else
                        "**Answer:** <1-3 direct sentences; state figures/caps if any>\n")
            prompt = (
                "You are a legal advisor. Use ONLY the sources below, do NOT fabricate. PROFESSIONAL, "
                "concise tone, no preamble. Reply in EXACTLY this format (in English):\n" + ans_line +
                "**Basis:** one citation per line — Article/Clause + document name + short point "
                "(use only the sources below; if insufficient write 'Not enough grounding in the knowledge base').\n\n"
                f"Sources:\n{sources}\n\nQuestion: {q}\nAnswer in English.")     # q = redacted (PII)
        # HYBRID: câu có mốc thời gian (point-in-time) → flagship (chính xác); còn lại → model nhanh.
        # Dùng q (đã redact); năm/ngày KHÔNG bị redact (redact chỉ xóa email + số ≥9 chữ số) nên vẫn nhận.
        llm = self.lookup_pit_llm if _PIT_RE.search(q) else self.lookup_llm
        try:
            answer = llm.complete(prompt)
        except LLMError as exc:
            return f"Chưa trả lời được: {exc}", snippets
        # ĐỘ TIN CẬY (từ tín hiệu ĐÃ TÍNH — NLI + độ tập trung evidence; KHÔNG thêm LLM call). Gộp cảnh báo
        # NLI-phủ-định cũ vào nhãn 'Thấp'. User biết khi nào tin, khi nào cần luật sư đối chiếu.
        from legalguard.domain.confidence import answer_confidence, append_confidence
        nli_ok = nli_supports(answer, sources, self.judge) if self.nli_verification else None
        n_kept = elbow_cutoff([s.score for s in snippets], min_keep=3) if snippets else 0
        answer = append_confidence(answer, answer_confidence(nli_ok, n_kept), lang)   # idempotent (chống lặp)
        if self.observer is not None:
            self.observer.event("lookup", {"tenant": get_tenant(org.country).id,
                                           "lang": lang, "hits": len(snippets)})
        result = (answer, snippets)
        if self._lookup_cache_size:                      # chỉ cache câu trả lời THÀNH CÔNG (không cache lỗi)
            self._lookup_cache[ckey] = result
            if len(self._lookup_cache) > self._lookup_cache_size:
                self._lookup_cache.popitem(last=False)   # đẩy mục cũ nhất ra (LRU evict)
        return result
