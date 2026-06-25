"""Counter-clause generation — biến fallback (gợi ý đàm phán) thành ĐIỀU KHOẢN PHẢN-ĐỀ song ngữ.

Khác `Fallback.english_reply` (câu nhắn đối tác): đây là VĂN BẢN ĐIỀU KHOẢN thay thế, dán thẳng vào
hợp đồng được. Bám `legal_basis` (căn cứ đã grounding) + vị thế đàm phán. LLM (Qwen reasoner) soạn;
offline (chưa có key) → trả khung an toàn, KHÔNG bịa luật.

Hàm `_parse_counter` thuần (test offline). `draft_counter_clause` rẽ nhánh theo `reasoner.available`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from legalguard.domain.ports import LLMPort

_SYSTEM = (
    "Bạn là luật sư thương mại Việt Nam, soạn điều khoản hợp đồng thay thế (counter-clause) bảo vệ "
    "doanh nghiệp Việt (bên thường yếu thế) trong hợp đồng quốc tế. Soạn ngắn gọn, đúng chuẩn hợp đồng, "
    "song ngữ Việt–Anh. CHỈ dựa trên căn cứ pháp lý được cung cấp; không bịa số hiệu điều luật. "
    'Trả về DUY NHẤT một khối JSON: {"vi": "<điều khoản tiếng Việt>", "en": "<English clause>", '
    '"rationale": "<vì sao, 1-2 câu, bám căn cứ + vị thế>"}.'
)

_LEVERAGE_VI = {"strong": "mạnh (có thể yêu cầu sửa)", "balanced": "cân bằng",
                "weak": "yếu (ưu tiên phương án thỏa hiệp, không đòi quá)"}


def _parse_counter(raw: str) -> dict:
    """Rút {vi, en, rationale} từ phản hồi LLM (khối ```json hoặc {...} trần). Lỗi → vi = raw rút gọn."""
    text = (raw or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL) or \
        re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        try:
            d = json.loads(m.group(1))
            return {"vi": str(d.get("vi", "")).strip(), "en": str(d.get("en", "")).strip(),
                    "rationale": str(d.get("rationale", "")).strip()}
        except (json.JSONDecodeError, AttributeError):
            pass
    return {"vi": text[:800], "en": "", "rationale": ""}


@dataclass
class CounterClause:
    clause: str           # điều khoản gốc (bị thay)
    vi: str               # bản tiếng Việt đề xuất
    en: str               # bản tiếng Anh đề xuất (dán vào HĐ)
    rationale: str        # lý do (bám căn cứ + vị thế)
    legal_basis: str = "" # căn cứ pháp lý kèm theo (nếu có)
    grounded: bool = True  # False = soạn offline/khung, cần luật sư hoàn thiện


def draft_counter_clause(reasoner: LLMPort, *, clause: str, risk: str = "", suggestion: str = "",
                         legal_basis: str = "", leverage: str = "balanced") -> CounterClause:
    """Soạn điều khoản phản-đề song ngữ cho 1 điều khoản rủi ro. Offline → khung an toàn (grounded=False)."""
    if not reasoner.available:
        vi = (f"[CẦN LUẬT SƯ HOÀN THIỆN] Đề xuất sửa điều khoản “{clause}”: {suggestion or risk}. "
              + (f"Căn cứ: {legal_basis}." if legal_basis else ""))
        return CounterClause(clause=clause, vi=vi.strip(), en="", rationale=suggestion,
                             legal_basis=legal_basis, grounded=False)
    prompt = (
        f"Điều khoản gốc (đối tác áp): {clause}\n"
        f"Rủi ro với doanh nghiệp Việt: {risk}\n"
        f"Hướng thỏa hiệp mong muốn: {suggestion}\n"
        f"Căn cứ pháp lý (đã đối chiếu, dùng nguyên văn, không bịa thêm): {legal_basis or '(không có)'}\n"
        f"Vị thế đàm phán: {_LEVERAGE_VI.get(leverage, leverage)}\n\n"
        "Soạn điều khoản thay thế theo hướng thỏa hiệp trên."
    )
    parsed = _parse_counter(reasoner.complete(prompt, system=_SYSTEM))
    return CounterClause(clause=clause, vi=parsed["vi"], en=parsed["en"],
                         rationale=parsed["rationale"], legal_basis=legal_basis, grounded=True)
