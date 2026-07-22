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
import unicodedata
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
    "(4) đề xuất THANG NHƯỢNG-BỘ (next_moves): 1-3 nước đi TRAO ĐỔI cho vòng tới — mỗi nước = NHƯỢNG một "
    "điểm RẺ-với-ta ĐỂ ĐỔI LẤY chốt một điểm CÒN MỞ có giá trị; hiệu chỉnh theo lợi thế (mạnh→đòi nhiều, "
    "nhượng ít; yếu→ưu tiên giữ deal). TUYỆT ĐỐI KHÔNG đề xuất nhượng điểm red-line. "
    "GIỚI HẠN PHÁP LÝ = RED-LINE CỨNG: điều khoản TRÁI LUẬT (vượt TRẦN luật định — vd phạt vi phạm >8% theo "
    "Điều 301 Luật Thương mại) thì PHẦN VƯỢT VÔ HIỆU → TUYỆT ĐỐI KHÔNG chấp nhận/chốt mức TRÊN trần luật, KỂ CẢ "
    "khi đối tác đề nghị HAY khi áp dụng HAI CHIỀU (hai chiều KHÔNG cứu phần vượt trần — vẫn vô hiệu). Chỉ chốt "
    "ở mức ≤ trần luật (vd 8%); đối tác KIÊN QUYẾT giữ mức trái luật = red_line_blocked=true. "
    "(5) khuyến nghị status. Bám căn cứ pháp lý nếu có, KHÔNG bịa số hiệu điều luật. "
    "status: 'continue' (còn đàm phán) | 'close' (điều kiện đã đủ tốt, nên chốt) | 'walk_away' (đối tác không "
    "nhượng điểm sống còn + ta có BATNA → nên rút). "
    "red_line_blocked = true CHỈ KHI đối tác TỪ CHỐI thẳng một điểm trong danh sách red-line (must-fix). "
    "newly_secured/newly_conceded/still_open = CÁC MỤC MỚI của vòng này (ngắn gọn, mỗi mục 1 cụm). "
    'Trả về DUY NHẤT một khối JSON: {"assessment":"<đánh giá phản hồi đối tác>", '
    '"strategy":"<chiến lược vòng tới: giữ/nhượng/walk-away>", "reply_vi":"<câu trả lời tiếng Việt>", '
    '"reply_en":"<English reply to partner>", "newly_secured":["..."], "newly_conceded":["..."], '
    '"still_open":["..."], "next_moves":[{"offer":"<nhượng gì (rẻ với ta)>","in_return_for":"<đổi lấy chốt '
    'điểm nào>","why":"<vì sao hợp lý theo vị thế>"}], "red_line_blocked":false, '
    '"status":"continue|close|walk_away"}.'
)

# Stopword VN (từ chức năng) — bỏ khi so nước-đi với red-line để giảm khớp giả (chỉ token đặc trưng mới tính).
_STOP = {"phải", "tại", "của", "cho", "các", "một", "trong", "được", "này", "đối", "tác", "và", "với",
         "theo", "khi", "thì", "sang", "về", "bên", "điểm", "việc", "sẽ", "đã", "còn"}

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


def _key_tokens(s: str) -> set[str]:
    """Token đặc trưng (NFC, thường, len≥3, bỏ stopword) để so nước-đi với red-line."""
    toks = re.findall(r"\w+", unicodedata.normalize("NFC", (s or "").lower()))
    return {t for t in toks if len(t) >= 3 and t not in _STOP}


def _touches(offer: str, red_line: str) -> bool:
    """Nước đi 'nhượng' CÓ đụng điểm red-line không? Substring hoặc ≥2 token đặc trưng chung (bảo thủ →
    thà gắn cờ oan còn hơn để lọt nhượng điểm sống còn; cờ hiển thị cho người, không tự ý bỏ nước đi)."""
    o, r = offer.strip().lower(), red_line.strip().lower()
    if not o or not r:
        return False
    if o in r or r in o:
        return True
    return len(_key_tokens(o) & _key_tokens(r)) >= 2


def screen_moves(moves: list[dict], red_lines: list[str]) -> list[dict]:
    """Gắn cờ `near_red_line` cho từng nước đi đụng điểm red-line (bảo vệ TẤT ĐỊNH — LLM có thể lỡ gợi ý
    nhượng điểm sống còn). THUẦN (test offline). Không bỏ nước đi, chỉ đánh dấu để UI/người quyết."""
    out = []
    for m in moves:
        offer = str(m.get("offer", ""))
        flagged = any(_touches(offer, rl) for rl in red_lines)
        out.append({"offer": offer, "in_return_for": str(m.get("in_return_for", "")).strip(),
                    "why": str(m.get("why", "")).strip(), "near_red_line": flagged})
    return out


def format_tactics_context(win_rates: dict, limit: int = 6) -> str:
    """Tóm tắt WIN-RATE lịch sử (kết quả đàm phán THẬT — moat flywheel) → context cho vòng đàm phán:
    agent ưu tiên GIỮ điểm win-rate cao (đối tác hay chấp nhận), LINH HOẠT điểm win-rate thấp (hay bị từ
    chối → nhượng đổi lấy điểm khác). Sắp theo (rate, số vụ) giảm dần; chỉ clause có ≥1 mẫu. Rỗng → "" (vòng
    đầu chưa có dữ liệu → không thêm gì). THUẦN (test offline)."""
    items = sorted(((c, s.get("rate", 0.0), s.get("total", 0))
                    for c, s in (win_rates or {}).items() if isinstance(s, dict) and s.get("total")),
                   key=lambda x: (x[1], x[2]), reverse=True)[:limit]
    if not items:
        return ""
    body = "; ".join(f"'{c}' đạt {int(r * 100)}% ({n} vụ)" for c, r, n in items)
    return ("WIN-RATE LỊCH SỬ (kết quả đàm phán THẬT của ta — ưu tiên GIỮ điểm đạt cao, LINH HOẠT nhượng "
            f"điểm đạt thấp): {body}")


def format_memory_context(episodes: list, limit: int = 5) -> str:
    """Tóm tắt TÌNH TIẾT bộ nhớ theo-đối-tác (deal/vòng trước) → context THAM KHẢO cho vòng đàm phán.
    Khác win-rate (số tổng hợp): đây là tình tiết CỤ THỂ ('điều khoản X: chiến thuật Y → kết quả Z'). Rỗng
    → "" (không thêm gì). THUẦN (test offline). Định vị THAM KHẢO, KHÔNG phải căn cứ pháp lý (tránh coi là luật)."""
    eps = [e for e in (episodes or [])][:limit]
    if not eps:
        return ""
    body = "; ".join(f"'{getattr(e, 'clause', '')}': {getattr(e, 'content', '')}".strip(" ':")
                     for e in eps if getattr(e, "content", ""))
    if not body:
        return ""
    return ("BỘ NHỚ ĐỐI TÁC (tình tiết deal/vòng TRƯỚC của ta — THAM KHẢO để nhất quán, KHÔNG phải luật): "
            f"{body}")


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
                    "next_moves": _move_list(d.get("next_moves")),
                    "red_line_blocked": bool(d.get("red_line_blocked", False)),
                    "status": status}
        except (json.JSONDecodeError, AttributeError):
            pass
    return {"assessment": text[:800], "strategy": "", "reply_vi": "", "reply_en": "",
            "newly_secured": [], "newly_conceded": [], "still_open": [], "next_moves": [],
            "red_line_blocked": False, "status": "continue"}


def _move_list(v) -> list[dict]:
    """Ép next_moves về list[{offer,in_return_for,why}]. LLM có thể trả str đơn → coi là offer."""
    if not isinstance(v, list):
        return []
    out = []
    for m in v:
        if isinstance(m, dict):
            out.append({"offer": str(m.get("offer", "")).strip(),
                        "in_return_for": str(m.get("in_return_for", "")).strip(),
                        "why": str(m.get("why", "")).strip()})
        elif isinstance(m, str) and m.strip():
            out.append({"offer": m.strip(), "in_return_for": "", "why": ""})
    return [m for m in out if m["offer"]]


@dataclass
class NegotiationState:
    """Sổ nhượng-bộ mang qua các vòng — bộ nhớ CÓ CẤU TRÚC của thế trận (chống quên do free-text cắt cụt)."""
    red_lines: list[str] = field(default_factory=list)   # điểm must-fix KHÔNG được nhượng (từ /analyze)
    secured: list[str] = field(default_factory=list)     # đối tác ĐÃ đồng ý → đừng đàm phán lại
    conceded: list[str] = field(default_factory=list)    # ta ĐÃ nhượng → đừng nhượng thêm/lặp
    open_items: list[str] = field(default_factory=list)  # còn tranh chấp


def state_to_json(state: NegotiationState) -> str:
    """NegotiationState → JSON string (persist trong conv/store dưới dạng chuỗi, không cần cột nested)."""
    return json.dumps({"red_lines": state.red_lines, "secured": state.secured,
                       "conceded": state.conceded, "open_items": state.open_items}, ensure_ascii=False)


def state_from_json(s: str) -> NegotiationState:
    """JSON string → NegotiationState. Rỗng/hỏng → state trống (an toàn, không vỡ luồng chat)."""
    if not s:
        return NegotiationState()
    try:
        d = json.loads(s)
        return NegotiationState(red_lines=_str_list(d.get("red_lines")), secured=_str_list(d.get("secured")),
                                conceded=_str_list(d.get("conceded")), open_items=_str_list(d.get("open_items")))
    except (json.JSONDecodeError, AttributeError, TypeError):
        return NegotiationState()


@dataclass
class NegotiationRound:
    assessment: str            # đối tác nhượng/giữ/phản-đề gì
    strategy: str              # chiến lược vòng tới
    reply_vi: str              # câu trả lời gửi đối tác (tiếng Việt)
    reply_en: str              # câu trả lời gửi đối tác (tiếng Anh — sẵn gửi)
    status: str = "continue"   # continue | close | walk_away
    state: NegotiationState = field(default_factory=NegotiationState)  # sổ nhượng-bộ ĐÃ cập nhật
    next_moves: list[dict] = field(default_factory=list)  # thang nhượng-bộ: [{offer,in_return_for,why,near_red_line}]
    walk_away_recommended: bool = False   # guardrail red-line: red-line bị chặn + có BATNA
    grounded: bool = True      # False = soạn offline/khung, cần người hoàn thiện


def negotiate_round(reasoner: LLMPort, *, deal_context: str, partner_message: str,
                    position: NegotiationPosition | None = None,
                    state: NegotiationState | None = None, tactics_context: str = "",
                    memory_context: str = "", lang: str = "vi") -> NegotiationRound:
    """Một VÒNG đàm phán: bối cảnh deal + SỔ nhượng-bộ + WIN-RATE lịch sử + tin đối tác → đánh giá + chiến
    lược + câu trả lời + status + sổ nhượng-bộ ĐÃ cập nhật. `state` mang qua các vòng (agent nhớ đã nhượng/
    chốt gì); `tactics_context` = win-rate lịch sử (moat flywheel) → agent ưu tiên nước đi từng thành công.
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
        + (f"{tactics_context[:1000]}\n\n" if tactics_context else "")
        + (f"{memory_context[:1000]}\n\n" if memory_context else "")
        + f"ĐỐI TÁC VỪA PHẢN HỒI:\n{partner_message[:2000]}\n\n"
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
    moves = screen_moves(parsed["next_moves"], new_state.red_lines)    # bảo vệ tất định: gắn cờ nước-đi đụng red-line
    return NegotiationRound(assessment=parsed["assessment"], strategy=strategy,
                            reply_vi=parsed["reply_vi"], reply_en=parsed["reply_en"],
                            status=status, state=new_state, next_moves=moves,
                            walk_away_recommended=walk, grounded=True)
