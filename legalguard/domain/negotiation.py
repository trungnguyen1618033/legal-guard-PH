"""Đàm phán đa phiên — agent đọc PHẢN HỒI của đối tác qua từng vòng, cập nhật chiến lược.

Khác `analyze` (rà soát 1 lần) và `counter_clause` (soạn 1 điều khoản): đây là VÒNG ĐÀM PHÁN —
nhận bối cảnh deal (từ phân tích trước) + tin nhắn đối tác vừa gửi → đánh giá đối tác nhượng/giữ gì,
cập nhật chiến lược vòng tới, soạn câu trả lời, và khuyến nghị tiếp tục / chốt / rút (walk-away).

Đây là lõi "Autopilot Agent": agent dẫn dắt đàm phán nhiều bước, không chỉ trả lời 1 lần.

SỔ NHƯỢNG-BỘ CÓ CẤU TRÚC (`NegotiationState`): mang qua các vòng để agent NHỚ chính xác đã nhượng/chốt
gì — chống "quên" khi bối cảnh free-text bị cắt cụt (đàm phán nhiều bước hay nhượng lại thứ đã nhượng /
đàm phán lại thứ đối tác đã đồng ý). GUARDRAIL walk-away THUẦN theo red-line: đối tác chặn điểm must-fix +
ta có BATNA → khuyến nghị rút (bảo vệ vị thế tất định, không để agent nhượng tiếp khi điểm sống còn bị chặn).

`_parse_round`, `should_walk_away`, `_merge_unique` THUẦN (test offline). `negotiate_round` rẽ nhánh theo
`reasoner.available`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from legalguard.domain.models import NegotiationPosition
from legalguard.domain.ports import LLMPort

_STATUSES = ("continue", "close", "walk_away")

_SYSTEM = (
    "Bạn là luật sư đàm phán hợp đồng thương mại quốc tế, đại diện cho BÊN ĐƯỢC BẢO VỆ. Mỗi vòng, bạn nhận "
    "bối cảnh deal + SỔ NHƯỢNG-BỘ (đã chốt/đã nhượng/còn mở/điểm red-line KHÔNG nhượng) + tin nhắn mới nhất "
    "của đối tác, rồi: (1) đánh giá đối tác CHẤP NHẬN/TỪ CHỐI/PHẢN-ĐỀ gì; (2) cập nhật chiến lược vòng tới "
    "(còn PHẢI GIỮ gì, NHƯỢNG thêm gì) — TUYỆT ĐỐI không nhượng lại thứ đã nhượng, không đàm phán lại thứ "
    "đối tác đã đồng ý (secured); (3) soạn câu trả lời gửi đối tác song ngữ, chuyên nghiệp, bám vị thế; "
    "(4) khuyến nghị status. Bám căn cứ pháp lý nếu có, KHÔNG bịa số hiệu điều luật. "
    "status: 'continue' (còn đàm phán) | 'close' (điều kiện đã đủ tốt, nên chốt) | 'walk_away' (đối tác không "
    "nhượng điểm sống còn + ta có BATNA → nên rút). "
    "red_line_blocked = true CHỈ KHI đối tác TỪ CHỐI thẳng một điểm trong danh sách red-line (must-fix). "
    "newly_secured/newly_conceded/still_open = CÁC MỤC MỚI của vòng này (ngắn gọn, mỗi mục 1 cụm). "
    'Trả về DUY NHẤT một khối JSON: {"assessment":"<đánh giá phản hồi đối tác>", '
    '"strategy":"<chiến lược vòng tới: giữ/nhượng/walk-away>", "reply_vi":"<câu trả lời tiếng Việt>", '
    '"reply_en":"<English reply to partner>", "newly_secured":["..."], "newly_conceded":["..."], '
    '"still_open":["..."], "red_line_blocked":false, "status":"continue|close|walk_away"}.'
)

_LEVERAGE_VI = {"strong": "mạnh", "balanced": "cân bằng", "weak": "yếu (ưu tiên giữ deal, không đòi quá)"}


def _str_list(v) -> list[str]:
    """Ép về list[str] gọn (bỏ rỗng, cắt khoảng trắng). LLM có thể trả str đơn/None/list lẫn lộn."""
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()]


def _merge_unique(base: list[str], new: list[str]) -> list[str]:
    """Nối `new` vào `base`, khử trùng theo bản chữ-thường (giữ nguyên dạng gốc lần đầu gặp)."""
    seen = {x.strip().lower() for x in base}
    out = list(base)
    for x in new:
        k = x.strip().lower()
        if k and k not in seen:
            out.append(x.strip())
            seen.add(k)
    return out


def should_walk_away(red_line_blocked: bool, has_alternatives: bool) -> bool:
    """Guardrail THUẦN: đối tác chặn một điểm red-line (must-fix) VÀ ta có BATNA (giải pháp thay thế) →
    nên RÚT. Bảo vệ vị thế tất định — không để agent nhượng tiếp/chốt khi điểm sống còn đã bị chặn.
    Không có BATNA → giữ đàm phán (rút mà không có lựa chọn khác là tự hại)."""
    return bool(red_line_blocked and has_alternatives)


def _parse_round(raw: str) -> dict:
    """Rút các trường vòng đàm phán từ phản hồi LLM. Lỗi → assessment=raw rút gọn, status=continue."""
    text = (raw or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL) or \
        re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        try:
            d = json.loads(m.group(1))
            status = str(d.get("status", "continue")).strip().lower()
            if status not in _STATUSES:                       # ép enum hợp lệ (bảo thủ → continue)
                status = "continue"
            return {"assessment": str(d.get("assessment", "")).strip(),
                    "strategy": str(d.get("strategy", "")).strip(),
                    "reply_vi": str(d.get("reply_vi", "")).strip(),
                    "reply_en": str(d.get("reply_en", "")).strip(),
                    "newly_secured": _str_list(d.get("newly_secured")),
                    "newly_conceded": _str_list(d.get("newly_conceded")),
                    "still_open": _str_list(d.get("still_open")),
                    "red_line_blocked": bool(d.get("red_line_blocked", False)),
                    "status": status}
        except (json.JSONDecodeError, AttributeError):
            pass
    return {"assessment": text[:800], "strategy": "", "reply_vi": "", "reply_en": "",
            "newly_secured": [], "newly_conceded": [], "still_open": [],
            "red_line_blocked": False, "status": "continue"}


@dataclass
class NegotiationState:
    """Sổ nhượng-bộ mang qua các vòng — bộ nhớ CÓ CẤU TRÚC của thế trận (chống quên do free-text cắt cụt)."""
    red_lines: list[str] = field(default_factory=list)   # điểm must-fix KHÔNG được nhượng (từ /analyze)
    secured: list[str] = field(default_factory=list)     # đối tác ĐÃ đồng ý → đừng đàm phán lại
    conceded: list[str] = field(default_factory=list)    # ta ĐÃ nhượng → đừng nhượng thêm/lặp
    open_items: list[str] = field(default_factory=list)  # còn tranh chấp


@dataclass
class NegotiationRound:
    assessment: str            # đối tác nhượng/giữ/phản-đề gì
    strategy: str              # chiến lược vòng tới
    reply_vi: str              # câu trả lời gửi đối tác (tiếng Việt)
    reply_en: str              # câu trả lời gửi đối tác (tiếng Anh — sẵn gửi)
    status: str = "continue"   # continue | close | walk_away
    state: NegotiationState = field(default_factory=NegotiationState)  # sổ nhượng-bộ ĐÃ cập nhật
    walk_away_recommended: bool = False   # guardrail red-line: red-line bị chặn + có BATNA
    grounded: bool = True      # False = soạn offline/khung, cần người hoàn thiện


def negotiate_round(reasoner: LLMPort, *, deal_context: str, partner_message: str,
                    position: NegotiationPosition | None = None,
                    state: NegotiationState | None = None, lang: str = "vi") -> NegotiationRound:
    """Một VÒNG đàm phán: bối cảnh deal + SỔ nhượng-bộ + tin đối tác → đánh giá + chiến lược + câu trả lời +
    status + sổ nhượng-bộ ĐÃ cập nhật. `state` mang qua các vòng (agent nhớ đã nhượng/chốt gì).
    Offline (chưa có key) → khung an toàn (grounded=False), KHÔNG bịa."""
    pos = position or NegotiationPosition()
    st = state or NegotiationState()
    protected = pos.protected_party.strip() or "doanh nghiệp Việt Nam"
    if not reasoner.available:
        return NegotiationRound(
            assessment="[CẦN NGƯỜI HOÀN THIỆN] Chưa cấu hình AI — chưa đánh giá được phản hồi đối tác.",
            strategy=f"Giữ các điểm must-fix đã nêu; cân nhắc vị thế {pos.leverage}.",
            reply_vi="", reply_en="", status="continue", state=st, grounded=False)
    ledger = (
        f"SỔ NHƯỢNG-BỘ hiện tại:\n"
        f"- RED-LINE (KHÔNG nhượng): {'; '.join(st.red_lines) or '(chưa có)'}\n"
        f"- ĐÃ CHỐT (đối tác đồng ý, đừng đàm phán lại): {'; '.join(st.secured) or '(chưa có)'}\n"
        f"- TA ĐÃ NHƯỢNG (đừng nhượng thêm/lặp): {'; '.join(st.conceded) or '(chưa có)'}\n"
        f"- CÒN MỞ: {'; '.join(st.open_items) or '(chưa có)'}\n"
    )
    prompt = (
        f"BÊN ĐƯỢC BẢO VỆ: {protected}\n"
        f"VỊ THẾ: lợi thế={_LEVERAGE_VI.get(pos.leverage, pos.leverage)}, độ gấp={pos.urgency}, "
        f"quan hệ={pos.relationship}, có BATNA={pos.alternatives}\n\n"
        f"BỐI CẢNH DEAL (từ phân tích/các vòng trước):\n{deal_context[:4000]}\n\n"
        f"{ledger}\n"
        f"ĐỐI TÁC VỪA PHẢN HỒI:\n{partner_message[:2000]}\n\n"
        f"Đánh giá phản hồi, cập nhật sổ nhượng-bộ (các mục MỚI vòng này) + chiến lược vòng tới, soạn câu "
        f"trả lời ({'tiếng Việt + tiếng Anh' if lang == 'vi' else 'English + Vietnamese'}), đề xuất status."
    )
    parsed = _parse_round(reasoner.complete(prompt, system=_SYSTEM))
    new_state = NegotiationState(
        red_lines=list(st.red_lines),                                  # red-line do người/analyze đặt, không tự đổi
        secured=_merge_unique(st.secured, parsed["newly_secured"]),
        conceded=_merge_unique(st.conceded, parsed["newly_conceded"]),
        open_items=parsed["still_open"] or list(st.open_items))        # còn-mở = ảnh chụp vòng này (LLM), giữ cũ nếu rỗng
    walk = should_walk_away(parsed["red_line_blocked"], pos.alternatives)
    status = parsed["status"]
    strategy = parsed["strategy"]
    if walk and status != "walk_away":                                 # guardrail tất định GHI ĐÈ: red-line bị chặn +
        status = "walk_away"                                           # có BATNA → không để agent chốt/nhượng tiếp
        strategy = (strategy + " " if strategy else "") + \
            "[GUARDRAIL] Đối tác chặn điểm red-line (must-fix) và ta có BATNA → khuyến nghị RÚT."
    return NegotiationRound(assessment=parsed["assessment"], strategy=strategy,
                            reply_vi=parsed["reply_vi"], reply_en=parsed["reply_en"],
                            status=status, state=new_state, walk_away_recommended=walk, grounded=True)
