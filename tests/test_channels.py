import hashlib
import hmac
import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from legalguard.adapters.inbound.channels import (
    ChatHandler,
    _mrkdwn_blocks,
    build_channels_router,
    format_chat_reply,
)
from legalguard.adapters.outbound.conversation_store import InMemoryConversationStore
from legalguard.config.container import build_parser, build_service
from legalguard.domain.models import AnalysisResult


def _handler():
    return ChatHandler(build_service(), build_parser(), InMemoryConversationStore(), "VN")

MSG = "Tranh chấp bằng trọng tài tại Bắc Kinh."


class _FakeSender:
    def __init__(self, available=True, file_bytes=b""):
        self._a = available
        self.sent = []
        self.threads = []
        self.downloaded = []
        self._fb = file_bytes

    @property
    def available(self):
        return self._a

    def send(self, conv, text, thread_ts=None, blocks=None):
        self.sent.append((conv, text))
        self.threads.append(thread_ts)
        self.blocks = blocks

    def download(self, url):
        self.downloaded.append(url)
        return self._fb


def _client(slack="", zalo="", appid="", slack_sender=None, zalo_sender=None):
    handler = _handler()
    app = FastAPI()
    app.include_router(build_channels_router(handler, slack_signing_secret=slack,
                                             zalo_oa_secret=zalo, zalo_app_id=appid,
                                             slack_sender=slack_sender, zalo_sender=zalo_sender))
    return TestClient(app)


def _slack_post(client, secret, payload):
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))      # timestamp tươi (qua replay check)
    sig = "v0=" + hmac.new(secret.encode(), b"v0:" + ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    return client.post("/channels/slack/events", content=body,
                       headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig})


# ---- format / handler ----
def test_format_chat_reply():
    res = AnalysisResult(tenant="VN", risks=[{"clause": "Trọng tài", "risk": "Bất lợi",
                         "severity": "high", "priority": "must_fix"}], fallbacks=[],
                         needs_human_review=True, review_reasons=[], summary="", trace=[],
                         strategy="Giữ điều khoản trọng tài")
    out = format_chat_reply(res)
    assert "Trọng tài: Bất lợi" in out and "🔴" in out and "Giữ điều khoản trọng tài" in out


def test_format_chat_reply_marks_illegal():
    # Điều khoản TRÁI LUẬT được gắn nhãn ⚖️ + điều luật bị vi phạm.
    res = AnalysisResult(tenant="VN", risks=[{"clause": "Phạt 15%", "risk": "vượt trần",
                         "severity": "high", "priority": "must_fix",
                         "legal_status": "illegal", "violated_law": "Điều 301 LTM 2005"}],
                         fallbacks=[], needs_human_review=False, review_reasons=[],
                         summary="", trace=[], strategy="")
    out = format_chat_reply(res)
    assert "TRÁI LUẬT" in out and "Điều 301" in out


def test_format_chat_reply_illegal_without_violated_law():
    # illegal nhưng thiếu violated_law → hiện 'TRÁI LUẬT' không kèm '— vi phạm' (không lỗi chuỗi).
    res = AnalysisResult(tenant="VN", risks=[{"clause": "Điều X", "risk": "trái luật",
                         "severity": "high", "priority": "must_fix",
                         "legal_status": "illegal", "violated_law": ""}],
                         fallbacks=[], needs_human_review=False, review_reasons=[],
                         summary="", trace=[], strategy="")
    out = format_chat_reply(res)
    assert "TRÁI LUẬT" in out and "vi phạm" not in out


def test_format_chat_reply_unfavorable_not_marked_illegal():
    # điều khoản chỉ bất lợi → KHÔNG bị gắn nhãn TRÁI LUẬT nhầm.
    res = AnalysisResult(tenant="VN", risks=[{"clause": "Điều Y", "risk": "bất lợi",
                         "severity": "medium", "priority": "negotiate",
                         "legal_status": "unfavorable", "violated_law": ""}],
                         fallbacks=[], needs_human_review=False, review_reasons=[],
                         summary="", trace=[], strategy="")
    out = format_chat_reply(res)
    assert "TRÁI LUẬT" not in out


def test_handler_empty_prompts_for_input():
    assert "Gửi giúp" in _handler().reply("c1", text="")


def test_handler_analyzes_text():
    assert "Điều khoản trọng tài" in _handler().reply("c1", text=MSG)


def test_handler_legal_lookup_without_contract():
    # Câu hỏi pháp lý đứng một mình (không tín hiệu HĐ, chưa có deal) → tra cứu KB có grounding,
    # KHÔNG trả câu nhắc chung "Gửi giúp...".
    out = _handler().reply("cL", text="Thời điểm lập hóa đơn khi bán hàng hóa quy định ra sao?")
    assert out and "Gửi giúp" not in out


def test_handler_skips_lookup_for_casual_message():
    # Lời chào/ack vu vơ KHÔNG kích hoạt tra cứu (tránh tốn LLM) → trả câu nhắc nhẹ.
    out = _handler().reply("cZ", text="cảm ơn nhé")
    assert "Gửi giúp" in out


def test_legal_question_in_deal_routes_lookup():
    # Câu hỏi pháp lý CHUNG dù đang trong deal (đã analyze) → LOOKUP (template+nguồn), không follow-up.
    h = _handler()
    h.reply("cDeal", text=MSG)                          # analyze → set context
    assert h.store.get("cDeal").context                  # context đã set
    r = h.reply_ex("cDeal", text="Mức phạt vi phạm hợp đồng tối đa bao nhiêu %?")
    assert r.kind == "lookup"                            # câu pháp lý chung → lookup (nhất quán template)


def test_deal_specific_question_routes_followup():
    # Câu ĐẶC-THÙ-DEAL (không thuật ngữ luật chung) → follow-up theo ngữ cảnh, không lookup.
    h = _handler()
    h.reply("cDeal2", text=MSG)
    r = h.reply_ex("cDeal2", text="Nếu đối tác từ chối thì mình nên làm gì?")
    assert r.kind == ""                                  # follow-up (ChatReply không gắn kind)


def test_counter_offer_in_deal_routes_negotiation():
    # Trong deal, tin là PHẢN HỒI đối tác (không phải câu hỏi) → vòng ĐÀM PHÁN có cấu trúc.
    from legalguard.adapters.inbound.channels import _is_counter_offer
    assert _is_counter_offer("Đối tác đồng ý giảm phạt còn 10% nhưng giữ trọng tài Bắc Kinh.")
    assert not _is_counter_offer("Mức phạt tối đa là bao nhiêu?")     # câu hỏi → KHÔNG phải counter
    h = _handler()
    h.reply("cNego", text=MSG)                                        # analyze → set context
    r = h.reply_ex("cNego", text="Đối tác đồng ý giảm phạt còn 10%, nhưng từ chối đổi trọng tài.")
    assert r.kind == "negotiate"                                      # → vòng đàm phán


def test_format_negotiation_reply():
    from legalguard.adapters.inbound.channels import format_negotiation_reply
    out = format_negotiation_reply({"status": "close", "assessment": "đối tác nhượng đủ",
                                    "strategy": "chốt", "reply_vi": "Đồng ý", "grounded": True})
    assert "Nên CHỐT deal" in out and "đối tác nhượng đủ" in out and "Đồng ý" in out


def test_chat_history_redacts_pii_before_store():
    # Khách DÁN hợp đồng có PII vào chat → history KHÔNG được giữ email/sđt nguyên văn.
    store = InMemoryConversationStore()
    h = ChatHandler(build_service(), build_parser(), store, "VN")
    h.reply("cPII", text="Điều khoản trọng tài; liên hệ a@example.com, sđt 0912345678")
    hist = store.get("cPII").history
    joined = " ".join(m["content"] for m in hist if m["role"] == "user")
    assert "a@example.com" not in joined and "0912345678" not in joined   # đã redact
    assert "trọng tài" in joined.lower()                                  # vẫn giữ ngữ cảnh pháp lý


def test_conversation_remembers_context_and_history():
    store = InMemoryConversationStore()
    h = ChatHandler(build_service(), build_parser(), store, "VN")
    h.reply("c9", text=MSG)                              # lượt 1: rà soát → set context
    conv = store.get("c9")
    assert "trọng tài" in conv.context.lower()           # nhớ deal đang bàn
    assert len(conv.history) == 2

    out = h.reply("c9", text="Nếu đối tác từ chối SIAC thì sao?")   # follow-up (không có tín hiệu HĐ)
    assert out                                           # trả lời tiếp (stub) — không rà soát lại
    assert len(store.get("c9").history) == 4             # tích lũy lịch sử


# ---- Slack ----
def test_slack_challenge_and_signature():
    c = _client(slack="slacksecret")
    r = _slack_post(c, "slacksecret", {"type": "url_verification", "challenge": "abc123"})
    assert r.json() == {"challenge": "abc123"}


def test_slack_rejects_bad_signature():
    c = _client(slack="slacksecret")
    r = c.post("/channels/slack/events", content=b"{}",
               headers={"X-Slack-Request-Timestamp": "1", "X-Slack-Signature": "v0=bad"})
    assert r.status_code == 401


def test_slack_message_returns_reply():
    c = _client(slack="slacksecret")
    r = _slack_post(c, "slacksecret", {"event": {"text": MSG}})
    assert "Điều khoản trọng tài" in r.json()["reply"]


# ---- Zalo ----
def test_zalo_message_and_signature():
    secret, appid = "zalosecret", "app1"
    c = _client(zalo=secret, appid=appid)
    ts = str(int(time.time()))      # timestamp tươi (qua replay check)
    body = json.dumps({"timestamp": ts, "message": {"text": MSG}}).encode()
    mac = "mac=" + hashlib.sha256((appid + body.decode() + ts + secret).encode()).hexdigest()
    r = c.post("/channels/zalo/webhook", content=body, headers={"X-ZEvent-Signature": mac})
    assert "Điều khoản trọng tài" in r.json()["reply"]


def test_zalo_rejects_bad_signature():
    c = _client(zalo="zalosecret", appid="app1")
    body = json.dumps({"timestamp": "111", "message": {"text": "x"}}).encode()
    r = c.post("/channels/zalo/webhook", content=body, headers={"X-ZEvent-Signature": "mac=bad"})
    assert r.status_code == 401


# ---- Outbound: gửi reply + tải file ----
def test_slack_sends_reply_via_sender():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    r = _slack_post(c, "s", {"event": {"text": MSG, "channel": "C123"}})
    assert r.json() == {"ok": True}                       # ack nhanh
    assert sender.sent and sender.sent[0][0] == "C123"    # đã gửi về đúng channel
    assert "Đã nhận" in sender.sent[0][1]                 # ack tức thì trước khi phân tích
    assert "Điều khoản trọng tài" in sender.sent[-1][1]   # rồi mới tới kết quả


def test_per_conversation_lock_no_lost_updates():
    # 2 tin ĐỒNG THỜI cùng 1 hội thoại → lock tuần tự hóa → KHÔNG mất lượt (chống last-write-wins).
    import threading
    h = _handler()

    def ask(msg):
        h.reply("cRACE", text=msg)

    threads = [threading.Thread(target=ask, args=(f"Mức phạt vi phạm hợp đồng là bao nhiêu {i}?",))
               for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    hist = h.store.get("cRACE").history
    assert len(hist) == 8                  # 4 user + 4 assistant — không lượt nào bị đè mất


def test_mrkdwn_blocks_splits_long_reply_no_truncation():
    # Reply dài (HĐ nhiều rủi ro) phải chia nhiều block, KHÔNG cụt, mỗi block ≤ 3000 ký tự.
    long_reply = "\n".join(f"🔴 Điều {i}: rủi ro chi tiết tiếng Việt có dấu" for i in range(300))
    blocks = _mrkdwn_blocks(long_reply)
    assert len(blocks) >= 2                                          # chia nhiều block
    assert all(len(b["text"]["text"]) <= 3000 for b in blocks)      # không vượt giới hạn Slack
    joined = "\n".join(b["text"]["text"] for b in blocks)
    assert "Điều 0:" in joined and "Điều 299:" in joined            # giữ cả đầu lẫn cuối (không cụt)


def test_mrkdwn_blocks_short_reply_single_block():
    blocks = _mrkdwn_blocks("Rủi ro: trọng tài Bắc Kinh.")
    assert len(blocks) == 1 and blocks[0]["type"] == "section"


def test_slack_reply_threads_under_top_level_message():
    # Mention ở CẤP CHANNEL (không thread_ts) → ack + reply phải thread NGAY DƯỚI tin người hỏi (dùng ts).
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"event": {"text": MSG, "channel": "C1", "ts": "111.22"}})
    assert sender.threads and all(t == "111.22" for t in sender.threads)


def test_slack_reply_stays_in_existing_thread():
    # Hỏi TRONG thread → reply đúng thread gốc (thread_ts), không tách theo ts tin mới.
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"event": {"text": MSG, "channel": "C1", "ts": "999.00", "thread_ts": "111.22"}})
    assert sender.threads and all(t == "111.22" for t in sender.threads)


def test_slack_acks_lookup_question_not_silent():
    # Câu hỏi pháp lý (lookup, ~30s) → phải gửi ack "đang tra cứu" trước, không để user chờ im.
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"event": {"text": "Mức phạt vi phạm hợp đồng tối đa bao nhiêu %?",
                                   "channel": "C1", "ts": "1.1"}})
    assert sender.sent and "tra cứu" in sender.sent[0][1].lower()   # ack tra cứu đi trước
    assert len(sender.sent) >= 2                                     # ack + kết quả


def test_slack_no_ack_for_casual_message():
    # Tin xã giao (không phải câu hỏi) → KHÔNG ack tra cứu (tránh phiền).
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"event": {"text": "cảm ơn nhé", "channel": "C1", "ts": "2.2"}})
    assert all("tra cứu" not in t.lower() for _, t in sender.sent)


def test_slack_ignores_bot_messages_no_reply_loop():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    r = _slack_post(c, "s", {"event": {"text": "reply của bot", "channel": "C123",
                                       "bot_id": "B042"}})
    assert r.json() == {"ok": True}
    assert sender.sent == []                              # không tự trả lời chính mình


def test_slack_ignores_retry_deliveries():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    body = json.dumps({"event": {"text": MSG, "channel": "C1"}}).encode()
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(b"s", b"v0:" + ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    r = c.post("/channels/slack/events", content=body,
               headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig,
                        "X-Slack-Retry-Num": "1"})       # bản giao lại (at-least-once)
    assert r.json() == {"ok": True}
    assert sender.sent == []                              # không xử lý trùng


def test_slack_ignores_message_edits_and_deletes():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    for subtype in ("message_changed", "message_deleted"):
        _slack_post(c, "s", {"event": {"subtype": subtype, "channel": "C1"}})
    assert sender.sent == []                              # edit/xóa tin không kích hoạt bot


def test_slack_replies_in_thread_when_asked_in_thread():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"event": {"text": MSG, "channel": "C1", "thread_ts": "171.001"}})
    assert len(sender.threads) == 2                        # ack + kết quả
    assert all(t == "171.001" for t in sender.threads)     # cả hai đúng thread


def test_slack_ack_sent_before_file_analysis():
    sender = _FakeSender(file_bytes=MSG.encode())
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"event": {"text": "", "channel": "C1",
                                   "files": [{"url_private": "https://files/x", "name": "hd.txt"}]}})
    assert "Đã nhận" in sender.sent[0][1]                  # ack trước
    assert "Điều khoản trọng tài" in sender.sent[-1][1]    # kết quả sau


def test_slack_no_ack_for_quick_followup():
    # Câu hỏi thường (không tín hiệu HĐ, không file) → trả lời thẳng, KHÔNG ack (tránh ồn).
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"event": {"text": "xin chào bạn nhé", "channel": "C1"}})
    assert len(sender.sent) == 1
    assert "Đã nhận" not in sender.sent[0][1]


def test_slack_app_mention_strips_tag_and_analyzes():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"authorizations": [{"user_id": "U99"}],
                         "event": {"type": "app_mention", "channel": "C1",
                                   "text": f"<@U99> {MSG}"}})
    assert "Điều khoản trọng tài" in sender.sent[-1][1]    # mention → vẫn rà soát
    # tag @bot không lọt vào nội dung phân tích (không nằm trong reply prompt nào)


def test_slack_message_with_bot_mention_deduped():
    # Channel bot là member: cùng 1 tin mention sinh CẢ event message lẫn app_mention
    # (cùng ts). Event đến TRƯỚC xử lý, event sau bị dedup → khách nhận đúng 1 reply.
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    base = {"authorizations": [{"user_id": "U99"}]}
    _slack_post(c, "s", {**base, "event": {"type": "message", "channel": "C1",
                                           "ts": "111.222", "text": f"<@U99> {MSG}"}})
    assert len(sender.sent) == 2                           # message tới trước: ack + kết quả
    _slack_post(c, "s", {**base, "event": {"type": "app_mention", "channel": "C1",
                                           "ts": "111.222", "text": f"<@U99> {MSG}"}})
    assert len(sender.sent) == 2                           # app_mention cùng ts → bỏ qua
    assert "Điều khoản trọng tài" in sender.sent[-1][1]    # tag @bot đã bóc, vẫn rà soát


def test_slack_mention_with_file_uses_message_event_files():
    # Mention + đính kèm file: event `message` (chắc chắn có files) tới trước → file
    # được tải và phân tích; app_mention (có thể thiếu files) tới sau bị dedup.
    sender = _FakeSender(file_bytes=MSG.encode())
    c = _client(slack="s", slack_sender=sender)
    base = {"authorizations": [{"user_id": "U99"}]}
    _slack_post(c, "s", {**base, "event": {
        "type": "message", "subtype": "file_share", "channel": "C1", "ts": "222.333",
        "text": "<@U99> xem giúp", "files": [{"url_private": "https://files/x", "name": "hd.txt"}]}})
    _slack_post(c, "s", {**base, "event": {"type": "app_mention", "channel": "C1",
                                           "ts": "222.333", "text": "<@U99> xem giúp"}})
    assert sender.downloaded == ["https://files/x"]        # file được tải đúng 1 lần
    assert len(sender.sent) == 2                           # ack + kết quả
    assert "Điều khoản trọng tài" in sender.sent[-1][1]    # phân tích nội dung file


def test_slack_mention_other_user_still_processed():
    # Mention NGƯỜI KHÁC (không phải bot) thì vẫn là tin nhắn thường → xử lý bình thường.
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"authorizations": [{"user_id": "U99"}],
                         "event": {"type": "message", "channel": "C1",
                                   "text": f"<@U42> xem giúp: {MSG}"}})
    assert len(sender.sent) == 2                           # ack + kết quả


def test_slack_rejects_oversize_attachment():
    sender = _FakeSender(file_bytes=b"x" * 2048)          # file "tải về" 2KB
    handler = _handler()
    app = FastAPI()
    app.include_router(build_channels_router(handler, slack_signing_secret="s",
                                             slack_sender=sender, max_upload_bytes=1024))
    c = TestClient(app)
    _slack_post(c, "s", {"event": {"text": "", "channel": "C1",
                                   "files": [{"url_private": "https://files/big", "name": "x.pdf"}]}})
    assert "quá lớn" in sender.sent[-1][1]                # báo khách, không phân tích


def test_slack_downloads_attachment_then_analyzes():
    sender = _FakeSender(file_bytes=MSG.encode())          # "file" tải về = nội dung HĐ
    c = _client(slack="s", slack_sender=sender)
    payload = {"event": {"text": "", "channel": "C1",
                         "files": [{"url_private": "https://files/x", "name": "hd.txt"}]}}
    _slack_post(c, "s", payload)
    assert sender.downloaded == ["https://files/x"]        # đã tải file
    assert "Điều khoản trọng tài" in sender.sent[-1][1]    # phân tích nội dung file


# ---- Slack feedback (interactive buttons) ----
def _slack_interaction(client, secret, action_id, value):
    import urllib.parse
    payload = {"type": "block_actions", "user": {"id": "U1"}, "channel": {"id": "C1"},
               "actions": [{"action_id": action_id, "value": value}]}
    body = ("payload=" + urllib.parse.quote(json.dumps(payload))).encode()
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(secret.encode(), b"v0:" + ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    return client.post("/channels/slack/interactions", content=body,
                       headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig,
                                "Content-Type": "application/x-www-form-urlencoded"})


def test_slack_interaction_records_feedback():
    c = _client(slack="sek")
    r = _slack_interaction(c, "sek", "fb_wrong", json.dumps({"k": "lookup", "r": "phạt vi phạm?"}))
    assert r.status_code == 200
    assert r.json().get("replace_original") is True        # thay tin gốc bằng xác nhận


def test_slack_interaction_bad_signature_401():
    c = _client(slack="sek")
    r = c.post("/channels/slack/interactions", content=b"payload=%7B%7D",
               headers={"X-Slack-Request-Timestamp": "0", "X-Slack-Signature": "v0=bad"})
    assert r.status_code == 401


def test_reply_ex_marks_lookup_and_analysis_kind():
    h = _handler()
    assert h.reply_ex("cK", text="Mức phạt vi phạm hợp đồng tối đa bao nhiêu?").kind == "lookup"
    assert h.reply_ex("cA", text=MSG).kind == "analysis"
