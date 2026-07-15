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


def _live_accuracy() -> dict | None:
    """Đọc số ĐO THẬT từ accuracy_eval (nếu đã chạy) → /trust hiện số sống, không phải snapshot tay."""
    import json
    from pathlib import Path
    p = Path("evaluation/accuracy_report.json")
    if not p.exists():
        return None
    try:
        r = json.loads(p.read_text(encoding="utf-8"))
        rep = r.get("repeat", 1)
        # Ghi chú BỘ-ĐỀ: 100% = 0 lỗi TRÊN bộ golden này (không phải 'hoàn hảo mãi mãi'). Minh bạch cỡ mẫu
        # + majority-vote nhiều lần (chống nhiễu LLM hosted) → số trung thực, không đọc thành tuyệt đối.
        flaky = r.get("flaky_cases", 0)
        flaky_note = (f" {flaky} ca dao động giữa các lần (biên nhiễu LLM hosted, đa số vẫn đạt)."
                      if flaky else "")
        note = (f"{r['passed']}/{r['total']} ca golden (dẫn đúng Điều/Khoản + dữ kiện + biết từ chối khi "
                f"ngoài KB), majority-vote {rep} lần/ca — accuracy_eval. Số trên BỘ ĐỀ này, không suy ra "
                f"mọi câu hỏi.{flaky_note}")
        return {"name": "Độ chính xác câu trả lời (golden set)",
                "value": f"{r['answer_accuracy']:.0%} ({r['passed']}/{r['total']})",
                "note": note}
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def _live_fast_review() -> dict | None:
    """Đọc số ĐO THẬT rà-soát-nhanh (fast_bench_live --holdout, lawyer-verified) → công bố chất lượng RÀ SOÁT
    (khác accuracy tra cứu). TRUNG THỰC: nêu cỡ mẫu nhỏ + held-out (chống học tủ) + cần luật sư duyệt."""
    import json
    from pathlib import Path
    p = Path("scripts/fast_bench_report_shipped.json")
    if not p.exists():
        return None
    try:
        r = json.loads(p.read_text(encoding="utf-8"))
        f = r["fast"]
        det = f["detection"]
        f1, ir = det["f1"], f["illegal_recall_pct"]
        fa, med = f["false_alarm_pct_on_clean"], f["latency_s"]["median"]
        note = (f"Chế độ rà soát NHANH: F1 {f1} (precision {det['precision']} · recall {det['recall']}), "
                f"bắt điều khoản TRÁI LUẬT {ir:.0f}%, báo dư trên điều-khoản-vô-hại {fa:.0f}%, ~{med:.0f}s/HĐ. "
                f"Trên {r['cases']} HĐ HELD-OUT luật-sư-duyệt ({f['runs']} lượt; loại HĐ dùng làm ví dụ mẫu → "
                f"chống học tủ). Bộ nhỏ, không suy ra mọi HĐ; luôn cần luật sư duyệt.")
        return {"name": "Chất lượng rà soát nhanh (bộ luật-sư-duyệt)",
                "value": f"F1 {f1} · trái luật {ir:.0f}%", "note": note}
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def trust_report() -> dict:
    """Báo cáo độ tin cậy có cấu trúc: phương pháp đo + số đo + disclaimer. Dùng cho /trust + Slack.
    Nếu đã chạy `accuracy_eval` → chèn số ĐO THẬT lên đầu (sống), không thì dùng số nền."""
    metrics = [{"name": n, "value": val, "note": note} for n, val, note in _METRICS]
    for live in (_live_fast_review(), _live_accuracy()):   # số sống lên đầu (accuracy trên cùng)
        if live:
            metrics.insert(0, live)
    return {
        "methodology": [{"layer": k, "desc": v} for k, v in _METHODOLOGY],
        "metrics": metrics,
        "disclaimer": _DISCLAIMER,
    }


def format_trust_text(report: dict | None = None) -> str:
    """Tóm tắt độ tin cậy dạng văn bản (Slack/markdown). Tái dùng cùng số liệu với trang /trust."""
    r = report or trust_report()
    lines = ["*Độ tin cậy Legal Guard* — cách chúng tôi đảm bảo KHÔNG bịa:"]
    lines += [f"• *{m['layer']}*: {m['desc']}" for m in r["methodology"]]
    lines += ["", "*Số đo (golden set nội bộ):*"]
    lines += [f"• {m['name']}: *{m['value']}* — {m['note']}" for m in r["metrics"]]
    lines += ["", f"_{r['disclaimer']}_"]
    return "\n".join(lines)
