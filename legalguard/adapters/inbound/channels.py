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
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from legalguard.domain.analysis import AnalysisService
from legalguard.domain.models import AnalysisResult, Conversation, Feedback, Outcome, SourceMeta
from legalguard.domain.negotiation import NegotiationState, state_from_json, state_to_json
from legalguard.domain.ports import (
    ChatSenderPort,
    ConversationStorePort,
    DocumentParserPort,
    LLMError,
)
from legalguard.domain.redaction import redact
from legalguard.domain.tenants import default_org

# Tín hiệu nội dung là hợp đồng (→ rà soát); ngược lại coi là câu hỏi tiếp (follow-up).
_SIGNALS = ("hợp đồng", "điều khoản", "trọng tài", "thanh toán", "kiểm định", "giao hàng",
            "contract", "clause", "arbitration", "payment", "inspection", "delivery")
# Dấu hỏi / từ để hỏi → đây là CÂU HỎI (không phải đoạn HĐ dán vào), kể cả khi chứa từ khóa HĐ.
_INTERROG_RE = re.compile(
    r"\?|\b(gì|nào|sao|ra sao|thế nào|như thế nào|bao nhiêu|khi nào|ở đâu|"
    r"có được|có phải|có cần|được không|hay không)\b", re.IGNORECASE)
# Thuật ngữ pháp lý → câu hỏi đáng tra cứu KB (kết hợp với interrogative ở dưới).
_LEGAL_TERM_RE = re.compile(
    r"luật|điều|khoản|nghị định|thông tư|quy định|phạt|bồi thường|hóa đơn|thuế|lao động|hiệu lực",
    re.IGNORECASE)


def _is_question(text: str) -> bool:
    """Câu hỏi rõ ràng: có dấu '?' hoặc từ để hỏi (dùng để ưu tiên TRA CỨU hơn rà soát HĐ)."""
    return bool(_INTERROG_RE.search(text))


def _looks_like_question(text: str) -> bool:
    """Đáng tra cứu KB nếu là câu hỏi rõ, có thuật ngữ luật, hoặc đủ dài (≥6 từ) — tránh tốn LLM cho lời chào."""
    return _is_question(text) or bool(_LEGAL_TERM_RE.search(text)) or len(text.split()) >= 6


def _is_legal_lookup(text: str) -> bool:
    """Câu hỏi pháp lý CHUNG (từ-để-hỏi + thuật ngữ luật) → ưu tiên LOOKUP (template + dẫn nguồn) hơn
    follow-up, kể cả đang trong deal. Câu đặc-thù-deal ('nếu đối tác từ chối…') không khớp → follow-up."""
    return bool(_is_question(text) and _LEGAL_TERM_RE.search(text))


# Tín hiệu đây là PHẢN HỒI/COUNTER-OFFER của đối tác (đang trong deal) → vòng đàm phán có cấu trúc.
_COUNTER_RE = re.compile(
    r"đối tác|đối phương|bên kia|bên bán|bên mua|họ (nói|đề nghị|muốn|đồng ý|từ chối)|phản hồi|phản đề|"
    r"đồng ý|chấp nhận|từ chối|đề nghị|yêu cầu|giảm (còn|xuống)|tăng|nhượng|chốt|walk|counter|offer|%",
    re.IGNORECASE)


def _is_counter_offer(text: str) -> bool:
    """Trong deal, tin KHÔNG phải câu hỏi nhưng có tín hiệu phản hồi đối tác → vòng đàm phán đa phiên."""
    return bool(text and not _is_question(text) and _COUNTER_RE.search(text))


# Meta-câu-hỏi về ĐỘ TIN CẬY của công cụ (khác câu hỏi pháp lý) → trả công bố độ chính xác.
_TRUST_RE = re.compile(
    r"độ (chính xác|tin cậy)|đáng tin|tin cậy không|có bịa|có chính xác|chính xác không|"
    r"\baccuracy\b|\btrust(worthy)?\b|kiểm chứng thế nào|làm sao tin", re.IGNORECASE)


def _is_trust_query(text: str) -> bool:
    return bool(text and _TRUST_RE.search(text))
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
        # Đánh dấu TRÁI LUẬT (có thể vô hiệu) — đòn mạnh cho luật sư, khác 'bất lợi nhưng hợp pháp'.
        tag = ""
        if r.get("legal_status") == "illegal":
            vl = r.get("violated_law", "")
            tag = f" ⚖️ *TRÁI LUẬT{' — vi phạm ' + vl if vl else ''}*"
        lines.append(f"{_PRIO_EMOJI.get(r.get('priority'), '•')} {r['clause']}: {r['risk']}{tag}")
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


_NEGO_STATUS = {"continue": "🔄 Tiếp tục đàm phán", "close": "✅ Nên CHỐT deal",
                "walk_away": "🚪 Nên RÚT (walk-away)"}


def format_negotiation_reply(r: dict, lang: str = "vi") -> str:
    """Định dạng 1 vòng đàm phán (negotiate_round) cho Slack: status + đánh giá + chiến lược + câu trả lời."""
    lines = [f"*{_NEGO_STATUS.get(r.get('status'), '🔄 Đàm phán')}*"]
    if r.get("assessment"):
        lines.append(f"📊 *Đánh giá phản hồi:* {r['assessment']}")
    if r.get("strategy"):
        lines.append(f"🧭 *Vòng tới:* {r['strategy']}")
    st = r.get("state") or {}
    if st.get("secured"):
        lines.append("✅ *Đã chốt:* " + "; ".join(st["secured"]))
    if st.get("conceded"):
        lines.append("↩️ *Ta đã nhượng:* " + "; ".join(st["conceded"]))
    if r.get("walk_away_recommended"):
        lines.append("🚨 *Red-line bị chặn + ta có BATNA → cân nhắc RÚT.*")
    moves = r.get("next_moves") or []
    if moves:
        mv = []
        for m in moves:
            flag = " ⚠️ _gần red-line — cân nhắc_" if m.get("near_red_line") else ""
            ret = f" → đổi lấy: {m['in_return_for']}" if m.get("in_return_for") else ""
            mv.append(f"• Nhượng: {m.get('offer', '')}{ret}{flag}")
        lines.append("🪜 *Nước đi đề xuất (thang nhượng-bộ):*\n" + "\n".join(mv))
    reply = r.get("reply_vi") if lang == "vi" else (r.get("reply_en") or r.get("reply_vi"))
    if reply:
        lines.append(f"💬 *Câu trả lời đối tác:*\n{reply}")
    if not r.get("grounded"):
        lines.append("_(khung sơ bộ — chưa cấu hình AI)_")
    out = "\n\n".join(lines)
    return out if len(out) <= _MAX_REPLY else out[:_MAX_REPLY] + "…"


@dataclass
class ChatReply:
    """Kết quả 1 lượt chat: text + ngữ cảnh feedback (kind/ref) để gắn nút trên Slack."""
    text: str
    kind: str = ""        # "" | analysis | lookup (rỗng = không gắn nút feedback)
    ref: str = ""         # case_id (analysis) hoặc câu hỏi (lookup)


class ChatHandler:
    """Glue hội thoại: nhớ phiên (history + deal context) → rà soát hoặc trả lời tiếp."""

    def __init__(self, service: AnalysisService, parser: DocumentParserPort,
                 store: ConversationStorePort, default_tenant: str = "VN") -> None:
        self.service = service
        self.parser = parser
        self.store = store
        self.default_tenant = default_tenant
        # Lock PER-CONVERSATION (in-process): tin cùng 1 hội thoại xử lý tuần tự → hết race
        # load→sửa→save (last-write-wins). Hội thoại khác nhau vẫn chạy SONG SONG. Đủ cho 1 instance;
        # đa-instance cần Redis lock (xem docs/internal/scale-concurrency.md).
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _conv_lock(self, conversation_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(conversation_id, threading.Lock())

    def reply_ex(self, conversation_id: str, text: str | None = None, attachment: bytes | None = None,
                 filename: str | None = None, lang: str = "vi") -> ChatReply:
        with self._conv_lock(conversation_id):     # tuần tự hóa theo hội thoại (chống race)
            conv = self.store.get(conversation_id) or Conversation(id=conversation_id)
            res = self._handle(conv, text, attachment, filename, lang)
            # REDACT trước khi lưu history: khách DÁN hợp đồng vào chat → không giữ PII nguyên văn.
            # `_handle` đã redact bản gửi LLM riêng → không ảnh hưởng phân tích.
            user_msg = redact((text or "").strip())[0] or "(đã gửi tệp)"
            conv.add("user", user_msg)
            conv.add("assistant", res.text)
            self._summarize(conv)
            self.store.save(conv)
            return res

    def reply(self, conversation_id: str, text: str | None = None, attachment: bytes | None = None,
              filename: str | None = None, lang: str = "vi") -> str:
        return self.reply_ex(conversation_id, text, attachment, filename, lang).text

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

    def _handle(self, conv: Conversation, text, attachment, filename, lang) -> ChatReply:
        org = default_org(self.default_tenant)
        if attachment is None and _is_trust_query(text or ""):     # meta-câu-hỏi về độ tin cậy → công bố
            from legalguard.domain.trust import format_trust_text
            return ChatReply(format_trust_text())
        contract, source = None, None
        if attachment is not None:
            source = SourceMeta.of(attachment, filename or "file")   # audit: hash file gốc
            try:
                contract = self.parser.extract_text(attachment, filename or "file")
            except ValueError as exc:
                return ChatReply(f"Không đọc được file: {exc}")
        elif (text and not _is_question(text) and any(s in text.lower() for s in _SIGNALS)
              and not (conv.context and _is_counter_offer(text))):
            contract = text                            # tín hiệu HĐ & KHÔNG phải câu hỏi → rà soát
            # (đang trong deal + là phản hồi đối tác → KHÔNG re-analyze, để rơi xuống nhánh đàm phán)

        if contract and contract.strip():                 # → RÀ SOÁT
            try:
                result = self.service.analyze(contract, org, lang=lang, source=source)
            except (ValueError, LLMError) as exc:
                return ChatReply(f"Xin lỗi, chưa xử lý được: {exc}")
            conv.context = _context_from_result(result)    # nhớ deal đang bàn
            # Seed red-line đàm phán = các rủi ro must_fix (điểm sống còn KHÔNG nhượng) → vòng đàm phán sau
            # có bộ nhớ cấu trúc + guardrail walk-away tất định.
            red = [r["clause"] for r in result.risks if r.get("priority") == "must_fix" and r.get("clause")]
            conv.nego_state = state_to_json(NegotiationState(red_lines=red))
            return ChatReply(format_chat_reply(result, lang), "analysis", result.case_id or "")
        # Trong deal: tin là PHẢN HỒI/COUNTER của đối tác → VÒNG ĐÀM PHÁN có cấu trúc (không phải Q&A chung).
        if conv.context and _is_counter_offer(text or ""):
            return ChatReply(self._negotiate(conv, text or "", lang), "negotiate", "")
        # Follow-up theo deal — TRỪ câu hỏi pháp lý CHUNG (→ ưu tiên lookup template+dẫn nguồn cho nhất quán).
        if conv.context and not _is_legal_lookup(text or ""):
            return ChatReply(self._followup(conv, text or "", lang))
        if text and _looks_like_question(text):            # → TRA CỨU LUẬT có grounding (template + nguồn)
            answer, snippets = self.service.lookup(text, org, lang=lang)
            if snippets:                                   # hiện nguồn (dẫn điều/khoản) gọn dưới câu trả lời
                srcs = " · ".join(s.source for s in snippets[:3])
                answer = f"{answer}\n\n📎 Nguồn: {srcs}"
            return ChatReply(answer, "lookup", text)
        if conv.context:                                   # có deal, không phải câu hỏi → follow-up
            return ChatReply(self._followup(conv, text or "", lang))
        return ChatReply("Gửi giúp em nội dung điều khoản / file hợp đồng để rà soát, "
                         "hoặc đặt câu hỏi pháp lý nhé.")

    def _negotiate(self, conv: Conversation, partner_message: str, lang: str) -> str:
        """Vòng đàm phán đa phiên trên Slack: bối cảnh deal + SỔ nhượng-bộ + tin đối tác → round có cấu trúc.
        Sổ nhượng-bộ (`conv.nego_state`) mang qua các vòng → agent NHỚ đã nhượng/chốt gì (không 'quên' do
        context free-text cắt cụt) + guardrail walk-away theo red-line."""
        state = state_from_json(conv.nego_state)
        try:
            r = self.service.negotiate_round(conv.context, partner_message, position=None,
                                             state=state, lang=lang)
        except LLMError as exc:
            return f"Xin lỗi, chưa xử lý được vòng đàm phán: {exc}"
        upd = r.get("state") or {}
        conv.nego_state = state_to_json(NegotiationState(
            red_lines=upd.get("red_lines", state.red_lines), secured=upd.get("secured", []),
            conceded=upd.get("conceded", []), open_items=upd.get("open_items", [])))
        nxt = r.get("reply_vi") or r.get("assessment") or ""
        conv.context = (conv.context + f"\n--- Đối tác: {partner_message}\n--- Ta: {nxt}")[:1800]
        return format_negotiation_reply(r, lang)

    def _followup(self, conv: Conversation, question: str, lang: str) -> str:
        hist = "\n".join(f"{m['role']}: {m['content']}" for m in conv.recent(6))
        tail = ", tiếng Việt." if lang == "vi" else ", in English."
        prompt = (f"Bối cảnh rà soát hợp đồng:\n{conv.context}\n\nLịch sử hội thoại:\n{hist}\n\n"
                  f"Câu hỏi tiếp của khách: {question}\nTrả lời CHUYÊN NGHIỆP, súc tích, đi thẳng vấn đề" + tail)
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


# Nút feedback Slack (Block Kit). action_id → rating; value mang ngữ cảnh {kind, ref}.
_FB_RATING = {"fb_helpful": "helpful", "fb_wrong": "wrong", "fb_incomplete": "incomplete"}


def _feedback_blocks(kind: str, ref: str) -> list[dict]:
    val = json.dumps({"k": kind, "r": ref[:300]}, ensure_ascii=False)   # value max 2000 ký tự

    def btn(txt: str, aid: str, style: str | None = None) -> dict:
        b = {"type": "button", "text": {"type": "plain_text", "text": txt, "emoji": True},
             "action_id": aid, "value": val}
        if style:
            b["style"] = style
        return b

    return [{"type": "actions", "block_id": "lg_feedback", "elements": [
        btn("👍 Đúng", "fb_helpful", "primary"),
        btn("⚠️ Sai", "fb_wrong", "danger"),
        btn("➖ Thiếu", "fb_incomplete")]}]


# Nút GHI KẾT QUẢ đàm phán (flywheel) — chỉ gắn cho reply phân tích có case_id. value mang case_id.
_OC_RESULT = {"oc_accepted": "accepted", "oc_partial": "partial", "oc_rejected": "rejected"}


def _outcome_blocks(case_id: str) -> list[dict]:
    val = json.dumps({"c": case_id[:120]}, ensure_ascii=False)

    def btn(txt: str, aid: str, style: str | None = None) -> dict:
        b = {"type": "button", "text": {"type": "plain_text", "text": txt, "emoji": True},
             "action_id": aid, "value": val}
        if style:
            b["style"] = style
        return b

    return [{"type": "actions", "block_id": "lg_outcome", "elements": [
        btn("✓ Chốt được (thắng)", "oc_accepted", "primary"),
        btn("~ Một phần", "oc_partial"),
        btn("✗ Không đạt", "oc_rejected", "danger")]}]


def _record_deal_outcome(service: AnalysisService, org_id: str, case_id: str, result: str) -> int:
    """Ghi Outcome cho MỌI điều khoản (fallback) của 1 case → nuôi win-rate. Trả số điều đã ghi (0 nếu
    không có case / sai org). Cô lập org để chống ghi chéo công ty."""
    if not case_id:
        return 0
    case = service.get_case(case_id)
    if case is None or getattr(case, "org_id", None) != org_id:
        return 0
    clauses = list(dict.fromkeys(f.get("clause", "") for f in (case.fallbacks or []) if f.get("clause")))
    n = 0
    for cl in clauses:
        try:
            service.record_outcome(Outcome(
                id=uuid.uuid4().hex, org_id=org_id, case_id=case_id, clause=cl, tactic="",
                result=result, created_at=datetime.now(timezone.utc).isoformat()))
            n += 1
        except Exception:  # noqa: BLE001 — outcome là phụ; vẫn ack để Slack không retry
            _log.exception("Không ghi được outcome từ Slack")
    return n


def _mrkdwn_blocks(text: str, limit: int = 2900, max_blocks: int = 12) -> list[dict]:
    """Chia reply thành NHIỀU section block Slack (mỗi block ≤ limit; Slack chặn 3000 ký tự/section).
    Cắt ở ranh giới DÒNG để không vỡ chữ/cụt câu (reply HĐ nhiều rủi ro thường > 2900). Quá dài →
    giữ `max_blocks` block + ghi chú xem bản đầy đủ trên web."""
    chunks: list[str] = []
    cur = ""
    for line in text.split("\n"):
        while len(line) > limit:                 # dòng đơn quá dài → cắt theo KÝ TỰ (an toàn UTF-8)
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if cur and len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    if len(chunks) > max_blocks:
        chunks = chunks[:max_blocks]
        chunks[-1] += "\n… (rút gọn — xem bản đầy đủ trên web /app)"
    return [{"type": "section", "text": {"type": "mrkdwn", "text": c}} for c in chunks]


def _process(handler: ChatHandler, sender: ChatSenderPort, key: str, send_to: str,
             text: str, file_url: str | None, filename: str | None,
             thread_ts: str | None = None, max_bytes: int = 10 * 1024 * 1024,
             supports_buttons: bool = False) -> None:
    """Chạy nền: tải file (nếu có) + analyze + gửi reply (webhook chỉ ack nhanh)."""
    # Ack ngay khi sắp PHÂN TÍCH HĐ (lâu ~vài phút). Câu hỏi tra cứu (lookup) nhanh → KHÔNG ack
    # (khớp routing: tín hiệu HĐ mà là câu hỏi thì đi lookup, không phân tích).
    will_analyze = bool(file_url) or (
        bool(text) and not _is_question(text) and any(s in text.lower() for s in _SIGNALS))
    if will_analyze:
        _safe_send(sender, send_to, _ACK, thread_ts)
    elif text and _looks_like_question(text):       # lookup/follow-up cũng chậm (~30s) → ack để không "chờ im"
        _safe_send(sender, send_to, "🔎 Đang tra cứu, chờ chút nhé…", thread_ts)
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
    blocks = None
    try:
        res = handler.reply_ex(key, text=text, attachment=attachment, filename=filename)
        reply = res.text
        if supports_buttons and res.kind:          # gắn nút feedback (Slack) cho câu trả lời thật
            # Chia reply thành nhiều block (không cụt ở 2900) rồi mới tới nút feedback.
            blocks = [*_mrkdwn_blocks(reply), *_feedback_blocks(res.kind, res.ref)]
            if res.kind == "analysis" and res.ref:  # reply phân tích (có case_id) → thêm nút ghi kết quả
                blocks += _outcome_blocks(res.ref)
    except Exception:  # noqa: BLE001 — task nền: lỗi bất ngờ → vẫn báo khách, không sập im lặng
        _log.exception("Lỗi xử lý tin nhắn (%s)", key)
        reply = "Xin lỗi, có lỗi khi xử lý. Vui lòng thử lại sau."
    _safe_send(sender, send_to, reply, thread_ts, blocks)


def _safe_send(sender: ChatSenderPort, send_to: str, text: str, thread_ts: str | None,
               blocks: list | None = None) -> None:
    try:
        sender.send(send_to, text, thread_ts, blocks)
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
            # Reply LUÔN theo thread: nếu hỏi trong thread → đúng thread đó; nếu mention ở cấp channel
            # → mở thread NGAY DƯỚI tin của người hỏi (dùng `ts` của tin đó) thay vì trả rời ở channel.
            thread_ts = event.get("thread_ts") or event.get("ts")
            # Hội thoại theo THREAD (không theo cả channel) → mỗi thread/người = 1 deal riêng, không
            # lẫn ngữ cảnh khi nhiều người dùng chung 1 channel.
            key = f"slack:{channel}:{thread_ts}"
            if slack_sender and slack_sender.available:         # ack nhanh, xử lý nền + gửi reply
                url, fn = _slack_file(event)
                background.add_task(_process, handler, slack_sender, key, channel, text,
                                    url, fn, thread_ts, max_upload_bytes, True)
                return {"ok": True}
            return {"ok": True, "reply": handler.reply(key, text=text)}

        @router.post("/channels/slack/interactions")
        async def slack_interactions(request: Request):
            # Nút feedback (block_actions) → ghi Feedback. Verify chữ ký trên RAW body TRƯỚC khi parse.
            body = await request.body()
            if not _verify_slack(slack_signing_secret,
                                 request.headers.get("X-Slack-Request-Timestamp", ""),
                                 body, request.headers.get("X-Slack-Signature", "")):
                raise HTTPException(status_code=401, detail="Chữ ký Slack không hợp lệ.")
            try:
                payload = json.loads(parse_qs(body.decode("utf-8")).get("payload", ["{}"])[0])
            except (UnicodeDecodeError, json.JSONDecodeError, IndexError):
                raise HTTPException(status_code=400, detail="Payload không hợp lệ.") from None
            if payload.get("type") != "block_actions":
                return {"ok": True}
            action = (payload.get("actions") or [{}])[0]
            aid = action.get("action_id", "")
            try:
                ctx = json.loads(action.get("value") or "{}")
            except json.JSONDecodeError:
                ctx = {}
            org = default_org(handler.default_tenant)
            user = (payload.get("user") or {}).get("id", "")

            if aid in _OC_RESULT:                  # nút GHI KẾT QUẢ đàm phán → nuôi flywheel
                n = _record_deal_outcome(handler.service, org.id, ctx.get("c", ""), _OC_RESULT[aid])
                return {"replace_original": True,
                        "text": f"📊 Đã ghi kết quả cho {n} điều khoản — cảm ơn! (nuôi win-rate)"}

            rating = _FB_RATING.get(aid)
            if not rating:
                return {"ok": True}
            try:                                   # lỗi DB KHÔNG được làm 500 (Slack sẽ retry-storm)
                handler.service.record_feedback(Feedback(
                    id=uuid.uuid4().hex, org_id=org.id, kind=ctx.get("k", "lookup"),
                    ref=ctx.get("r", ""), rating=rating, note=f"slack:{user}",
                    created_at=datetime.now(timezone.utc).isoformat()))
            except Exception:  # noqa: BLE001 — feedback là phụ; vẫn ack để Slack không retry
                _log.exception("Không ghi được feedback từ Slack")
            # Thay tin gốc bằng xác nhận (replace_original) — ack <3s, không hammer LLM.
            return {"replace_original": True, "text": "✅ Cảm ơn phản hồi của bạn — đã ghi nhận."}

    if zalo_oa_secret:
        @router.post("/channels/zalo/webhook")
        async def zalo_webhook(request: Request, background: BackgroundTasks):
            body = await request.body()
            try:                                       # body do bên ngoài gửi (pre-auth) → parse an toàn, lỗi = 400
                raw = body.decode("utf-8")
                payload = json.loads(raw or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise HTTPException(status_code=400, detail="Body không hợp lệ.") from None
            if not _verify_zalo(zalo_app_id, raw, str(payload.get("timestamp", "")),
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
