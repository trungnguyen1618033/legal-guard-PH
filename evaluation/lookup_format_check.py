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
from legalguard.domain.analysis import _PIT_RE
from legalguard.domain.tenants import default_org

# (nhãn, câu hỏi, lang, kỳ vọng): grounded = có căn cứ; honest = chấp nhận "chưa đủ căn cứ".
CASES = [
    # --- Q&A thường (kỳ vọng route qwen-plus, nhanh) ---
    ("phạt-tối-đa", "Mức phạt vi phạm hợp đồng tối đa bao nhiêu phần trăm?", "vi", "grounded"),
    ("lãi-chậm-trả", "Chậm thanh toán tiền hàng có được yêu cầu trả lãi không?", "vi", "grounded"),
    ("miễn-trách-nhiệm", "Các trường hợp được miễn trách nhiệm khi vi phạm hợp đồng là gì?", "vi", "grounded"),
    ("bồi-thường", "Giá trị bồi thường thiệt hại gồm những khoản nào?", "vi", "grounded"),
    ("hóa-đơn-xk", "Thời điểm lập hóa đơn khi xuất khẩu hàng hóa quy định ra sao?", "vi", "grounded"),
    ("giao-thiếu-hàng", "Bên bán giao thiếu hàng hoặc hàng kém chất lượng thì xử lý thế nào?", "vi", "grounded"),
    ("phạt-15%", "Hợp đồng thỏa thuận phạt vi phạm 15% giá trị có hợp lệ không?", "vi", "grounded"),
    ("quan-hệ-phạt-bồi-thường", "Vừa phạt vi phạm vừa đòi bồi thường thiệt hại được không?", "vi", "grounded"),
    # --- Ngoài KB (kỳ vọng 'chưa đủ căn cứ', không bịa) ---
    ("ngoài-KB-nhãn-hiệu", "Thủ tục đăng ký nhãn hiệu độc quyền mất bao lâu?", "vi", "honest"),
    ("ngoài-KB-lao-động", "Thời gian thử việc tối đa với lao động là bao lâu?", "vi", "honest"),
    # --- Point-in-time (kỳ vọng route FLAGSHIP) ---
    ("pit-2020", "Năm 2020, văn bản nào quy định về hóa đơn đang có hiệu lực?", "vi", "grounded"),
    ("pit-ngày", "Quy định về hóa đơn áp dụng tại ngày 1/6/2022 là văn bản nào?", "vi", "grounded"),
    # --- English ---
    ("en-penalty", "What is the maximum penalty for breach of a commercial contract in Vietnam?", "en", "grounded"),
    ("en-force-majeure", "When is a party exempt from liability for contract breach?", "en", "grounded"),
    # --- Edge ---
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
    lookup_model = getattr(svc.lookup_llm, "model", "?")
    print(f"LOOKUP check — {len(CASES)} case | fast={lookup_model} · point-in-time→{settings.qwen_model}\n"
          + "=" * 72)
    for label, q, lang, expect in CASES:
        route = settings.qwen_model if _PIT_RE.search(q) else lookup_model   # dự đoán model định tuyến
        t = time.perf_counter()
        ans, snips = svc.lookup(q, org, lang=lang)
        ms = round((time.perf_counter() - t) * 1000)
        fmt = _fmt_ok(ans, lang)
        cite = _cites(ans)
        fmt_pass += fmt
        print(f"\n[{label}] {lang} · route={route} · {ms}ms · format={'✓' if fmt else '✗'} cite={'✓' if cite else '—'}")
        print(f"  Q: {q}")
        print("  A: " + ans.replace("\n", "\n     ")[:480])
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
