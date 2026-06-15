"""Inbound adapter: kênh nhắn tin (Zalo OA, Slack) → cùng domain AnalysisService.

Mỗi nền tảng là một webhook (driving adapter): verify chữ ký → lấy text/HĐ → analyze →
trả lời gọn cho chat. Domain không đổi. MVP xử lý tin nhắn TEXT; tải file/ảnh từ API nền
tảng (cần token) là bước sau.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from legalguard.domain.analysis import AnalysisService
from legalguard.domain.models import AnalysisResult, Conversation, SourceMeta
from legalguard.domain.ports import (
    ChatSenderPort,
    ConversationStorePort,
    DocumentParserPort,
    LLMError,
)
from legalguard.domain.tenants import default_org

# Tín hiệu nội dung là hợp đồng (→ rà soát); ngược lại coi là câu hỏi tiếp (follow-up).
_SIGNALS = ("hợp đồng", "điều khoản", "trọng tài", "thanh toán", "kiểm định", "giao hàng",
            "contract", "clause", "arbitration", "payment", "inspection", "delivery")
_MAX_TURNS = 12      # khi vượt → summarize lượt cũ vào context, giữ N lượt gần
_KEEP_TURNS = 6
_MAX_SKEW = 300      # giây — chống replay (tin nhắn quá cũ → từ chối)

_PRIO_EMOJI = {"must_fix": "🔴", "negotiate": "🟠", "acceptable": "🟢"}
_MAX_REPLY = 3900    # Slack hiển thị đẹp ≤~4000 ký tự / message
_ACK = ("📥 Đã nhận! Em đang rà soát — thường mất vài phút (hợp đồng dài có thể lâu hơn). "
        "Kết quả sẽ trả vào đây.")
_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")   # tag @user trong text Slack

_log = logging.getLogger(__name__)


def format_chat_reply(result: AnalysisResult, lang: str = "vi") -> str:
    """Trả lời gọn cho chat (Zalo/Slack) — ngôn ngữ thường, tiếng Việt mặc định."""
    if not result.risks:
        return "✅ Không phát hiện điều khoản rủi ro rõ ràng trong nội dung bạn gửi."
    lines = ["📋 *Rà soát hợp đồng:*"]
    for r in result.risks:
        lines.append(f"{_PRIO_EMOJI.get(r.get('priority'), '•')} {r['clause']}: {r['risk']}")
    if result.strategy:
        lines += ["", f"🧭 {result.strategy}"]
    if result.needs_human_review:
        lines.append("⚖️ Có điểm rủi ro cao — nên để chuyên gia pháp lý duyệt trước khi áp dụng.")
    lines.append("\n_(AI hỗ trợ — không thay thế tư vấn luật chính thức.)_")
    out = "\n".join(lines)
    return out if len(out) <= _MAX_REPLY else out[:_MAX_REPLY] + "…"


def _context_from_result(result: AnalysisResult) -> str:
    risks = "; ".join(f"{r['clause']} ({r.get('priority', '')})" for r in result.risks)
    return f"Rủi ro: {risks or 'không'}. Chiến lược: {result.strategy[:400]}"


class ChatHandler:
    """Glue hội thoại: nhớ phiên (history + deal context) → rà soát hoặc trả lời tiếp."""

    def __init__(self, service: AnalysisService, parser: DocumentParserPort,
                 store: ConversationStorePort, default_tenant: str = "VN") -> None:
        self.service = service
        self.parser = parser
        self.store = store
        self.default_tenant = default_tenant

    def reply(self, conversation_id: str, text: str | None = None, attachment: bytes | None = None,
              filename: str | None = None, lang: str = "vi") -> str:
        conv = self.store.get(conversation_id) or Conversation(id=conversation_id)
        out = self._handle(conv, text, attachment, filename, lang)
        conv.add("user", (text or "").strip() or "(đã gửi tệp)")
        conv.add("assistant", out)
        self._summarize(conv)
        self.store.save(conv)
        return out

    def _summarize(self, conv: Conversation) -> None:
        """Progressive summarization: gộp lượt cũ vào context, giữ N lượt gần (bound token)."""
        if len(conv.history) <= _MAX_TURNS:
            return
        old, conv.history = conv.history[:-_KEEP_TURNS], conv.history[-_KEEP_TURNS:]
        if self.service.reasoner.available:
            text = "\n".join(f"{m['role']}: {m['content']}" for m in old)
            try:
                s = self.service.reasoner.complete(
                    f"Tóm tắt hội thoại sau, giữ ý chính + các quyết định:\n{text}")
                conv.context = (conv.context + "\n[Tóm tắt] " + s)[:2000]
            except LLMError:
                pass

    def _handle(self, conv: Conversation, text, attachment, filename, lang) -> str:
        org = default_org(self.default_tenant)
        contract, source = None, None
        if attachment is not None:
            source = SourceMeta.of(attachment, filename or "file")   # audit: hash file gốc
            try:
                contract = self.parser.extract_text(attachment, filename or "file")
            except ValueError as exc:
                return f"Không đọc được file: {exc}"
        elif text and any(s in text.lower() for s in _SIGNALS):
            contract = text

        if contract and contract.strip():                 # → RÀ SOÁT
            try:
                result = self.service.analyze(contract, org, lang=lang, source=source)
            except (ValueError, LLMError) as exc:
                return f"Xin lỗi, chưa xử lý được: {exc}"
            conv.context = _context_from_result(result)    # nhớ deal đang bàn
            return format_chat_reply(result, lang)
        if conv.context:                                   # → TRẢ LỜI TIẾP (follow-up)
            return self._followup(conv, text or "", lang)
        return "Gửi giúp em nội dung điều khoản hoặc file hợp đồng để rà soát nhé."

    def _followup(self, conv: Conversation, question: str, lang: str) -> str:
        hist = "\n".join(f"{m['role']}: {m['content']}" for m in conv.recent(6))
        tail = ", tiếng Việt." if lang == "vi" else ", in English."
        prompt = (f"Bối cảnh rà soát hợp đồng:\n{conv.context}\n\nLịch sử hội thoại:\n{hist}\n\n"
                  f"Câu hỏi tiếp của khách: {question}\nTrả lời ngắn gọn, ngôn ngữ thường" + tail)
        try:
            return self.service.reasoner.complete(prompt)
        except LLMError as exc:
            return f"Xin lỗi, chưa trả lời được: {exc}"


def _fresh(ts: str) -> bool:
    try:
        t = int(ts)
        if t > 1_000_000_000_000:        # mili-giây (Zalo) → giây
            t //= 1000
        return abs(time.time() - t) <= _MAX_SKEW
    except (ValueError, TypeError):
        return False


def _verify_slack(secret: str, ts: str, body: bytes, sig: str) -> bool:
    if not _fresh(ts):                       # chống replay
        return False
    base = b"v0:" + ts.encode() + b":" + body
    mac = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, sig or "")


def _verify_zalo(app_id: str, data: str, ts: str, secret: str, sig: str) -> bool:
    if not _fresh(ts):                       # chống replay (Zalo timestamp ms hoặc s)
        return False
    mac = "mac=" + hashlib.sha256((app_id + data + ts + secret).encode()).hexdigest()
    return hmac.compare_digest(mac, sig or "")


def _slack_file(event: dict) -> tuple[str | None, str | None]:
    """Chỉ trích (url, tên) — KHÔNG download ở đây (webhook phải ack <3s, tải ở task nền)."""
    files = event.get("files") or []
    if files and files[0].get("url_private"):
        return files[0]["url_private"], files[0].get("name", "file")
    return None, None


def _zalo_file(message: dict) -> tuple[str | None, str | None]:
    for att in message.get("attachments") or []:
        url = (att.get("payload") or {}).get("url")
        if url:
            return url, "scan.jpg"
    return None, None


def _process(handler: ChatHandler, sender: ChatSenderPort, key: str, send_to: str,
             text: str, file_url: str | None, filename: str | None,
             thread_ts: str | None = None, max_bytes: int = 10 * 1024 * 1024) -> None:
    """Chạy nền: tải file (nếu có) + analyze + gửi reply (webhook chỉ ack nhanh)."""
    # Ack ngay khi sắp PHÂN TÍCH (lâu ~vài phút) — follow-up nhanh thì không cần, tránh ồn.
    if file_url or any(s in (text or "").lower() for s in _SIGNALS):
        _safe_send(sender, send_to, _ACK, thread_ts)
    attachment: bytes | None = None
    if file_url:
        try:
            attachment = sender.download(file_url)
        except Exception:  # noqa: BLE001
            _log.exception("Không tải được file đính kèm (%s)", key)
            _safe_send(sender, send_to, "Xin lỗi, không tải được file đính kèm. "
                                        "Vui lòng gửi lại.", thread_ts)
            return
        if attachment and len(attachment) > max_bytes:
            _safe_send(sender, send_to,
                       f"File quá lớn (>{max_bytes // (1024 * 1024)}MB). "
                       "Vui lòng gửi bản gọn hơn.", thread_ts)
            return
    try:
        reply = handler.reply(key, text=text, attachment=attachment, filename=filename)
    except Exception:  # noqa: BLE001 — task nền: lỗi bất ngờ → vẫn báo khách, không sập im lặng
        _log.exception("Lỗi xử lý tin nhắn (%s)", key)
        reply = "Xin lỗi, có lỗi khi xử lý. Vui lòng thử lại sau."
    _safe_send(sender, send_to, reply, thread_ts)


def _safe_send(sender: ChatSenderPort, send_to: str, text: str, thread_ts: str | None) -> None:
    try:
        sender.send(send_to, text, thread_ts)
    except Exception:  # noqa: BLE001 — gửi lỗi (token sai/channel sai) không làm sập task nền
        _log.exception("Không gửi được reply (%s)", send_to)


def build_channels_router(handler: ChatHandler, *, slack_signing_secret: str = "",
                          zalo_oa_secret: str = "", zalo_app_id: str = "",
                          slack_sender: ChatSenderPort | None = None,
                          zalo_sender: ChatSenderPort | None = None,
                          max_upload_bytes: int = 10 * 1024 * 1024) -> APIRouter:
    router = APIRouter()
    # Dedup event Slack theo (channel, ts): mention trong channel bot là member sinh CẢ
    # `message` lẫn `app_mention` cho cùng 1 tin — event đến trước xử lý, event sau bỏ.
    # In-process (đủ cho 1 worker; đa instance cần Redis — cùng giới hạn như rate limiter).
    seen_events: dict[tuple, float] = {}

    if slack_signing_secret:
        @router.post("/channels/slack/events")
        async def slack_events(request: Request, background: BackgroundTasks):
            body = await request.body()
            if not _verify_slack(slack_signing_secret,
                                 request.headers.get("X-Slack-Request-Timestamp", ""),
                                 body, request.headers.get("X-Slack-Signature", "")):
                raise HTTPException(status_code=401, detail="Chữ ký Slack không hợp lệ.")
            # Slack giao at-least-once: bản retry (lần đầu chậm/lỗi) → ack, KHÔNG xử lý lại.
            if request.headers.get("X-Slack-Retry-Num"):
                return {"ok": True}
            payload = json.loads(body or b"{}")
            if payload.get("type") == "url_verification":      # Slack xác minh endpoint
                return {"challenge": payload.get("challenge")}
            event = payload.get("event") or {}
            etype = event.get("type", "message")
            # Bỏ qua tin của bot (tránh vòng lặp tự trả lời) + các subtype không phải tin mới
            # (message_changed/deleted...). file_share = tin nhắn kèm file → vẫn xử lý.
            if event.get("bot_id") or (etype == "message"
                                       and event.get("subtype") not in (None, "file_share")):
                return {"ok": True}
            channel = event.get("channel", "")
            # Dedup theo (channel, ts) — KHÔNG dedup theo loại event: event `message` chắc chắn
            # mang `files`, còn `app_mention` không đảm bảo → event nào tới trước thì xử lý.
            ts = event.get("ts") or event.get("event_ts") or ""
            if ts:
                if (channel, ts) in seen_events:
                    return {"ok": True}
                seen_events[(channel, ts)] = time.monotonic()
                if len(seen_events) > 500:                  # prune entry cũ (>10 phút)
                    cutoff = time.monotonic() - 600
                    for k in [k for k, t in seen_events.items() if t < cutoff]:
                        del seen_events[k]
            text = event.get("text", "")
            # Bóc tag @bot khỏi nội dung (user ID bot có sẵn trong payload `authorizations`).
            bot_uid = ((payload.get("authorizations") or [{}])[0]).get("user_id") or ""
            if bot_uid:
                text = text.replace(f"<@{bot_uid}>", "").strip()
            elif etype == "app_mention":
                text = _MENTION_RE.sub("", text, count=1).strip()
            thread_ts = event.get("thread_ts")                 # khách hỏi trong thread → reply đúng thread
            key = f"slack:{channel}"
            if slack_sender and slack_sender.available:         # ack nhanh, xử lý nền + gửi reply
                url, fn = _slack_file(event)
                background.add_task(_process, handler, slack_sender, key, channel, text,
                                    url, fn, thread_ts, max_upload_bytes)
                return {"ok": True}
            return {"ok": True, "reply": handler.reply(key, text=text)}

    if zalo_oa_secret:
        @router.post("/channels/zalo/webhook")
        async def zalo_webhook(request: Request, background: BackgroundTasks):
            body = await request.body()
            payload = json.loads(body or b"{}")
            if not _verify_zalo(zalo_app_id, body.decode("utf-8"), str(payload.get("timestamp", "")),
                                zalo_oa_secret, request.headers.get("X-ZEvent-Signature", "")):
                raise HTTPException(status_code=401, detail="Chữ ký Zalo không hợp lệ.")
            message = payload.get("message") or {}
            text = message.get("text", "")
            user_id = (payload.get("sender") or {}).get("id", "")
            key = f"zalo:{user_id}"
            if zalo_sender and zalo_sender.available:
                url, fn = _zalo_file(message)
                background.add_task(_process, handler, zalo_sender, key, user_id, text,
                                    url, fn, None, max_upload_bytes)
                return {"ok": True}
            return {"reply": handler.reply(key, text=text)}

    return router
