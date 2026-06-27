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
