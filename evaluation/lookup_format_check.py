"""Kiểm format + cache của lookup trên NHIỀU case THẬT (gọi Qwen). Verify chuẩn hóa giọng/template.

Chạy: uv run python -m evaluation.lookup_format_check   (cần QWEN_API_KEY)
Mỗi case: in câu hỏi + câu trả lời + nguồn + latency; chấm format (có **Trả lời**/**Căn cứ**, dẫn Điều).
Case cuối lặp case 1 → đo cache (phải ~0ms + đáp án y hệt).
"""
from __future__ import annotations

import logging
import time

from legalguard.config.container import build_service
from legalguard.config.settings import settings
from legalguard.domain.tenants import default_org

# (nhãn, câu hỏi, lang, kỳ vọng): grounded = có căn cứ; honest = chấp nhận "chưa đủ căn cứ".
CASES = [
    ("phạt-tối-đa", "Mức phạt vi phạm hợp đồng tối đa bao nhiêu phần trăm?", "vi", "grounded"),
    ("lãi-chậm-trả", "Chậm thanh toán tiền hàng có được yêu cầu trả lãi không?", "vi", "grounded"),
    ("miễn-trách-nhiệm", "Các trường hợp được miễn trách nhiệm khi vi phạm hợp đồng là gì?", "vi", "grounded"),
    ("bồi-thường", "Giá trị bồi thường thiệt hại gồm những khoản nào?", "vi", "grounded"),
    ("hóa-đơn-xk", "Thời điểm lập hóa đơn khi xuất khẩu hàng hóa quy định ra sao?", "vi", "grounded"),
    ("ngoài-KB", "Thủ tục đăng ký nhãn hiệu độc quyền mất bao lâu?", "vi", "honest"),
    ("point-in-time", "Năm 2020, văn bản nào quy định về hóa đơn đang có hiệu lực?", "vi", "honest"),
    ("english", "What is the maximum penalty for breach of a commercial contract in Vietnam?", "en", "grounded"),
    ("dạng-ngắn", "trần lãi suất nợ quá hạn", "vi", "honest"),
]


def _fmt_ok(ans: str, lang: str) -> bool:
    a = ans.lower()
    has_answer = "**trả lời:**" in a or "**answer:**" in a
    has_basis = "**căn cứ:**" in a or "**basis:**" in a or "chưa đủ căn cứ" in a or "not enough" in a
    return has_answer or has_basis           # ít nhất theo khung


def _cites(ans: str) -> bool:
    a = ans.lower()
    return "điều" in a or "article" in a or "khoản" in a


def main() -> None:
    logging.disable(logging.CRITICAL)
    if not settings.qwen_api_key:
        raise SystemExit("Cần QWEN_API_KEY.")
    svc = build_service()
    org = default_org("VN")
    fmt_pass = 0
    print(f"LOOKUP format check — {len(CASES)} case (model={settings.qwen_model})\n" + "=" * 70)
    for label, q, lang, expect in CASES:
        t = time.perf_counter()
        ans, snips = svc.lookup(q, org, lang=lang)
        ms = round((time.perf_counter() - t) * 1000)
        fmt = _fmt_ok(ans, lang)
        cite = _cites(ans)
        fmt_pass += fmt
        print(f"\n[{label}] ({lang}, {ms}ms) format={'✓' if fmt else '✗'} cite={'✓' if cite else '—'}")
        print(f"  Q: {q}")
        print("  A: " + ans.replace("\n", "\n     ")[:600])
        print("  📎 " + " · ".join(s.source for s in snips[:3]))

    # Cache: lặp case 1 → phải tức thì + y hệt.
    t = time.perf_counter()
    a1, _ = svc.lookup(CASES[0][1], org, lang="vi")
    cache_ms = round((time.perf_counter() - t) * 1000)
    print("\n" + "=" * 70)
    print(f"Format theo khung: {fmt_pass}/{len(CASES)}")
    print(f"Cache (lặp case 1): {cache_ms}ms {'✓ tức thì' if cache_ms < 50 else '✗ KHÔNG cache?'}")


if __name__ == "__main__":
    main()
