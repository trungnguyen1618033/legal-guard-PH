#!/usr/bin/env python3
"""Smoke-test Slack THẬT — đăng reply mẫu vào 1 kênh Slack để SOI RENDERING (in đậm, giãn dòng, nút,
song ngữ VN–EN) đúng như bot sẽ trả. Cần SLACK_BOT_TOKEN (trong .env) + quyền `chat:write`.

An toàn: chỉ đăng vào kênh bạn chỉ định, mỗi tin gắn nhãn "[SMOKE TEST]". Mời bot vào kênh trước
(/invite @bot). KHÔNG chạy phân tích LLM — chỉ đăng blocks đã dựng sẵn để kiểm hình thức.

Chạy:
  uv run python -m scripts.slack_live --channel C0XXXXXXX            # đăng bộ mẫu
  uv run python -m scripts.slack_live --channel C0XXXXXXX --thread 1700000000.0001   # đăng vào 1 thread
  uv run python -m scripts.slack_live --channel C0XXXXXXX --only heartbeat           # chỉ test chat.update

Lấy channel ID: mở kênh trên Slack → Details → gần cuối có "Channel ID: C…".
"""
from __future__ import annotations

import argparse
import time

from legalguard.adapters.inbound.channels import (
    _analysis_blocks,
    _format_amend,
    _md_to_slack,
    _mrkdwn_blocks,
    _review_action_blocks,
)
from legalguard.adapters.outbound.chat_senders import SlackSender
from legalguard.config.settings import Settings
from legalguard.domain.models import AnalysisResult

_TAG = "*[SMOKE TEST]* "


def _sample_result() -> AnalysisResult:
    return AnalysisResult(
        tenant="VN", case_id="smoke-live-1",
        contract_type="Thỏa thuận sửa đổi Hợp đồng mua bán căn hộ",
        protected_party="ông Lin Hsuan",
        risks=[
            {"clause": "Điều 5 — Phạt vi phạm", "risk": "mức phạt 15% vượt trần luật định",
             "priority": "must_fix", "legal_status": "illegal", "violated_law": "Điều 301 Luật Thương mại",
             "evidence": "Bên B chịu phạt 15% giá trị hợp đồng nếu chậm bàn giao.",
             "counter_clause": {"vi": "Mức phạt tối đa 8% giá trị phần nghĩa vụ bị vi phạm.",
                                "en": "Penalty shall not exceed 8% of the breached obligation value.",
                                "rationale": "Điều 301 Luật Thương mại 2005 giới hạn phạt ở 8%.",
                                "grounded": True}},
            {"clause": "Điều 8 — Thanh toán", "risk": "thời hạn 90 ngày gây bất lợi dòng tiền",
             "priority": "negotiate"},
        ],
        fallbacks=[{"clause": "Điều 8 — Thanh toán", "suggestion": "rút thời hạn về 30–45 ngày"}],
        drafting_notes=[
            "Tại Điều 1.2 bản tiếng Anh, tên người thừa kế ghi nhầm \"LIN YUAN\"; đề xuất sửa thành: LIN HSUAN",
            "Tại phần địa chỉ ông LIN HSUAN, thiếu quốc gia; đề xuất sửa như sau:\n"
            "Tiếng Việt: Số 275 đường Tam Thố, ..., thành phố Đài Trung, Đài Loan\n"
            "Tiếng Anh: No. 275, Sancuo Street, ..., Taichung City, Taiwan",
        ],
        needs_human_review=True, review_reasons=[], summary="", trace=[],
        strategy="Giữ trần phạt 8% (must_fix); có thể nhượng thời hạn thanh toán để chốt.",
    )


def _post_analysis(s: SlackSender, ch: str, thread: str | None) -> None:
    res = _sample_result()
    blocks = _analysis_blocks(res, res.case_id) + _review_action_blocks("analysis", res.case_id)
    blocks[0]["text"]["text"] = _TAG + blocks[0]["text"]["text"]
    ts = s.send(ch, "[SMOKE] reply rà soát", thread, blocks)
    print(f"  ✔ Rà soát (nút Đồng ý sửa + Chốt/Sửa lại) → ts={ts}")


def _post_lookup(s: SlackSender, ch: str, thread: str | None) -> None:
    ans = (_TAG + "\n**Trả lời:** Mức phạt vi phạm hợp đồng thương mại tối đa 8% giá trị phần nghĩa vụ "
           "vi phạm.\n**Căn cứ:** Điều 301 Luật Thương mại 2005 — giới hạn mức phạt 8%.\n\n"
           "Độ tin cậy: Cao — nguồn dẫn hậu thuẫn, căn cứ tập trung.")
    ts = s.send(ch, "[SMOKE] tra cứu", thread, _mrkdwn_blocks(ans))
    print(f"  ✔ Tra cứu (in đậm '**Trả lời**' → *Trả lời*) → ts={ts}")


def _post_amend(s: SlackSender, ch: str, thread: str | None) -> None:
    res = _sample_result()
    cc = res.risks[0]["counter_clause"]
    text = _md_to_slack(_format_amend(res.risks[0]["clause"], res.risks[0]["evidence"], cc))
    ts = s.send(ch, "[SMOKE] điều khoản sửa", thread, _mrkdwn_blocks(_TAG + "\n" + text))
    print(f"  ✔ Điều khoản sửa (cũ → mới song ngữ) → ts={ts}")


def _post_heartbeat(s: SlackSender, ch: str, thread: str | None) -> None:
    ts = s.send(ch, _TAG + "Đã nhận hợp đồng. Hệ thống đang rà soát…", thread)
    print(f"  ✔ Gửi ack → ts={ts}. Đợi 1s rồi chat.update (heartbeat)…")
    time.sleep(1)
    s.update(ch, ts or "", _TAG + "Đang rà soát hợp đồng… đã phát hiện 3 rủi ro.")
    print("  ✔ Đã update ack (kiểm trên Slack: tin ack phải ĐỔI chữ, không phải tin mới).")


_ACTIONS = {"analysis": _post_analysis, "lookup": _post_lookup,
            "amend": _post_amend, "heartbeat": _post_heartbeat}


def main() -> None:
    ap = argparse.ArgumentParser(description="Đăng reply mẫu vào Slack thật để soi rendering.")
    ap.add_argument("--channel", required=True, help="Channel ID (C…) — mời bot vào kênh trước.")
    ap.add_argument("--thread", default=None, help="thread_ts (tùy chọn) để đăng vào 1 thread.")
    ap.add_argument("--only", choices=sorted(_ACTIONS), help="chỉ chạy 1 loại (mặc định: tất cả).")
    args = ap.parse_args()

    token = Settings().slack_bot_token
    if not token:
        raise SystemExit("Thiếu SLACK_BOT_TOKEN (đặt trong .env). Không thể đăng lên Slack.")
    sender = SlackSender(token)
    print(f"Đăng vào kênh {args.channel}"
          + (f" (thread {args.thread})" if args.thread else "") + " …\n")
    actions = [args.only] if args.only else ["analysis", "lookup", "amend", "heartbeat"]
    for name in actions:
        _ACTIONS[name](sender, args.channel, args.thread)
    print("\n✔ Xong. Mở Slack kiểm: (1) chữ IN ĐẬM đúng, (2) GIÃN DÒNG dễ đọc, "
          "(3) nút hiển thị, (4) song ngữ Tiếng Việt/Tiếng Anh tách dòng, (5) ack heartbeat ĐỔI tại chỗ.")
    print("Lưu ý: bấm nút ở đây sẽ gọi webhook interactions THẬT của server — chỉ bấm khi server đang chạy.")


if __name__ == "__main__":
    main()
