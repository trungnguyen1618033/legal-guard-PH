"""Công bố độ tin cậy — NGUỒN SỰ THẬT chung cho trang web /trust + câu trả lời Slack.

Số đo lấy từ eval harness (`evaluation/run_eval.py`, `legal_eval.py`) — đo trên golden set nội bộ (đang
mở rộng + luật sư duyệt). TRUNG THỰC: nêu rõ golden set còn nhỏ, kèm disclaimer 'AI hỗ trợ, không thay
tư vấn'. `trust_report()` thuần (test offline); cập nhật số khi chạy lại eval.
"""
from __future__ import annotations

# Cập nhật khi chạy lại eval (run_eval / legal_eval). Mỗi mục: (tên, giá trị, ghi chú/cách đo).
_METHODOLOGY = [
    ("Grounding + trích dẫn", "Mọi rủi ro gắn nguồn KB + dẫn ĐÚNG Điều/Khoản; không có căn cứ khớp → để trống"),
    ("Verify 2 lớp", "Đối chiếu trích dẫn với văn bản gốc + LLM-judge + NLI entailment (nguồn CÓ hậu thuẫn claim)"),
    ("Phát hiện TRÁI LUẬT (NLI-mâu-thuẫn)", "Chỉ gắn 'trái luật' khi đối chiếu ĐÚNG điều luật + judge xác nhận mâu thuẫn; nghi ngờ → để 'bất lợi'"),
    ("Lọc hiệu lực", "Mặc định chỉ trả văn bản CÒN hiệu lực; point-in-time theo mốc thời gian câu hỏi"),
    ("Backend kiểm soát citation", "LLM diễn giải; nguồn/điều luật/hiệu lực do backend truy xuất — không để LLM tự bịa"),
]

_METRICS = [
    ("Groundedness (không bịa)", "1.0", "Mọi câu trả lời chỉ dùng căn cứ truy được — run_eval"),
    ("Retrieval F1 (hybrid)", "0.94", "Precision 0.89 · Recall 1.0 trên golden set — run_eval"),
    ("Kéo điều dẫn-chiếu-chéo (closure)", "+0.5 recall", "Tự kéo điều liên quan (vd Đ.300→Đ.294) — legal_eval"),
    ("Trả đúng luật CÒN hiệu lực", "0.75 → 1.0", "Bật lọc hiệu lực: loại VB hết hiệu lực lọt top — legal_eval (corpus thật)"),
]

_DISCLAIMER = ("Số đo trên GOLDEN SET NỘI BỘ đang mở rộng (cần luật sư đối chiếu/duyệt). "
               "Legal Guard là công cụ HỖ TRỢ — không thay thế tư vấn pháp lý chính thức; "
               "văn bản luật cần luật sư đối chiếu bản gốc trước khi sử dụng.")


def trust_report() -> dict:
    """Báo cáo độ tin cậy có cấu trúc: phương pháp đo + số đo + disclaimer. Dùng cho /trust + Slack."""
    return {
        "methodology": [{"layer": k, "desc": v} for k, v in _METHODOLOGY],
        "metrics": [{"name": n, "value": val, "note": note} for n, val, note in _METRICS],
        "disclaimer": _DISCLAIMER,
    }


def format_trust_text(report: dict | None = None) -> str:
    """Tóm tắt độ tin cậy dạng văn bản (Slack/markdown). Tái dùng cùng số liệu với trang /trust."""
    r = report or trust_report()
    lines = ["🔎 *Độ tin cậy Legal Guard* — cách chúng tôi đảm bảo KHÔNG bịa:"]
    lines += [f"• *{m['layer']}*: {m['desc']}" for m in r["methodology"]]
    lines += ["", "*Số đo (golden set nội bộ):*"]
    lines += [f"• {m['name']}: *{m['value']}* — {m['note']}" for m in r["metrics"]]
    lines += ["", f"_{r['disclaimer']}_"]
    return "\n".join(lines)
