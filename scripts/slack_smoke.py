#!/usr/bin/env python3
"""Smoke-test Slack OFFLINE (không gọi Slack thật, không cần token).

Ba phần:
  A. XEM TRƯỚC FORMAT  — render reply mẫu (rà soát + tra cứu + điều khoản sửa) đúng bộ định dạng Slack
     (blocks), in ra terminal có tô ĐẬM để bạn soi văn phong/giãn dòng — KHÔNG cần LLM.
  B. ĐỊNH TUYẾN        — dựng app trong tiến trình + FakeSender, bắn sự kiện Slack ĐÃ KÝ (app_mention
     tra cứu, dán hợp đồng) → in ra thứ bot "gửi". Chế độ stub (không key) nên nội dung là [..._STUB]
     nhưng LUỒNG + việc build blocks được kiểm thật.
  C. NÚT BẤM           — bắn interaction đã ký (Đồng ý sửa / Chốt / Sửa lại / feedback) → in phản hồi.

Chạy:  uv run python -m scripts.slack_smoke
       (đặt QWEN_API_KEY trong .env nếu muốn phần B/C dùng LLM thật thay vì stub)
"""
from __future__ import annotations

import os
import tempfile

# CÔ LẬP offline: sqlite tạm + STUB LLM (blank key → không gọi mạng, không embed KB lúc boot → chạy nhanh,
# tất định) + tắt auth. Đặt TRƯỚC khi import legalguard (ghi đè .env prod). Nội dung phần B/C là [..._STUB]
# — mục tiêu là kiểm LUỒNG + FORMAT, không phải chất lượng LLM (dùng slack_live.py cho LLM thật).
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/smoke.db"
os.environ["API_KEYS"] = ""
os.environ["PERSIST_EMBEDDINGS"] = "0"
for _k in ("QWEN_API_KEY", "QWEN_FAST_MODEL_KEY", "QWEN_LOOKUP_MODEL_KEY", "GEMINI_API_KEY"):
    os.environ[_k] = ""

import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
import urllib.parse  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from legalguard.adapters.inbound.channels import (  # noqa: E402
    ChatHandler,
    _analysis_blocks,
    _format_amend,
    _md_to_slack,
    _review_action_blocks,
    build_channels_router,
    format_chat_reply,
)
from legalguard.adapters.outbound.conversation_store import InMemoryConversationStore  # noqa: E402
from legalguard.config.container import build_parser, build_service  # noqa: E402
from legalguard.domain.models import AnalysisResult  # noqa: E402

_SECRET = "smoke-signing-secret"
_BOLD, _DIM, _RST = "\033[1m", "\033[2m", "\033[0m"


# ---------- in Slack mrkdwn ra terminal (tô đậm *x* → đậm) ----------
def _render_mrkdwn(text: str) -> str:
    import re
    return re.sub(r"\*(.+?)\*", lambda m: f"{_BOLD}{m.group(1)}{_RST}", text)


def _print_blocks(blocks: list[dict]) -> None:
    for b in blocks:
        t = b.get("type")
        if t == "section":
            print(_render_mrkdwn(b["text"]["text"]))
            if acc := b.get("accessory"):
                print(f"      {_DIM}[ nút: {acc['text']['text']} ]{_RST}")
        elif t == "actions":
            btns = " ".join(f"[ {e['text']['text']} ]" for e in b["elements"])
            print(f"{_DIM}{btns}{_RST}")
        elif t == "context":
            print(f"{_DIM}{b['elements'][0]['text']}{_RST}")
        print()


def _sample_result() -> AnalysisResult:
    """HĐ song ngữ kiểu demo: 1 rủi ro TRÁI LUẬT có điều khoản mới + lỗi soạn thảo + khác biệt VN–EN."""
    return AnalysisResult(
        tenant="VN", case_id="smoke-case-1",
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
            "Tại Điều 1.2 bản tiếng Anh, tên người thừa kế ghi nhầm \"LIN YUAN\"; "
            "đề xuất sửa thành: LIN HSUAN",
            "Tại phần địa chỉ ông LIN HSUAN, thiếu quốc gia; đề xuất sửa như sau:\n"
            "Tiếng Việt: Số 275 đường Tam Thố, ..., thành phố Đài Trung, Đài Loan\n"
            "Tiếng Anh: No. 275, Sancuo Street, ..., Taichung City, Taiwan",
        ],
        needs_human_review=True, review_reasons=[], summary="", trace=[],
        strategy="Giữ trần phạt 8% (must_fix); có thể nhượng thời hạn thanh toán để chốt.",
    )


def part_a_format_preview() -> None:
    print(f"\n{_BOLD}══════ PHẦN A — XEM TRƯỚC FORMAT (Slack blocks, không LLM) ══════{_RST}\n")
    res = _sample_result()
    print(f"{_BOLD}--- Reply RÀ SOÁT (Slack blocks) ---{_RST}\n")
    _print_blocks(_analysis_blocks(res, res.case_id) + _review_action_blocks("analysis", res.case_id))

    print(f"{_BOLD}--- Reply RÀ SOÁT (text fallback / Zalo) ---{_RST}\n")
    print(_render_mrkdwn(format_chat_reply(res)))

    print(f"\n{_BOLD}--- Tin 'Đồng ý sửa' (điều khoản cũ → mới, song ngữ) ---{_RST}\n")
    cc = res.risks[0]["counter_clause"]
    print(_render_mrkdwn(_md_to_slack(_format_amend(res.risks[0]["clause"],
                                                    res.risks[0]["evidence"], cc))))

    print(f"\n{_BOLD}--- Reply TRA CỨU (mô phỏng định dạng '**Trả lời**' → Slack) ---{_RST}\n")
    lookup = ("**Trả lời:** Mức phạt vi phạm hợp đồng thương mại tối đa 8% giá trị phần nghĩa vụ vi phạm.\n"
              "**Căn cứ:** Điều 301 Luật Thương mại 2005 — giới hạn mức phạt 8%.\n\n"
              "Độ tin cậy: Cao — nguồn dẫn hậu thuẫn, căn cứ tập trung.")
    print(_render_mrkdwn(_md_to_slack(lookup)))


# ---------- Phần B/C: app trong tiến trình + FakeSender ----------
class _FakeSender:
    name = "slack"

    def __init__(self) -> None:
        self.sent: list[tuple] = []
        self.updated: list[tuple] = []

    @property
    def available(self) -> bool:
        return True

    def send(self, conv, text, thread_ts=None, blocks=None):
        self.sent.append((conv, text, blocks))
        return "1700000000.000100"      # ts giả → cho phép chat.update heartbeat

    def update(self, conv, ts, text, blocks=None):
        self.updated.append((ts, text))

    def download(self, url):
        return b""

    def fetch_thread(self, channel, thread_ts):
        return []

    def resolve_names(self, ids):
        return {}


def _client(sender: _FakeSender) -> TestClient:
    handler = ChatHandler(build_service(), build_parser(), InMemoryConversationStore(), "VN")
    app = FastAPI()
    app.include_router(build_channels_router(
        handler, slack_signing_secret=_SECRET, slack_sender=sender, mention_only=True))
    return TestClient(app)


def _sign(body: bytes) -> dict:
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(_SECRET.encode(), b"v0:" + ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig}


def _event(client: TestClient, event: dict, bot_uid: str = "UBOT") -> None:
    payload = {"authorizations": [{"user_id": bot_uid}], "event": event}
    body = json.dumps(payload).encode()
    r = client.post("/channels/slack/events", content=body, headers=_sign(body))
    print(f"{_DIM}HTTP {r.status_code} {r.json()}{_RST}")


def _interaction(client: TestClient, action_id: str, value: dict) -> dict:
    payload = {"type": "block_actions", "user": {"id": "UASKER"}, "channel": {"id": "C1"},
               "message": {"ts": "1700000000.000200"}, "container": {"thread_ts": "1700000000.000010"},
               "actions": [{"action_id": action_id, "value": json.dumps(value, ensure_ascii=False)}]}
    body = ("payload=" + urllib.parse.quote(json.dumps(payload))).encode()
    r = client.post("/channels/slack/interactions", content=body,
                    headers={**_sign(body), "Content-Type": "application/x-www-form-urlencoded"})
    return r.json()


def part_b_routing() -> None:
    print(f"\n{_BOLD}══════ PHẦN B — ĐỊNH TUYẾN (app + FakeSender, sự kiện đã ký) ══════{_RST}\n")
    sender = _FakeSender()
    client = _client(sender)

    print(f"{_BOLD}[1] app_mention — câu TRA CỨU{_RST}")
    _event(client, {"type": "app_mention", "channel": "C1", "user": "UASKER",
                    "text": "<@UBOT> mức phạt vi phạm hợp đồng thương mại tối đa bao nhiêu?",
                    "ts": "1700000000.000001"})

    print(f"\n{_BOLD}[2] tin DÁN hợp đồng (rà soát){_RST}")
    _event(client, {"type": "message", "channel": "C1", "user": "UASKER",
                    "text": "<@UBOT> rà soát giúp: Bên B chịu phạt 15% giá trị hợp đồng nếu chậm; "
                            "tranh chấp giải quyết bằng trọng tài tại Bắc Kinh.",
                    "ts": "1700000000.000002"})

    print(f"\n{_BOLD}[3] tin KHÔNG mention (phải IM LẶNG){_RST}")
    _event(client, {"type": "message", "channel": "C1", "user": "UASKER",
                    "text": "anh em ăn trưa chưa", "ts": "1700000000.000003"})

    print(f"\n{_BOLD}→ Bot đã GỬI {len(sender.sent)} tin:{_RST}")
    for conv, text, blocks in sender.sent:
        tag = f"{len(blocks)} blocks" if blocks else "text"
        print(f"  {_DIM}[{conv} · {tag}]{_RST} {text[:120]}")


def part_c_interactions() -> None:
    print(f"\n{_BOLD}══════ PHẦN C — NÚT BẤM (interaction đã ký) ══════{_RST}\n")
    sender = _FakeSender()
    client = _client(sender)
    val = {"c": "smoke-case-1", "i": 0, "r": "smoke-case-1"}
    for aid, v in [("amend_ok", {**val, "confirm": 1}), ("amend_ok", {"c": "smoke-case-1", "i": 1}),
                   ("rv_close", val), ("rv_revise", val), ("fb_helpful", {"k": "lookup", "r": "q"})]:
        out = _interaction(client, aid, v)
        print(f"  {_BOLD}{aid}{_RST} → {out}")


def main() -> None:
    part_a_format_preview()
    part_b_routing()
    part_c_interactions()
    print(f"\n{_BOLD}✔ Xong smoke offline.{_RST} Dùng scripts/slack_live.py để soi rendering trên Slack THẬT.\n")


if __name__ == "__main__":
    main()
