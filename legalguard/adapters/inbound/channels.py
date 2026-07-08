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
    r"đồng ý|chấp nhận|từ chối|đề nghị|yêu cầu|giảm (còn|xuống)|tăng|nhượng|chốt|walk|counter|offer|%|"
    # Từ chối/kiên quyết/ngôi-thứ-nhất-đối-tác (đối tác giữ/chặn điểm — vẫn là vòng đàm phán, đo từ test live):
    r"chúng tôi|chúng tớ|phía (tôi|chúng tôi|bên)|không thể|không đổi|không (đồng ý|chấp nhận)|"
    r"khó chấp nhận|bắt buộc|kiên quyết|vẫn (giữ|muốn|cần)|giữ nguyên|"
    r"\b(we|our|cannot|can't|must|insist|refuse|decline|reject)\b",
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


# Meta: người dùng xin HƯỚNG DẪN dùng / trợ giúp → trả bảng hướng dẫn + gỡ sự cố.
# Neo ^ (chỉ khớp khi tin BẮT ĐẦU bằng các cụm này) — tránh nuốt câu hỏi/HĐ chứa từ khóa giữa câu.
# KHÔNG dùng cụm quá generic ("có gì" → va "có gì trong HĐ rủi ro không?").
_HELP_RE = re.compile(
    r"^\s*(help|/help|trợ giúp|tro giup|hướng dẫn|huong dan|dùng thế nào|dùng sao|"
    r"how to use|bắt đầu thế nào|làm sao dùng|dùng công cụ)\b", re.IGNORECASE)


def _is_help_query(text: str) -> bool:
    return bool(text and _HELP_RE.search(text.strip()))
_MAX_TURNS = 12      # khi vượt → summarize lượt cũ vào context, giữ N lượt gần
_KEEP_TURNS = 6
_MAX_SKEW = 300      # giây — chống replay (tin nhắn quá cũ → từ chối)

_MAX_REPLY = 3900    # Slack hiển thị đẹp ≤~4000 ký tự / message
_ACK = ("📥 Đã nhận! Em đang rà soát — thường mất vài phút (hợp đồng dài có thể lâu hơn). "
        "Kết quả sẽ trả vào đây.")
_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")   # tag @user trong text Slack

_log = logging.getLogger(__name__)


# Minh bạch AI — Luật AI 134/2025 (hiệu lực 1/3/2026): hệ thống AI tương tác trực tiếp với người phải
# cho người dùng BIẾT đang làm việc với máy. Marker này gắn vào MỌI reply chat (analyze/lookup/negotiate).
_AI_DISCLOSURE = "\n_(🤖 Trả lời bởi AI — hỗ trợ, không thay thế tư vấn luật chính thức.)_"


# Công bố AI dạng VĂN PHONG PHÁP LÝ (không icon) — cho reply rà soát HĐ gửi luật sư.
_AI_DISCLOSURE_LEGAL = ("\n\n(Nội dung trên do trí tuệ nhân tạo (AI) hỗ trợ soạn, mang tính tham khảo, "
                        "không thay thế tư vấn pháp lý chính thức của luật sư.)")


def _review_head(result: AnalysisResult) -> str:
    """Dòng ĐẦU reply rà soát: loại HĐ + khách hàng được bảo vệ (khi LLM xác định được)."""
    ctype = (result.contract_type or "").strip()
    client = (result.protected_party or "").strip()
    lead = "Sau đây là các rủi ro và đề xuất sửa đổi"
    if client:
        lead += f" có lợi cho khách hàng là {client}"
    return (f"Đây là {ctype}. " if ctype else "") + lead + ":"


def _risk_segments(result: AnalysisResult) -> list[tuple[int, int, str, str, bool]]:
    """(số hiển thị, index0, clause, đoạn văn pháp lý, có-đề-xuất-sửa) cho MỖI rủi ro — dùng CHUNG cho
    text reply (Zalo/web) và Slack blocks (nút 'Đồng ý sửa' per-risk). Văn phong luật sư, không icon."""
    sugg = {f.get("clause", ""): (f.get("suggestion") or "").strip() for f in result.fallbacks}
    out: list[tuple[int, int, str, str, bool]] = []
    for idx, r in enumerate(result.risks):
        num = idx + 1
        seg = f"({num}) {r['clause']}: {r['risk']}".rstrip(".") + "."
        if r.get("legal_status") == "illegal":       # nêu trái luật bằng văn phong pháp lý (không icon)
            vl = (r.get("violated_law") or "").strip()
            seg += f" Điều khoản này có dấu hiệu trái quy định{(' tại ' + vl) if vl else ' của pháp luật'}" \
                   "; phần vi phạm có thể bị tuyên vô hiệu."
        s = sugg.get(r["clause"], "")
        if s:
            seg += f" Đề xuất sửa đổi: {s.rstrip('.')}."
        out.append((num, idx, r["clause"], seg, bool(s)))
    return out


def format_chat_reply(result: AnalysisResult, lang: str = "vi") -> str:
    """Trả lời rà soát HĐ cho LUẬT SƯ — văn phong pháp lý, KHÔNG icon/màu/nhãn ưu tiên; rủi ro đánh số
    (1)(2)(3); dòng đầu nêu loại HĐ + khách hàng được bảo vệ (nếu LLM xác định được)."""
    head = _review_head(result)
    if not result.risks:
        return head + "\n\nKhông phát hiện điều khoản rủi ro rõ ràng trong nội dung được cung cấp." \
            + _AI_DISCLOSURE_LEGAL
    lines = [head, ""]
    lines += [seg for _num, _idx, _clause, seg, _has in _risk_segments(result)]
    if result.strategy:
        lines += ["", result.strategy]
    if result.needs_human_review:
        lines.append("Các nội dung nêu trên cần luật sư đối chiếu bản gốc trước khi áp dụng.")
    out = "\n".join(lines) + _AI_DISCLOSURE_LEGAL
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
    lines.append(_AI_DISCLOSURE.strip())
    out = "\n\n".join(lines)
    return out if len(out) <= _MAX_REPLY else out[:_MAX_REPLY] + "…"


@dataclass
class ChatReply:
    """Kết quả 1 lượt chat: text + ngữ cảnh feedback (kind/ref) để gắn nút trên Slack."""
    text: str
    kind: str = ""        # "" | analysis | lookup (rỗng = không gắn nút feedback)
    ref: str = ""         # case_id (analysis) hoặc câu hỏi (lookup)
    result: AnalysisResult | None = None   # kèm kết quả rà soát → dựng nút 'Đồng ý sửa' per-risk trên Slack


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
            # PERSIST-FIRST: lưu tin user (đã REDACT PII) TRƯỚC khi xử lý → lỗi bất ngờ trong `_handle`
            # KHÔNG làm mất tin (dữ liệu audit/flywheel/debug, KHÔNG để hiển thị lại). `_handle` chỉ đọc
            # conv.context/nego_state — không đọc history → prepend an toàn. Chống DUP (retry / user tự
            # gửi lại y hệt): turn cuối đã là user + content giống → không append lần 2.
            user_msg = redact((text or "").strip())[0] or "(đã gửi tệp)"
            if not (conv.history and conv.history[-1].get("role") == "user"
                    and conv.history[-1].get("content") == user_msg):
                conv.add("user", user_msg)
                conv.updated_at = datetime.now(timezone.utc).isoformat()
                self.store.save(conv)               # save #1 — tin user đã BỀN (trước điểm có thể chết)
            res = self._handle(conv, text, attachment, filename, lang)
            conv.add("assistant", res.text)
            self._summarize(conv)
            conv.updated_at = datetime.now(timezone.utc).isoformat()   # 'last active'
            self.store.save(conv)                   # save #2 — kèm assistant reply, như cũ
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
        if attachment is None and _is_help_query(text or ""):      # xin hướng dẫn / trợ giúp → bảng help
            from legalguard.domain.help import format_help_text
            return ChatReply(format_help_text("slack"))
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
              and not (conv.context and (_is_counter_offer(text) or len(text.strip()) < 220))):
            contract = text                            # tín hiệu HĐ & KHÔNG phải câu hỏi → rà soát
            # ĐANG TRONG DEAL: phản hồi đối tác HOẶC tin NGẮN (<220 ký tự) → KHÔNG re-analyze (tin ngắn không
            # phải HĐ mới; để rơi xuống nhánh đàm phán). Đo từ test live: tin từ chối "chúng tôi không thể đổi…"
            # từng bị re-analyze oan vì chứa từ khóa HĐ ("trọng tài") → guardrail walk-away không chạy.

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
            return ChatReply(format_chat_reply(result, lang), "analysis", result.case_id or "", result)
        # Trong deal: tin là PHẢN HỒI/COUNTER của đối tác → VÒNG ĐÀM PHÁN có cấu trúc (không phải Q&A chung).
        if conv.context and _is_counter_offer(text or ""):
            return ChatReply(self._negotiate(conv, text or "", lang, org.id), "negotiate", "")
        # Follow-up theo deal — TRỪ câu hỏi pháp lý CHUNG (→ ưu tiên lookup template+dẫn nguồn cho nhất quán).
        if conv.context and not _is_legal_lookup(text or ""):
            return ChatReply(self._followup(conv, text or "", lang))
        if text and _looks_like_question(text):            # → TRA CỨU LUẬT có grounding (template + nguồn)
            answer, snippets = self.service.lookup(text, org, lang=lang)
            if snippets:                                   # hiện nguồn (dẫn điều/khoản) gọn dưới câu trả lời
                srcs = " · ".join(s.source for s in snippets[:3])
                answer = f"{answer}\n\n📎 Nguồn: {srcs}"
            return ChatReply(answer + _AI_DISCLOSURE, "lookup", text)
        if conv.context:                                   # có deal, không phải câu hỏi → follow-up
            return ChatReply(self._followup(conv, text or "", lang))
        return ChatReply("Gửi giúp em nội dung điều khoản / file hợp đồng để rà soát, "
                         "hoặc đặt câu hỏi pháp lý nhé.")

    def _negotiate(self, conv: Conversation, partner_message: str, lang: str, org_id: str = "") -> str:
        """Vòng đàm phán đa phiên trên Slack: bối cảnh deal + SỔ nhượng-bộ + tin đối tác → round có cấu trúc.
        Sổ nhượng-bộ (`conv.nego_state`) mang qua các vòng → agent NHỚ đã nhượng/chốt gì (không 'quên' do
        context free-text cắt cụt) + guardrail walk-away theo red-line. org_id → win-rate flywheel cô lập org."""
        state = state_from_json(conv.nego_state)
        try:
            r = self.service.negotiate_round(conv.context, partner_message, position=None,
                                             state=state, lang=lang, org_id=org_id or None)
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
        # BỎ turn cuối = câu hỏi HIỆN TẠI (persist-first đã append TRƯỚC _handle) — nếu không, câu hỏi
        # lặp 2 lần trong prompt (bản redact trong hist + bản raw ở "Câu hỏi tiếp"). Khôi phục hành vi
        # trước persist-first (khi ấy history CHƯA có turn hiện tại).
        hist = "\n".join(f"{m['role']}: {m['content']}" for m in conv.history[:-1][-6:])
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


# RETRY khi lỗi xử lý (Slack): lưu payload GỐC in-process → nút 🔁 chỉ mang KEY (value ≤2000 ký tự).
# One-shot qua `pop` (chống double-click). Payload NGUYÊN VĂN chỉ sống trong RAM TTL 15' (KHÔNG ghi
# disk — history đã có bản redact bền, đây không phải kho PII thứ hai). In-process như `seen_events`;
# đa-instance cần Redis (cùng giới hạn dedup/rate-limit đã ghi nhận). Restart = mất payload → nút báo hết hạn.
_RETRY_TTL = 15 * 60
_RETRY_MAX = 200


class _RetryStore:
    # Lock: `put`/`pop` gọi từ NHIỀU thread (BackgroundTasks chạy threadpool). Không lock → prune iterate
    # dict trong khi thread khác mutate = RuntimeError "dict changed size" (đúng lúc bão lỗi cần nút nhất).
    def __init__(self) -> None:
        self._items: dict[str, tuple[float, tuple]] = {}
        self._lock = threading.Lock()

    def put(self, retry_id: str, payload: tuple) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._items) >= _RETRY_MAX:           # prune hết-hạn trước, rồi evict cũ nhất
                for k in [k for k, (t, _) in self._items.items() if now - t > _RETRY_TTL]:
                    self._items.pop(k, None)
                while len(self._items) >= _RETRY_MAX:
                    self._items.pop(next(iter(self._items)), None)
            self._items[retry_id] = (now, payload)

    def pop(self, retry_id: str) -> tuple | None:
        with self._lock:
            item = self._items.pop(retry_id, None)
        if item is None or time.monotonic() - item[0] > _RETRY_TTL:
            return None
        return item[1]


_retry_store = _RetryStore()


def _retry_blocks(retry_id: str) -> list[dict]:
    val = json.dumps({"k": retry_id}, ensure_ascii=False)   # retry_id = uuid ngắn, không cần cắt
    return [{"type": "actions", "block_id": "lg_retry", "elements": [
        {"type": "button", "text": {"type": "plain_text", "text": "🔁 Thử lại", "emoji": True},
         "action_id": "retry_run", "value": val, "style": "primary"}]}]


def _send_error_with_retry(sender: ChatSenderPort, send_to: str, conv_key: str, payload: tuple,
                           thread_ts: str | None, msg: str, supports_buttons: bool) -> None:
    """Gửi tin lỗi kèm nút 🔁 (Slack) — lưu payload gốc để chạy lại. Dùng cho MỌI lỗi retry-được
    (tải file lỗi tạm thời, lỗi xử lý). Không hỗ trợ nút (Zalo) → gửi text thường. CHỈ dùng cho lỗi
    TẠM THỜI (đáng thử lại), KHÔNG dùng cho lỗi user-cố-định (vd file quá lớn — thử lại vô ích).
    Mỗi lần lỗi = 1 retry_id RIÊNG (uuid) → 2 lỗi cùng thread không ghi đè nhau; payload mang conv_key."""
    blocks = None
    if supports_buttons:
        retry_id = uuid.uuid4().hex
        _retry_store.put(retry_id, payload)
        blocks = [*_mrkdwn_blocks(msg), *_retry_blocks(retry_id)]
    _safe_send(sender, send_to, msg, thread_ts, blocks)


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


# Nút "Đồng ý sửa" per-risk (Slack) — accessory trên section rủi ro. Bấm → soạn điều khoản sửa (cũ→mới).
# value mang {c: case_id, i: index0}; handler nạp lại case (đã BỀN) → draft_counter_clause. KHÔNG cần
# store in-process: case đã persist với risks+fallbacks (sống sót restart, không TTL — bền hơn _RetryStore).
def _analysis_blocks(result: AnalysisResult, case_id: str, prefix: str = "") -> list[dict]:
    """Slack blocks reply rà soát HĐ: MỖI rủi ro = 1 section + nút 'Đồng ý sửa' (chỉ khi CÓ đề xuất để
    đồng ý). Head/chiến lược/miễn trừ như text reply. Nhất quán với `format_chat_reply` qua `_risk_segments`."""
    head = prefix + _review_head(result)
    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": head[:2900]}}]
    if not result.risks:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
            "text": "Không phát hiện điều khoản rủi ro rõ ràng trong nội dung được cung cấp."}})
    for num, idx, _clause, seg, has_sugg in _risk_segments(result):
        sec: dict = {"type": "section", "block_id": f"lg_amend_{num}",
                     "text": {"type": "mrkdwn", "text": seg[:2900]}}
        if has_sugg and case_id:                     # có đề xuất + case đã lưu → nút soạn điều khoản sửa
            sec["accessory"] = {
                "type": "button", "text": {"type": "plain_text", "text": "Đồng ý sửa", "emoji": False},
                "action_id": "amend_ok",
                "value": json.dumps({"c": case_id[:120], "i": idx}, ensure_ascii=False)}
        blocks.append(sec)
    if result.strategy:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": result.strategy[:2900]}})
    if result.needs_human_review:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
            "text": "Các nội dung nêu trên cần luật sư đối chiếu bản gốc trước khi áp dụng."}})
    blocks.append({"type": "context",
                   "elements": [{"type": "mrkdwn", "text": _AI_DISCLOSURE_LEGAL.strip()}]})
    return blocks


def _format_amend(clause: str, cc: dict) -> str:
    """Điều khoản sửa (song ngữ) sau khi luật sư bấm 'Đồng ý sửa' — văn phong pháp lý, không icon."""
    vi = (cc.get("vi") or "").strip()
    en = (cc.get("en") or "").strip()
    parts = [f"Đề xuất sửa đổi điều khoản: {clause}", "",
             "Điều khoản đề xuất (Tiếng Việt):", vi or "(chưa soạn được)"]
    if en:
        parts += ["", "Suggested clause (English):", en]
    if not cc.get("grounded", True):
        parts.append("\n(Bản khung sơ bộ — cần luật sư hoàn thiện trước khi áp dụng.)")
    parts.append(_AI_DISCLOSURE_LEGAL.strip())
    return "\n".join(parts)


def _run_amend(service: AnalysisService, sender: ChatSenderPort, org_id: str, case_id: str,
               idx: int, send_to: str, thread_ts: str | None) -> None:
    """Chạy nền: nạp case (cô lập org) → soạn điều khoản sửa cho rủi ro thứ `idx` → gửi vào thread.
    Tách khỏi handler interactions (phải ack <3s); draft_counter_clause gọi LLM nên chậm."""
    try:
        case = service.get_case(case_id)
        if case is None or getattr(case, "org_id", None) != org_id or idx is None or idx < 0:
            _safe_send(sender, send_to, "Không tìm thấy hồ sơ rà soát để soạn điều khoản "
                       "(có thể đã hết hạn). Vui lòng gửi lại hợp đồng.", thread_ts)
            return
        risks = case.risks or []
        if idx >= len(risks):
            _safe_send(sender, send_to, "Không xác định được điều khoản cần sửa.", thread_ts)
            return
        r = risks[idx]
        clause = r.get("clause", "")
        fb = next((f for f in (case.fallbacks or []) if f.get("clause") == clause), {})
        cc = service.draft_counter_clause(
            clause=clause, risk=r.get("risk", ""), suggestion=fb.get("suggestion", ""),
            legal_basis=fb.get("legal_basis") or r.get("legal_basis", ""))
        _safe_send(sender, send_to, _format_amend(clause, cc), thread_ts)
    except Exception:  # noqa: BLE001 — task nền: lỗi soạn không được làm sập, báo khách nhẹ nhàng
        _log.exception("Không soạn được điều khoản sửa (%s)", case_id)
        _safe_send(sender, send_to, "Xin lỗi, chưa soạn được điều khoản sửa. Vui lòng thử lại.", thread_ts)


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
             supports_buttons: bool = False, reply_prefix: str = "") -> None:
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
        except Exception:  # noqa: BLE001 — tải file lỗi TẠM THỜI (mạng…) → nút 🔁 chạy lại, khỏi gửi lại
            _log.exception("Không tải được file đính kèm (%s)", key)
            _send_error_with_retry(sender, send_to, key,
                                   (key, send_to, text, file_url, filename, thread_ts), thread_ts,
                                   "Xin lỗi, không tải được file đính kèm. Vui lòng thử lại.",
                                   supports_buttons)
            return
        if attachment and len(attachment) > max_bytes:      # lỗi user CỐ ĐỊNH → KHÔNG nút (thử lại vô ích)
            _safe_send(sender, send_to,
                       f"File quá lớn (>{max_bytes // (1024 * 1024)}MB). "
                       "Vui lòng gửi bản gọn hơn.", thread_ts)
            return
    blocks = None
    try:
        res = handler.reply_ex(key, text=text, attachment=attachment, filename=filename)
        reply = (reply_prefix + res.text) if reply_prefix else res.text   # vd "🔄 (cập nhật…)" khi chạy lại từ tin sửa
        if supports_buttons and res.kind:          # gắn nút feedback (Slack) cho câu trả lời thật
            if res.kind == "analysis" and res.result is not None:
                # Reply rà soát: MỖI rủi ro 1 section + nút 'Đồng ý sửa' (→ soạn điều khoản sửa), rồi
                # nút feedback + ghi kết quả đàm phán (flywheel). prefix vd "🔄 (cập nhật…)" khi chạy lại.
                blocks = _analysis_blocks(res.result, res.ref, reply_prefix)
                blocks += _feedback_blocks(res.kind, res.ref)
                if res.ref:
                    blocks += _outcome_blocks(res.ref)
            else:
                # Chia reply thành nhiều block (không cụt ở 2900) rồi mới tới nút feedback.
                blocks = [*_mrkdwn_blocks(reply), *_feedback_blocks(res.kind, res.ref)]
    except Exception:  # noqa: BLE001 — task nền: lỗi bất ngờ → vẫn báo khách kèm nút 🔁, không sập im lặng
        _log.exception("Lỗi xử lý tin nhắn (%s)", key)
        _send_error_with_retry(sender, send_to, key,
                               (key, send_to, text, file_url, filename, thread_ts), thread_ts,
                               "Xin lỗi, có lỗi khi xử lý. Vui lòng thử lại.", supports_buttons)
        return
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

    def _seen_dup(dkey: tuple) -> bool:
        """True nếu event đã xử lý (dedup); else ghi nhận + prune. Dùng CHUNG nhánh message + edit
        (nếu prune chỉ ở 1 nhánh → nhánh kia làm seen_events phình vô hạn)."""
        if dkey in seen_events:
            return True
        seen_events[dkey] = time.monotonic()
        if len(seen_events) > 500:                      # prune entry cũ (>10 phút)
            cutoff = time.monotonic() - 600
            for k in [k for k, t in seen_events.items() if t < cutoff]:
                del seen_events[k]
        return False

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
            # SỬA TIN NHẮN → chạy lại CHỈ nếu là câu TRA CỨU (stateless). Đặt TRƯỚC guard bỏ-qua subtype.
            # KHÔNG chạy lại tin phân tích/đàm phán (re-run sẽ merge nego ledger lần 2 / lệch deal context).
            if etype == "message" and event.get("subtype") == "message_changed":
                inner = event.get("message") or {}
                prev = event.get("previous_message") or {}
                new_text = (inner.get("text") or "").strip()
                # Lọc noisy: bot sửa · rỗng · text KHÔNG đổi (Slack unfurl link cũng bắn message_changed).
                if inner.get("bot_id") or not new_text \
                        or new_text == (prev.get("text") or "").strip():
                    return {"ok": True}
                bot_uid = ((payload.get("authorizations") or [{}])[0]).get("user_id") or ""
                if bot_uid:
                    new_text = new_text.replace(f"<@{bot_uid}>", "").strip()
                if not _is_legal_lookup(new_text):        # chỉ câu tra cứu (không đụng deal state)
                    return {"ok": True}
                ch2 = event.get("channel", "")
                edit_ts = (inner.get("edited") or {}).get("ts") or event.get("event_ts") or ""
                if _seen_dup((ch2, inner.get("ts", ""), edit_ts)):   # khóa 3 phần (tin sửa GIỮ ts gốc)
                    return {"ok": True}
                th2 = inner.get("thread_ts") or inner.get("ts")
                if slack_sender and slack_sender.available:
                    background.add_task(_process, handler, slack_sender,
                                        f"slack:{ch2}:{th2}", ch2, new_text, None, None, th2,
                                        max_upload_bytes, True, "🔄 _(cập nhật theo tin đã sửa)_\n")
                return {"ok": True}
            # Bỏ qua tin của bot (tránh vòng lặp tự trả lời) + các subtype không phải tin mới
            # (message_changed/deleted...). file_share = tin nhắn kèm file → vẫn xử lý.
            if event.get("bot_id") or (etype == "message"
                                       and event.get("subtype") not in (None, "file_share")):
                return {"ok": True}
            channel = event.get("channel", "")
            # Dedup theo (channel, ts) — KHÔNG dedup theo loại event: event `message` chắc chắn
            # mang `files`, còn `app_mention` không đảm bảo → event nào tới trước thì xử lý.
            ts = event.get("ts") or event.get("event_ts") or ""
            if ts and _seen_dup((channel, ts)):
                return {"ok": True}
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
        async def slack_interactions(request: Request, background: BackgroundTasks):
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

            if aid == "retry_run":                 # nút 🔁 THỬ LẠI sau lỗi → chạy lại payload đã lưu
                payload_r = _retry_store.pop(ctx.get("k", ""))   # pop = one-shot (double-click lần 2 → hết hạn)
                if payload_r is None or not (slack_sender and slack_sender.available):
                    return {"replace_original": True,
                            "text": "⏳ Hết hạn thử lại — vui lòng gửi lại tin nhắn giúp mình."}
                conv_key, send_to, r_text, r_url, r_fn, r_thread = payload_r   # conv_key riêng với retry_id
                background.add_task(_process, handler, slack_sender, conv_key, send_to,
                                    r_text, r_url, r_fn, r_thread, max_upload_bytes, True)
                return {"replace_original": True, "text": "🔁 Đang thử lại — kết quả sẽ trả vào thread…"}

            if aid == "amend_ok":                  # nút 'Đồng ý sửa' per-risk → soạn điều khoản sửa (cũ→mới)
                if not (slack_sender and slack_sender.available):
                    return {"ok": True}
                container = payload.get("container") or {}
                msg = payload.get("message") or {}
                send_to = (payload.get("channel") or {}).get("id", "")
                thread_ts = container.get("thread_ts") or msg.get("thread_ts") or msg.get("ts")
                # Soạn = gọi LLM (chậm) → nền, gửi vào thread; ack rỗng ngay (giữ nút cho các rủi ro khác).
                background.add_task(_run_amend, handler.service, slack_sender, org.id,
                                    ctx.get("c", ""), ctx.get("i", -1), send_to, thread_ts)
                return {"ok": True}

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
