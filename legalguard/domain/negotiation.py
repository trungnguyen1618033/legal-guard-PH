"""Đàm phán đa phiên — agent đọc PHẢN HỒI của đối tác qua từng vòng, cập nhật chiến lược.

Khác `analyze` (rà soát 1 lần) và `counter_clause` (soạn 1 điều khoản): đây là VÒNG ĐÀM PHÁN —
nhận bối cảnh deal (từ phân tích trước) + tin nhắn đối tác vừa gửi → đánh giá đối tác nhượng/giữ gì,
cập nhật chiến lược vòng tới, soạn câu trả lời, và khuyến nghị tiếp tục / chốt / rút (walk-away).

Đây là lõi "Autopilot Agent": agent dẫn dắt đàm phán nhiều bước, không chỉ trả lời 1 lần.
`_parse_round` thuần (test offline). `negotiate_round` rẽ nhánh theo `reasoner.available`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from legalguard.domain.models import NegotiationPosition
from legalguard.domain.ports import LLMPort

_STATUSES = ("continue", "close", "walk_away")

_SYSTEM = (
    "Bạn là luật sư đàm phán hợp đồng thương mại quốc tế, đại diện cho BÊN ĐƯỢC BẢO VỆ. Mỗi vòng, bạn nhận "
    "bối cảnh deal + tin nhắn mới nhất của đối tác, rồi: (1) đánh giá đối tác CHẤP NHẬN/TỪ CHỐI/PHẢN-ĐỀ gì so "
    "với yêu cầu của ta; (2) cập nhật chiến lược vòng tới (còn PHẢI GIỮ gì, NHƯỢNG thêm gì); (3) soạn câu trả "
    "lời gửi đối tác song ngữ, chuyên nghiệp, bám vị thế; (4) khuyến nghị status. Bám căn cứ pháp lý nếu có, "
    "KHÔNG bịa số hiệu điều luật. status: 'continue' (còn đàm phán) | 'close' (điều kiện đã đủ tốt, nên chốt) "
    "| 'walk_away' (đối tác không nhượng điểm sống còn + ta có BATNA → nên rút). "
    'Trả về DUY NHẤT một khối JSON: {"assessment":"<đánh giá phản hồi đối tác>", '
    '"strategy":"<chiến lược vòng tới: giữ/nhượng/walk-away>", "reply_vi":"<câu trả lời tiếng Việt>", '
    '"reply_en":"<English reply to partner>", "status":"continue|close|walk_away"}.'
)

_LEVERAGE_VI = {"strong": "mạnh", "balanced": "cân bằng", "weak": "yếu (ưu tiên giữ deal, không đòi quá)"}


def _parse_round(raw: str) -> dict:
    """Rút {assessment, strategy, reply_vi, reply_en, status} từ phản hồi LLM. Lỗi → assessment=raw rút gọn."""
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
                    "reply_en": str(d.get("reply_en", "")).strip(), "status": status}
        except (json.JSONDecodeError, AttributeError):
            pass
    return {"assessment": text[:800], "strategy": "", "reply_vi": "", "reply_en": "", "status": "continue"}


@dataclass
class NegotiationRound:
    assessment: str            # đối tác nhượng/giữ/phản-đề gì
    strategy: str              # chiến lược vòng tới
    reply_vi: str              # câu trả lời gửi đối tác (tiếng Việt)
    reply_en: str              # câu trả lời gửi đối tác (tiếng Anh — sẵn gửi)
    status: str = "continue"   # continue | close | walk_away
    grounded: bool = True      # False = soạn offline/khung, cần người hoàn thiện


def negotiate_round(reasoner: LLMPort, *, deal_context: str, partner_message: str,
                    position: NegotiationPosition | None = None, lang: str = "vi") -> NegotiationRound:
    """Một VÒNG đàm phán: bối cảnh deal + tin đối tác → đánh giá + chiến lược + câu trả lời + status.
    Offline (chưa có key) → khung an toàn (grounded=False), KHÔNG bịa."""
    pos = position or NegotiationPosition()
    protected = pos.protected_party.strip() or "doanh nghiệp Việt Nam"
    if not reasoner.available:
        return NegotiationRound(
            assessment="[CẦN NGƯỜI HOÀN THIỆN] Chưa cấu hình AI — chưa đánh giá được phản hồi đối tác.",
            strategy=f"Giữ các điểm must-fix đã nêu; cân nhắc vị thế {pos.leverage}.",
            reply_vi="", reply_en="", status="continue", grounded=False)
    prompt = (
        f"BÊN ĐƯỢC BẢO VỆ: {protected}\n"
        f"VỊ THẾ: lợi thế={_LEVERAGE_VI.get(pos.leverage, pos.leverage)}, độ gấp={pos.urgency}, "
        f"quan hệ={pos.relationship}, có BATNA={pos.alternatives}\n\n"
        f"BỐI CẢNH DEAL (từ phân tích/các vòng trước):\n{deal_context[:4000]}\n\n"
        f"ĐỐI TÁC VỪA PHẢN HỒI:\n{partner_message[:2000]}\n\n"
        f"Đánh giá phản hồi, cập nhật chiến lược vòng tới, soạn câu trả lời "
        f"({'tiếng Việt + tiếng Anh' if lang == 'vi' else 'English + Vietnamese'}), và đề xuất status."
    )
    parsed = _parse_round(reasoner.complete(prompt, system=_SYSTEM))
    return NegotiationRound(assessment=parsed["assessment"], strategy=parsed["strategy"],
                            reply_vi=parsed["reply_vi"], reply_en=parsed["reply_en"],
                            status=parsed["status"], grounded=True)
