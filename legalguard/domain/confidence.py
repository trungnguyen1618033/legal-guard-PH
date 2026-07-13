"""Độ tin cậy câu trả lời — THUẦN, từ tín hiệu ĐÃ TÍNH (NLI + độ tập trung evidence). KHÔNG thêm LLM call.

Giúp user biết khi nào TIN, khi nào CẦN LUẬT SƯ đối chiếu (đòn bẩy 'đáng tin' của sản phẩm). Dùng chung
mọi kênh (lookup/Slack/web/MCP) qua AnalysisService — 1 nguồn tính, không lặp theo kênh.
"""
from __future__ import annotations


def answer_confidence(nli_supports: bool | None, n_kept: int) -> str:
    """'high' | 'medium' | 'low' từ: NLI (nguồn có hậu thuẫn câu trả lời không) + n_kept (số đoạn evidence
    TẬP TRUNG qua coverage-gate). low = NLI phủ định; high = không phủ định + evidence tập trung (≥3);
    còn lại medium. Bảo thủ: nghi ngờ → medium (không thổi 'Cao')."""
    if nli_supports is False:
        return "low"
    if n_kept >= 3:
        return "high"
    return "medium"


_LINE = {
    "vi": {
        "high": "Độ tin cậy: Cao — nguồn dẫn hậu thuẫn, căn cứ tập trung.",
        "medium": "Độ tin cậy: Trung bình — nên đối chiếu văn bản gốc trước khi áp dụng.",
        "low": "Độ tin cậy: Thấp — câu trả lời có thể chưa được nguồn dẫn hậu thuẫn đầy đủ; "
               "đề nghị luật sư đối chiếu bản gốc trước khi áp dụng.",
    },
    "en": {
        "high": "Confidence: High — supported by cited sources, focused basis.",
        "medium": "Confidence: Medium — verify against the original text before relying on it.",
        "low": "Confidence: Low — this answer may not be fully supported by the cited sources; "
               "please have a lawyer verify against the original text before relying on it.",
    },
}


def confidence_line(level: str, lang: str = "vi") -> str:
    """Dòng độ tin cậy KÊNH-AGNOSTIC (text) — Slack/web/`/ask` dùng chung."""
    return _LINE.get(lang if lang in _LINE else "vi", _LINE["vi"]).get(level, _LINE["vi"]["medium"])


# Tiền tố ổn định của MỌI dòng độ-tin-cậy (mọi mức, cả 2 ngôn ngữ) → dùng để nhận diện & bỏ khi nối lại.
_CONF_PREFIXES = ("Độ tin cậy:", "Confidence:")


def append_confidence(text: str, level: str, lang: str = "vi") -> str:
    """Nối dòng độ tin cậy đúng MỘT lần (idempotent): bỏ MỌI dòng độ-tin-cậy đã có sẵn trong `text`
    (mọi mức/ngôn ngữ — vd LLM lỡ sinh, hoặc câu trả lời dẫn lại) rồi mới nối → chống lặp dòng 2 lần."""
    kept = [ln for ln in (text or "").splitlines() if not ln.strip().startswith(_CONF_PREFIXES)]
    return "\n".join(kept).rstrip() + "\n\n" + confidence_line(level, lang)
