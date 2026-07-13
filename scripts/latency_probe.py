#!/usr/bin/env python3
"""Đo LATENCY THẬT của analyze() từng bước — chạy trong môi trường có QWEN_API_KEY.

In bảng: total ms · agent-loop ms · post-agent ms · #cửa sổ · #tool-call · #rủi ro · route
cho HĐ NGẮN / VỪA / DÀI → thấy rõ nút thắt (agent loop) + so đường fast vs full.

Chạy:  QWEN_API_KEY=... uv run python -m scripts.latency_probe
       uv run python -m scripts.latency_probe --only short     # chỉ 1 cỡ (tiết kiệm quota)

LƯU Ý: gọi LLM THẬT (tốn quota + ~vài phút cho HĐ dài). Dùng DB sqlite tạm; nếu KB chưa persist
embeddings thì boot sẽ embed KB (một lần, tính RIÊNG, không nằm trong số analyze bên dưới).
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import tempfile
import time

# DB sqlite tạm để không phụ thuộc Postgres; GIỮ nguyên QWEN key (đo LLM thật).
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/probe.db")

from legalguard.config.container import build_service  # noqa: E402
from legalguard.domain.models import NegotiationPosition  # noqa: E402
from legalguard.domain.tenants import default_org  # noqa: E402

# HĐ mẫu 3 cỡ: ngắn (route fast), vừa (1 cửa sổ full), dài (nhiều cửa sổ).
_SHORT = ("Điều 5. Bên B chịu phạt 15% giá trị hợp đồng nếu chậm bàn giao. "
          "Điều 8. Thanh toán trong vòng 90 ngày kể từ ngày nhận hàng.")           # ~130 ký tự → fast
_MED = _SHORT + " " + ("Điều 9. Mọi tranh chấp giải quyết bằng trọng tài tại Bắc Kinh theo quy tắc "
                       "CIETAC. Điều 12. Bên A được đơn phương chấm dứt hợp đồng bất kỳ lúc nào mà "
                       "không cần lý do và không chịu bồi thường. ") * 6            # ~1.8k → full, 1 cửa sổ
_LONG = _MED + (" Điều 20. Bên B bảo đảm hàng hóa đúng chất lượng trong 24 tháng. "
                "Điều 21. Phí phạt chậm thanh toán 0,5%/ngày. ") * 40               # >6k → nhiều cửa sổ


class _Capture(logging.Handler):
    """Bắt dòng log 'agent loop (N window) Xms' để tách agent vs post-agent."""
    def __init__(self) -> None:
        super().__init__()
        self.agent_ms = 0

    def emit(self, record: logging.LogRecord) -> None:
        m = re.search(r"agent loop \(\d+ window\) (\d+)ms", record.getMessage())
        if m:
            self.agent_ms = int(m.group(1))


def _run(svc, org, name: str, text: str) -> None:
    cap = _Capture()
    lg = logging.getLogger("legalguard.domain.analysis")
    lg.setLevel(logging.INFO)
    lg.addHandler(cap)
    pos = NegotiationPosition(protected_party="Bên B (doanh nghiệp Việt)")
    t0 = time.monotonic()
    res = svc.analyze(text, org, lang="vi", position=pos)
    total = round((time.monotonic() - t0) * 1000)
    lg.removeHandler(cap)
    route = next((n for n in res.notes if "Route" in n), "?")
    n_win = route.count("đoạn") and re.search(r"chia (\d+) đoạn", route)
    n_win = int(n_win.group(1)) if n_win else 1
    post = max(0, total - cap.agent_ms)
    print(f"{name:6} | total {total/1000:6.1f}s | agent {cap.agent_ms/1000:6.1f}s "
          f"({100*cap.agent_ms/max(total,1):4.0f}%) | post {post/1000:5.1f}s | "
          f"cửa sổ {n_win} | tool-call {len(res.trace):3} | rủi ro {len(res.risks):2} | "
          f"{route.replace('🧭 ', '')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["short", "med", "long"], help="chỉ đo 1 cỡ (tiết kiệm quota)")
    args = ap.parse_args()
    svc = build_service()
    if not svc.reasoner.available:
        raise SystemExit("Thiếu QWEN_API_KEY — không đo được LLM thật (stub sẽ ~0ms, vô nghĩa).")
    org = default_org("VN")
    print(f"{'cỡ':6} | {'tổng':>10} | {'agent (nút thắt)':>22} | {'post':>10} | "
          "cửa sổ | tool-call | rủi ro | route")
    print("-" * 110)
    cases = {"short": _SHORT, "med": _MED, "long": _LONG}
    for name in ([args.only] if args.only else ["short", "med", "long"]):
        try:
            _run(svc, org, name, cases[name])
        except Exception as exc:  # noqa: BLE001 — 1 cỡ lỗi không chặn cỡ khác
            print(f"{name:6} | LỖI: {exc}")
    print("\n→ agent% cao = nút thắt ở vòng agent (nhiều call flagship tuần tự). "
          "Fast-path gộp về 1 call sẽ cắt phần này.")


if __name__ == "__main__":
    main()
