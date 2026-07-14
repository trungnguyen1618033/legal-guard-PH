"""ĐƯỜNG NHANH (fast-path) — rà soát HĐ bằng 1 LLM call, KHÔNG vòng ReAct.

Đổi tốc lấy độ sâu: agent đầy đủ = 3–6 call flagship TUẦN TỰ (~100s); fast = 1 call trích rủi ro/fallback.
Caller RIGHT-SIZE model: dùng qwen-plus (lookup_llm) ~15s (ngang ChatGPT) — đo thật flagship=61s, plus=15s
VẪN bắt trái luật, flash=5s BỎ SÓT illegal (loại). Ít sâu hơn (KHÔNG tra KB từng rủi ro trong lúc trích) →
LUÔN cần luật sư duyệt. Populate `ctx` QUA `execute_tool` (dùng CHUNG QA + shape Risk/Fallback với agent) →
post-agent (legal_basis/illegal/counter/verify) CHẠY Y HỆT → over-flag nhẹ của plus được verify lại.
Route riêng, opt-in → KHÔNG đụng accuracy golden (đó là lookup).
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable

from legalguard.domain.models import AgentContext, NegotiationPosition
from legalguard.domain.ports import LLMPort
from legalguard.domain.tools import execute_tool

_SYSTEM = (
    "Bạn là luật sư rà soát hợp đồng (tài phán: __COUNTRY__), làm việc CHO BÊN ĐƯỢC BẢO VỆ. Trả về DUY NHẤT "
    "một JSON, KHÔNG giải thích thêm:\n"
    '{"risks":[{"clause":"<tên/điều khoản>","risk":"<vì sao rủi ro/bất lợi>","evidence":"<TRÍCH NGUYÊN VĂN '
    'từ hợp đồng>","severity":"low|medium|high","priority":"must_fix|negotiate|acceptable","legal_status":'
    '"illegal|unfavorable","violated_law":"<điều luật nếu illegal, vd Điều 301>"}],'
    '"fallbacks":[{"clause":"<khớp clause ở trên>","suggestion":"<hướng sửa cụ thể>","english_reply":'
    '"<câu gửi đối tác, tiếng Anh>"}],"strategy":"<chiến lược đàm phán: giữ gì/nhượng gì/điểm rút>"}\n'
    "legal_status=illegal CHỈ khi vi phạm rõ quy định bắt buộc (vd phạt > trần 8% Điều 301); nghi ngờ → "
    "unfavorable (bảo thủ). CHỈ dùng thuật ngữ pháp lý VN chuẩn; KHÔNG bịa. Đây là RÀ SOÁT NHANH.\n"
    "CHỌN LỌC (giảm báo dư): CHỈ nêu điều khoản THỰC SỰ rủi ro/bất lợi cho BÊN ĐƯỢC BẢO VỆ hoặc trái luật. "
    "BỎ QUA điều khoản TIÊU CHUẨN/vô hại: thông báo, hiệu lực, mô tả (diện tích/số lượng), sửa đổi bằng văn "
    "bản, nghiệm thu/kiểm tra thông thường, cách trả lương, kỳ hạn trung tính, trọng tài VIAC chuẩn, mức phạt "
    "TRONG trần luật (≤8% thương mại), lãi TRONG trần (≤20%/năm). Nếu điều khoản cân bằng/thông lệ → KHÔNG nêu. "
    "Thà bỏ 1 mục vô hại còn hơn ngập báo dư — nhưng TUYỆT ĐỐI không bỏ điều khoản trái luật hay bất lợi rõ."
)


def _parse(raw: str) -> dict:
    """Rút JSON {risks,fallbacks,strategy} từ output LLM (chịu ```json fence / text thừa). Lỗi → rỗng."""
    s = (raw or "").strip()
    if "```" in s:
        s = re.sub(r"```(?:json)?", "", s).strip("` \n")
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if not m:
        return {}
    try:
        d = json.loads(m.group(0))
        return d if isinstance(d, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def fast_review(reasoner: LLMPort, contract_text: str, country: str, lang: str,
                position: NegotiationPosition | None, ctx: AgentContext,
                on_progress: "Callable[[dict], None] | None" = None) -> str:
    """1 call flagship → trích rủi ro/fallback vào `ctx` (qua execute_tool) → trả strategy. Offline/lỗi/parse
    hỏng → ctx rỗng + strategy rỗng (không bịa; caller đánh dấu cần người duyệt)."""
    if not reasoner.available:
        return ""
    pos = position or NegotiationPosition()
    protected = pos.protected_party.strip() or f"the SME client in {country}"
    prompt = (f"BÊN ĐƯỢC BẢO VỆ: {protected}. Vị thế: leverage={pos.leverage}, urgency={pos.urgency}, "
              f"BATNA={pos.alternatives}.\n\n<<<HỢP ĐỒNG>>>\n{contract_text}\n<<<HẾT>>>")
    try:
        parsed = _parse(reasoner.complete(prompt, system=_SYSTEM.replace("__COUNTRY__", country)))
    except Exception:  # noqa: BLE001 — LLM lỗi → rỗng an toàn (caller vẫn trả result + cần người duyệt)
        return ""
    for r in (parsed.get("risks") or [])[:30]:        # trần chống output rác phình
        if isinstance(r, dict):
            execute_tool("flag_risk", r, ctx)         # dùng CHUNG QA (ép enum) + shape Risk với agent
    for f in (parsed.get("fallbacks") or [])[:30]:
        if isinstance(f, dict):
            execute_tool("propose_fallback", f, ctx)
    if on_progress is not None:
        try:
            on_progress({"risks": len(ctx.risks), "windows": 1})
        except Exception:  # noqa: BLE001 — progress phụ
            pass
    return str(parsed.get("strategy") or "").strip()
