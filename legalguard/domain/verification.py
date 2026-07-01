"""Verification pass — chống hallucination cho domain pháp lý (2 lớp), TỐI ƯU call.

1. Clause-existence (offline, miễn phí): `evidence` phải có thật trong hợp đồng.
2. LLM-as-judge GỘP: 1 call duy nhất chấm TẤT CẢ rủi ro (thay vì 1 call/rủi ro) + 1 retrieval
   gộp → giảm mạnh số LLM call (tăng năng lực ~2×, giảm chi phí & rủi ro rate-limit).
Offline (judge chưa cấu hình) → chỉ lớp 1.
"""
from __future__ import annotations

import re

from legalguard.domain.models import Risk
from legalguard.domain.ports import KnowledgeBasePort, LLMError, LLMPort

_BATCH_PROMPT = (
    "Context (knowledge base):\n{ctx}\n\n"
    "Với MỖI mục dưới đây, rủi ro có được Context ở trên hậu thuẫn không?\n{items}\n\n"
    "Trả lời MỖI mục đúng một dòng theo dạng `<số>: YES` hoặc `<số>: NO`."
)
_VERDICT = re.compile(r"(\d+)\s*[:.\-)]\s*(YES|NO|CÓ|KHÔNG)", re.IGNORECASE)

_NLI_PROMPT = (
    "Căn cứ:\n{evidence}\n\nKhẳng định: {claim}\n\n"
    "Căn cứ trên có HẬU THUẪN (trực tiếp ủng hộ) khẳng định không? Chỉ trả lời đúng một từ: YES hoặc NO."
)
_NLI_YES = re.compile(r"\b(YES|CÓ)\b", re.IGNORECASE)
_NLI_NO = re.compile(r"\b(NO|KHÔNG)\b", re.IGNORECASE)

_CONTRADICT_PROMPT = (
    "Điều luật (quy định pháp luật):\n{article}\n\n"
    "Điều khoản trong hợp đồng:\n{clause}\n\n"
    "Điều khoản hợp đồng này có VI PHẠM / TRÁI với quy định BẮT BUỘC của điều luật trên không "
    "(tức có thể bị VÔ HIỆU)? Chỉ trả lời YES nếu CHẮC CHẮN trái quy định bắt buộc; nếu chỉ bất lợi "
    "nhưng hợp pháp, hoặc không chắc, hãy trả lời NO. Chỉ trả đúng một từ: YES hoặc NO."
)
# Parser CHẶT cho illegal (bất đối xứng — false-positive 'trái luật' = trách nhiệm pháp lý lớn):
# NO/KHÔNG → False (hướng an toàn); CHỈ 'YES' tiếng Anh → True. KHÔNG nhận 'CÓ' (va 'có thể' = maybe).
_CONTRADICT_YES = re.compile(r"\bYES\b", re.IGNORECASE)


def nli_supports(claim: str, evidence: str, judge: LLMPort, max_chars: int = 1500) -> bool | None:
    """Kiểm entailment: `evidence` CÓ hậu thuẫn `claim` không (chống 'citation tồn tại nhưng không hỗ trợ').
    True = có, False = không, None = không kết luận được (judge offline/lỗi/đáp mơ hồ). LLM-based (swap NLI
    model nhỏ như MiniCheck/AlignScore sau qua cùng chữ ký)."""
    if not judge.available or not claim.strip() or not evidence.strip():
        return None
    try:
        out = judge.complete(_NLI_PROMPT.format(evidence=evidence[:max_chars], claim=claim[:500]))
    except LLMError:
        return None
    if _NLI_NO.search(out):           # ưu tiên NO (thận trọng: nghi ngờ → coi như không hỗ trợ)
        return False
    if _NLI_YES.search(out):
        return True
    return None


def nli_contradicts(clause: str, article: str, judge: LLMPort, max_chars: int = 1500) -> bool | None:
    """Kiểm điều khoản hợp đồng có TRÁI/VI PHẠM điều luật `article` không (đảo chiều `nli_supports`).
    Dùng cho Phase B phát hiện TRÁI LUẬT có grounding: chỉ chạy trên điều luật THẬT đã retrieve.
    True = trái luật (có thể vô hiệu), False = không, None = không kết luận (judge offline/lỗi/mơ hồ).
    BẢO THỦ: nghi ngờ/mơ hồ → coi như KHÔNG trái luật (gắn 'illegal' sai = trách nhiệm pháp lý lớn)."""
    if not judge.available or not clause.strip() or not article.strip():
        return None
    try:
        out = judge.complete(_CONTRADICT_PROMPT.format(article=article[:max_chars], clause=clause[:500]))
    except LLMError:
        return None
    if _NLI_NO.search(out):           # ưu tiên NO (thận trọng: nghi ngờ → không phải trái luật)
        return False
    if _CONTRADICT_YES.search(out):   # CHỈ 'YES' tiếng Anh (bỏ 'CÓ' để tránh 'có thể' → illegal sai)
        return True
    return None


_RELEVANCE_PROMPT = (
    "Câu hỏi: {question}\n\nCác đoạn căn cứ từ cơ sở tri thức:\n{sources}\n\n"
    "Các đoạn căn cứ TRÊN có chứa thông tin để trả lời TRỰC TIẾP câu hỏi không? "
    "Trả lời YES nếu có đủ căn cứ liên quan để trả lời; trả lời NO nếu các đoạn này nói về "
    "vấn đề KHÁC / không liên quan tới câu hỏi. Chỉ trả đúng một từ: YES hoặc NO."
)


def sources_answer_question(question: str, sources: str, judge: LLMPort,
                            max_chars: int = 3000) -> bool | None:
    """Cổng RELEVANCE cho tra cứu: các `sources` đã retrieve có THỰC SỰ trả lời được `question` không?
    Chống over-reach khi KB lớn trả về đoạn cùng từ-vựng nhưng KHÁC chủ đề (vd hỏi 'ưu đãi đầu tư FDI'
    → vớ điều về xã hội hóa nhà trẻ). True = trả lời được, False = không liên quan (nên TỪ CHỐI),
    None = không kết luận (judge offline/lỗi/mơ hồ). BẢO THỦ ngược nli_supports: chỉ TỪ CHỐI khi judge
    nói NO RÕ — mơ hồ thì vẫn cho trả lời (tránh over-abstain giết câu hỏi grounded hợp lệ)."""
    if not judge.available or not question.strip() or not sources.strip():
        return None
    try:
        out = judge.complete(_RELEVANCE_PROMPT.format(question=question[:500], sources=sources[:max_chars]))
    except LLMError:
        return None
    if _NLI_NO.search(out):           # CHỈ NO rõ → không liên quan (abstain); else cho trả lời
        return False
    if _NLI_YES.search(out):
        return True
    return None


def elbow_cutoff(scores: list[float], min_keep: int = 1) -> int:
    """SỐ phần tử thuộc cụm điểm mạnh (elbow): cắt tại khe hụt lớn nhất → tách cụm evidence tập trung khỏi
    đuôi nhiễu. CHỈ cắt khi khe đủ rõ (> 1.5× khe trung bình); điểm giảm đều/không có khuỷu rõ → giữ hết
    (không over-cut). Luôn giữ >= min_keep. THUẦN (test offline).

    ƯỚC LƯỢNG cỡ cụm trên điểm ĐÃ SẮP GIẢM DẦN — bền với input KHÔNG đơn điệu (vd citation-closure APPEND
    đoạn dẫn-chiếu đã decay ở cuối list → không còn giảm dần; nếu tính gap theo thứ tự gốc sẽ ra khe âm/cắt
    sai). Caller lấy `snippets[:keep]` theo thứ tự HẠNG (top-first) — dùng cỡ cụm này là số đoạn mạnh cần giữ.

    Dùng cho Coverage-Gated Abstention: cho cổng relevance quyết trên cụm evidence tập trung, không để đoạn
    nhiễu cùng-từ-vựng pha loãng gây over-abstain (ca point-in-time). Ca ngoài-KB: điểm yếu/rải đều → không cắt."""
    n = len(scores)
    if n <= min_keep:
        return n
    ordered = sorted(scores, reverse=True)           # bền input không-đơn-điệu: gap có nghĩa trên bản giảm dần
    gaps = [ordered[i] - ordered[i + 1] for i in range(n - 1)]
    max_gap = max(gaps)
    avg_gap = sum(gaps) / len(gaps)
    if avg_gap <= 0 or max_gap < 1.5 * avg_gap:      # điểm bằng nhau / không có khuỷu rõ → giữ hết
        return n
    return max(min_keep, gaps.index(max_gap) + 1)    # số phần tử tới TRƯỚC khe lớn nhất


_QUOTES = "\"'“”‘’„«»`"   # model hay BỌC evidence trong ngoặc → strip trước khi so (tránh false-negative)


def _norm_ev(s: str) -> str:
    """Chuẩn hóa để so khớp evidence ↔ hợp đồng: gộp khoảng trắng + bỏ ngoặc kép bao quanh + thường hóa.
    Sửa false-negative: agent trả `\"Điều 2...\"` (có ngoặc/xuống dòng khác) tuy CÓ trong HĐ vẫn bị trượt."""
    return re.sub(r"\s+", " ", s).strip().strip(_QUOTES).strip().lower()


def verify_risks(risks: list[Risk], contract_text: str, retriever: KnowledgeBasePort,
                 judge: LLMPort) -> list[str]:
    notes: list[str] = []
    contract_low = _norm_ev(contract_text)

    # Lớp 1: evidence phải có thật trong hợp đồng (miễn phí, language-agnostic). So sau khi chuẩn hóa.
    for r in risks:
        if r.evidence and _norm_ev(r.evidence) not in contract_low:
            r.verified = False

    if not judge.available:
        if risks:
            notes.append("ℹ️ Verification: chỉ kiểm clause-existence (LLM-judge offline).")
        return _summary_note(risks, notes)

    # Lớp 2: GỘP — 1 retrieval + 1 judge call cho mọi rủi ro còn hợp lệ.
    to_judge = [r for r in risks if r.verified]
    if to_judge:
        query = " ".join(f"{r.clause} {r.risk}" for r in to_judge)
        ctx = "\n".join(s.text for s in retriever.retrieve(query, top_k=5))
        items = "\n".join(f"{i}. {r.clause}: {r.risk}" for i, r in enumerate(to_judge, 1))
        try:
            out = judge.complete(_BATCH_PROMPT.format(ctx=ctx, items=items))
            verdicts = {int(n): v.upper() in ("NO", "KHÔNG") for n, v in _VERDICT.findall(out)}
            for i, r in enumerate(to_judge, 1):
                if verdicts.get(i):     # chỉ loại khi judge nói NO rõ ràng
                    r.verified = False
        except LLMError:
            pass  # không kết luận được → giữ verified, để người duyệt

    return _summary_note(risks, notes)


def _summary_note(risks: list[Risk], notes: list[str]) -> list[str]:
    unverified = sum(1 for r in risks if not r.verified)
    if unverified:
        notes.append(f"⚠️ {unverified} rủi ro chưa được xác minh (evidence/KB) — cần chuyên gia duyệt.")
    return notes
