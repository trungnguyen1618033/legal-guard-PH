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


def verify_risks(risks: list[Risk], contract_text: str, retriever: KnowledgeBasePort,
                 judge: LLMPort) -> list[str]:
    notes: list[str] = []
    contract_low = contract_text.lower()

    # Lớp 1: evidence phải có thật trong hợp đồng (miễn phí, language-agnostic).
    for r in risks:
        if r.evidence and r.evidence.lower() not in contract_low:
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
