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
    "Thà bỏ 1 mục vô hại còn hơn ngập báo dư — nhưng TUYỆT ĐỐI không bỏ điều khoản trái luật hay bất lợi rõ.\n"
    "VÍ DỤ LUẬT SƯ DUYỆT (học ranh giới — KHÔNG copy nguyên văn):\n"
    "- 'Điều 3. Lãi suất: 60%/năm; lãi quá hạn bằng 200% lãi trong hạn.' → NÊU — TRÁI LUẬT [Khoản 1 Điều 468, "
    "khoản 5 Điều 466 BLDS 2015; Điều 5, Điều 9 Nghị quyết 01/2019/NQ-HĐTP]\n"
    "- 'Điều 6. Mục đích vay: Bên vay dùng vốn đúng mục đích kinh doanh đã khai.' → BỎ — vô hại [Điều 467 BLDS 2015]\n"
    "- 'Điều 6. Phạt vi phạm hợp đồng: 50% giá trị đơn hàng nếu hủy đơn.' → NÊU — TRÁI LUẬT [Điều 300, Điều 301 "
    "Luật Thương mại 2005]\n"
    "- 'Điều 8. Giao hàng: giao tại kho Bên A trong 15 ngày kể từ đặt hàng.' → BỎ — vô hại [Điều 34, Điều 35, "
    "Điều 37 Luật Thương mại 2005]\n"
    "- 'Điều 3. Thử việc: 6 tháng với lương 70% lương chính thức.' → NÊU — TRÁI LUẬT [Điều 25, Điều 26 Bộ luật "
    "Lao động 2019]\n"
    "- 'Điều 7. Nghỉ phép: người lao động được 12 ngày phép năm.' → BỎ — vô hại [Điều 113, Điều 114 Bộ luật Lao "
    "động 2019]\n"
    "- 'Điều 4. Chuyển rủi ro: Bên B (bán) chịu mọi rủi ro tới khi Bên A xác nhận nhận đủ, không theo Incoterms.' "
    "→ NÊU — BẤT LỢI [Điều 57 đến Điều 61 Luật Thương mại 2005]\n"
    "- 'Điều 12. Ngôn ngữ: hợp đồng lập bằng tiếng Việt và tiếng Anh, bản tiếng Anh ưu tiên.' → NÊU — BẤT LỢI "
    "[Điều 398 BLDS 2015; Điều 96 BLTTDS 2015]\n"
    "- 'Điều 3. Phạt vi phạm: phạt 6% giá trị phần nghĩa vụ vi phạm.' → BỎ — vô hại [Điều 300, Điều 301 Luật "
    "Thương mại 2005]\n"
    "- 'Điều 5. Bảo mật: hai bên giữ bí mật thông tin trong thời hạn hợp đồng.' → BỎ — vô hại [Điều 385, Điều "
    "398 BLDS 2015]\n"
    "- 'Điều 11. Giải quyết tranh chấp: tranh chấp giải quyết tại VIAC theo Quy tắc VIAC.' → BỎ — vô hại [Điều "
    "2, Điều 5, Điều 16 Luật Trọng tài thương mại]\n"
    "- 'Điều 13. Hiệu lực: hợp đồng có hiệu lực kể từ ngày hai bên ký.' → BỎ — vô hại [Điều 400, Điều 401 BLDS 2015]"
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
    """1 call flagship → trích rủi ro/fallback vào `ctx` (qua execute_tool) → trả strategy. Parse hỏng → ctx
    rỗng (không bịa). LLM LỖI (LLMError) → NỔI LÊN cho caller đếm cửa sổ lỗi (không nuốt → không mất đoạn âm
    thầm). KHÔNG bail khi !available — `complete` xử lý (stub JSON offline, như deep dùng chat-stub → test/demo)."""
    pos = position or NegotiationPosition()
    protected = pos.protected_party.strip() or f"the SME client in {country}"
    prompt = (f"BÊN ĐƯỢC BẢO VỆ: {protected}. Vị thế: leverage={pos.leverage}, urgency={pos.urgency}, "
              f"BATNA={pos.alternatives}.\n\n<<<HỢP ĐỒNG>>>\n{contract_text}\n<<<HẾT>>>")
    # LLM lỗi (rate-limit hết retry…) → ĐỂ NỔI LÊN cho caller ĐẾM cửa sổ lỗi (map-reduce) / đánh dấu (single)
    # → post-agent gắn note "N phân đoạn lỗi — chưa rà hết". KHÔNG nuốt (chống mất cả đoạn ÂM THẦM).
    parsed = _parse(reasoner.complete(prompt, system=_SYSTEM.replace("__COUNTRY__", country)))
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
