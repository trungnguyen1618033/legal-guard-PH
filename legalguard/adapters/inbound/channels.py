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
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from legalguard.domain.analysis import AnalysisService
from legalguard.domain.models import (
    AnalysisResult,
    Conversation,
    Feedback,
    NegotiationPosition,
    Outcome,
    SourceMeta,
)
from legalguard.domain.negotiation import NegotiationState, state_from_json, state_to_json
from legalguard.domain.presentation import Block  # tầng trình bày dùng chung
from legalguard.domain.presentation import md_to_slack as _md_to_slack
from legalguard.domain.presentation import strip_md, to_email_wrap, to_text
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


# TRÌNH BÀY LẠI (biến thể giọng/định dạng) — yêu cầu đổi CÁCH TRÌNH BÀY nội dung tư vấn ĐÃ có (không phải
# câu hỏi mới). Vd demo: "format lại giúp tôi". Cần intent RÕ để không nhầm câu hỏi/counter-offer.
_REFORMAT_RE = re.compile(
    r"(bản|dạng|gửi|viết thành|soạn( thành)?)\s+(email|thư|memo|ghi nhớ)|"
    r"format lại|trình bày lại|viết lại|soạn lại|rút gọn|gọn hơn|ngắn gọn hơn|súc tích hơn|"
    r"trang trọng hơn|mềm( mại)? hơn|nhẹ( nhàng)? hơn|lịch sự hơn|"
    r"\brewrite\b|\breformat\b|as an email|more formal|shorter|more concise", re.IGNORECASE)
_EMAIL_VARIANT_RE = re.compile(r"email|thư|thư điện tử", re.IGNORECASE)


def _is_reformat_request(text: str) -> bool:
    return bool(text and _REFORMAT_RE.search(text))


# XUẤT FILE — user muốn nhận KẾT QUẢ dưới dạng FILE (Word có comment/bản đối chiếu) thay vì đọc trong chat.
# Nguồn phản ánh THẬT: "thêm mục comment vào tệp này 4 ý…" → bot rà soát lại thay vì trả file. Bắt các cụm
# rõ ý "file/tệp/tải/xuất/comment vào". Neo ít nhất 1 danh từ file để không nuốt câu hỏi thường.
_FILE_EXPORT_RE = re.compile(
    r"(xuất|xuat|tải|tai|cho (tôi|mình)|gửi|gui|tạo|tao|kết xuất|download|export)\s+"
    r"(ra\s+)?(file|tệp|tep|bản\s+word|ban\s+word|word|docx|pdf|văn bản)|"
    r"(thêm|them|chèn|chen|gắn|gan|đưa|dua|bổ sung|bo sung).{0,20}"
    r"(comment|nhận xét|nhan xet|bình luận|binh luan|ghi chú|ghi chu).{0,12}"
    r"(vào|vao|lên|len|cho|trong)?\s*(file|tệp|tep|văn bản|hợp đồng|hop dong)|"
    r"file\s+(có\s+)?(comment|nhận xét)|"
    r"(có\s+)?comment\s+(vào\s+)?(file|tệp)|"
    r"bản\s+(word|docx|có\s+comment|có\s+nhận xét)|"
    r"add\s+comments?|comment(ed)?\s+(file|version|docx)", re.IGNORECASE)


def _wants_file_export(text: str) -> bool:
    return bool(text and _FILE_EXPORT_RE.search(text))


def _previous_review(conv) -> str:
    """Nội dung tư vấn GẦN NHẤT (tin assistant cuối) trong hội thoại — để trình bày lại. Rỗng nếu chưa có."""
    for m in reversed(conv.history or []):
        if m.get("role") == "assistant" and (m.get("content") or "").strip():
            return m["content"].strip()
    return ""


# Meta: người dùng xin HƯỚNG DẪN dùng / trợ giúp → trả bảng hướng dẫn + gỡ sự cố.
# Neo ^ (chỉ khớp khi tin BẮT ĐẦU bằng các cụm này) — tránh nuốt câu hỏi/HĐ chứa từ khóa giữa câu.
# KHÔNG dùng cụm quá generic ("có gì" → va "có gì trong HĐ rủi ro không?").
_HELP_RE = re.compile(
    r"^\s*(help|/help|trợ giúp|tro giup|hướng dẫn|huong dan|dùng thế nào|dùng sao|"
    r"how to use|bắt đầu thế nào|làm sao dùng|dùng công cụ)\b", re.IGNORECASE)
# "help me <làm X>" là YÊU CẦU HÀNH ĐỘNG (vd "help me review this contract"), KHÔNG phải xin hướng dẫn
# dùng bot → có động từ hành động rà soát/soạn thì loại khỏi help-docs.
_HELP_ACTION_RE = re.compile(
    r"\b(review|analyz|analyse|check|draft)\b|rà soát|ra soat|kiểm tra|phân tích|phan tich|soạn|xem giúp",
    re.IGNORECASE)


def _is_help_query(text: str) -> bool:
    t = (text or "").strip()
    if not t or not _HELP_RE.search(t):
        return False
    # "help me review this contract for X" → có tín hiệu HĐ hoặc động từ hành động → RÀ SOÁT, không phải help.
    low = t.lower()
    if any(s in low for s in _SIGNALS) or _HELP_ACTION_RE.search(low):
        return False
    return True


# Yêu cầu RÀ SOÁT CẢ hợp đồng (động từ rà soát + danh từ CẢ-văn-bản gần nhau). Phân biệt với followup về
# 1 điều khoản ("phân tích điều khoản thanh toán" — 'điều khoản' KHÔNG nằm nhóm danh từ cả-văn-bản).
_REVIEW_REQ_RE = re.compile(
    r"(review|analyze|analyse|rà soát|ra soat|phân tích|phan tich|kiểm tra|xem giúp|check)"
    r"[^.]{0,30}?(contract|hợp đồng|hop dong|hđ|file|tài liệu|document|văn bản)", re.IGNORECASE)


def _wants_whole_contract_review(text: str) -> bool:
    return bool(text and _REVIEW_REQ_RE.search(text))


_DEEP_REVIEW_RE = re.compile(
    r"(rà\s*(soát\s*)?kỹ|kỹ\s*(càng|lưỡng)|(phân tích|rà)\s*sâu|chuyên\s*sâu|chi\s*tiết|thật\s*kỹ"
    r"|\bdeep\b|\bthorough)", re.IGNORECASE)


def _wants_deep_review(text: str) -> bool:
    """User yêu cầu RÀ KỸ → deep (chấp nhận chờ ~2-15'); mặc định fast (nhanh, map-reduce cho HĐ dài)."""
    return bool(text and _DEEP_REVIEW_RE.search(text))


def _mentions(text: str, uid: str) -> bool:
    """text có mention user `uid` không — chịu cả 2 dạng Slack: `<@Uxxx>` và `<@Uxxx|tên hiển thị>`.
    Dùng cho MENTION GATE (dạng có `|tên` mà chỉ so substring `<@Uxxx>` sẽ TRƯỢT → bot im lặng oan)."""
    return bool(uid and re.search(rf"<@{re.escape(uid)}(\|[^>]*)?>", text or ""))


# Gợi ý 'bên mình bảo vệ' từ CHỈ DẪN chat ("...for Phu Quoc side", "bảo vệ Công ty X", "cho bên B").
# Gợi ý THÔ → LLM tinh thành TÊN ĐẦY ĐỦ khớp trong HĐ (analysis._classify_contract). Chỉ parse từ chỉ
# dẫn NGẮN / caption file (không từ HĐ dán dài — tránh nhiễu từ thân hợp đồng).
_PROTECT_HINT_RE = re.compile(
    r"\b(?:for|represent(?:ing)?|on behalf of|bảo vệ|đại diện cho|cho bên|phía)\s+"
    r"(?P<p>[\wÀ-ỹ .,&'\-]{2,60}?)\s*(?:\bside\b|\bparty\b|\bbên\b|[.,;\n]|$)", re.IGNORECASE)
_HINT_STOP = {"the", "this", "this contract", "me", "us", "them", "you", "my client", "client", "bên"}


def _extract_protected_hint(text: str) -> str:
    """Rút gợi ý bên được bảo vệ từ chỉ dẫn chat. Rỗng nếu không rõ (LLM sẽ tự chọn bên yếu thế)."""
    m = _PROTECT_HINT_RE.search(text or "")
    if not m:
        return ""
    p = m.group("p").strip(" .,-'\"")
    return "" if p.lower() in _HINT_STOP or len(p) < 2 else p
_MAX_TURNS = 12      # khi vượt → summarize lượt cũ vào context, giữ N lượt gần
_KEEP_TURNS = 6
_MAX_SKEW = 300      # giây — chống replay (tin nhắn quá cũ → từ chối)

_MAX_REPLY = 3900    # Slack hiển thị đẹp ≤~4000 ký tự / message
_ACK = ("Đã nhận hợp đồng. Hệ thống đang rà soát — thường mất vài phút (hợp đồng dài có thể lâu hơn). "
        "Kết quả sẽ được gửi vào đây.")
_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")   # tag @user trong text Slack

_log = logging.getLogger(__name__)


# Minh bạch AI — Luật AI 134/2025 (hiệu lực 1/3/2026): hệ thống AI tương tác trực tiếp với người phải
# cho người dùng BIẾT đang làm việc với máy. Marker này gắn vào MỌI reply chat (analyze/lookup/negotiate).
# Công bố AI dạng VĂN PHONG PHÁP LÝ (không icon) — dùng CHUNG cho mọi reply tư vấn (rà soát/tra cứu/đàm phán).
_AI_DISCLOSURE_LEGAL = ("\n\n(Nội dung trên do trí tuệ nhân tạo (AI) hỗ trợ soạn, mang tính tham khảo, "
                        "không thay thế tư vấn pháp lý chính thức của luật sư.)")


def _with_ai_disclosure(text: str) -> str:
    """Gắn công bố AI đúng MỘT lần ở cuối. Idempotent: bỏ MỌI lần đã có sẵn trong `text` (LLM tự thêm,
    hoặc nội dung dẫn lại từ reply trước) rồi mới nối → chống lặp câu công bố 2 lần (lỗi đã gặp)."""
    core = (text or "").replace(_AI_DISCLOSURE_LEGAL.strip(), "").rstrip()
    return core + _AI_DISCLOSURE_LEGAL

# Ngân sách ngữ cảnh thread — pack theo budget LUÔN-BẬT (thread ngắn tự vừa 100%, dài tự chọn lọc).
# ~24k ký tự ≈ 8k token tiếng Việt — model 128k context dư sức; đây là trần an toàn, không phải mục tiêu.
_THREAD_CTX_LIMIT = 24000
_CTX_TAIL_KEEP = 4                     # số tin CUỐI luôn giữ (mạch đối thoại ngay trước câu hỏi)
_GAP_MARK = "…(đã lược tin không liên quan)…"
# Stopword VN tối giản cho chấm liên quan LEXICAL (tầng fallback khi không có rank_fn / offline).
_CTX_STOP = frozenset(
    "và của là có cho với các những này kia thì mà được không anh chị em bạn mình nhé nhỉ ơi vậy đi rồi "
    "cũng như nếu khi đã sẽ về theo tại trong ngoài trên dưới".split())


def _ctx_tokens(s: str) -> set[str]:
    toks = re.findall(r"\w+", unicodedata.normalize("NFC", (s or "").lower()))
    return {t for t in toks if len(t) >= 3 and t not in _CTX_STOP}


def _relevance_scores(question: str, texts: list[str], rank_fn=None) -> list[float]:
    """Điểm LIÊN QUAN 3 TẦNG cho tin thread vs câu hỏi: (1) semantic cross-encoder (qwen3-rerank dùng
    chung với KB — bắt được paraphrase 'khoản đền bù' vs 'mức phạt'); (2) lexical token-overlap (tất
    định, offline — đủ tách chuyện-phiếm vs việc); (3) recency (tin mới điểm cao) khi câu hỏi không có
    token đặc trưng. Tầng trên lỗi/thiếu → rơi xuống tầng dưới, KHÔNG bao giờ chặn reply."""
    if rank_fn is not None and question.strip():
        try:
            s = rank_fn(question, texts)
            if s is not None and len(s) == len(texts):
                return [float(x) for x in s]
        except Exception:  # noqa: BLE001 — chấm điểm là phụ: lỗi API → fallback lexical
            _log.warning("rank_fn thread-context lỗi — fallback lexical", exc_info=True)
    qt = _ctx_tokens(question)
    if qt:
        lex = [float(len(qt & _ctx_tokens(t))) for t in texts]
        if any(lex):
            return lex
    return [float(i) for i in range(len(texts))]       # recency: index lớn = mới hơn = điểm cao


def _build_thread_context(msgs: list[dict], bot_uid: str, known: set[str] | None = None,
                          limit: int = _THREAD_CTX_LIMIT, *, question: str = "",
                          asker_id: str = "", names: dict[str, str] | None = None,
                          rank_fn=None) -> str:
    """Ngữ cảnh EPHEMERAL từ thread Slack — hỗ trợ thread NHIỀU NGƯỜI (M4): ai-nói-gì + chỉ giữ LIÊN QUAN.

    - NGƯỜI NÓI: tên thật (`names` từ users.info — danh tính là ngữ cảnh, ai trong thread cũng thấy tên
      nhau); không resolve được → nhãn ẩn danh 'Người A/B/C' theo thứ tự xuất hiện (tất định, test được).
      Bot mình = 'trợ lý'; bot khác = bỏ (nhiễu). CO-MENTION `<@U…>` giữ dạng '@tên' — không bóc mất
      referent ("hỏi ý @Người A" phải còn nguyên nghĩa).
    - Header 'Người tham gia: …' (+ '(người hỏi)' cho người mention bot) → LLM nắm cấu trúc đối thoại.
    - REDACT PII thân tin trước khi vào prompt; dedup `known` (khóa = bản BÓC-mention, khớp reply_ex);
      KHÔNG persist (không tạo kho PII thứ hai).
    - PACK THEO BUDGET luôn-bật: luôn giữ tin ĐẦU (chủ đề/HĐ gốc) + `_CTX_TAIL_KEEP` tin CUỐI; phần
      GIỮA chọn theo điểm liên quan (semantic→lexical→recency) tới khi đầy; chỗ bỏ chèn `_GAP_MARK`.
      Thread ngắn vừa budget → giữ 100% (không mất tin, không có 'cliff' hành vi)."""
    known = known or set()
    names = names or {}
    # 1) Nhãn speaker theo thứ tự xuất hiện (pre-pass tất định) — tên thật ưu tiên hơn nhãn ẩn danh.
    labels: dict[str, str] = {}
    for m in msgs:
        uid = m.get("user", "")
        if not uid or uid == bot_uid or m.get("bot_id"):
            continue
        if uid not in labels:
            n = len(labels)
            labels[uid] = names.get(uid) or ("Người " + (chr(65 + n) if n < 26 else str(n + 1)))

    def _sub_mention(mo: re.Match) -> str:
        u = mo.group(0)[2:-1]
        if u == bot_uid:
            return ""
        return "@" + (labels.get(u) or names.get(u) or "người khác")

    # 2) Làm sạch + redact + dedup. Khóa dedup = bản BÓC hết mention (khớp `known` reply_ex dựng từ
    # history + tin hiện tại); bản HIỂN THỊ giữ co-mention dạng @tên.
    rendered: list[str] = []
    present: dict[str, str] = {}       # uid → nhãn, CHỈ người thật sự có dòng hiển thị (cho header)
    for m in msgs:
        raw = (m.get("text") or "").strip()
        if not raw or (m.get("bot_id") and m.get("user") != bot_uid):
            continue
        key = redact(_MENTION_RE.sub("", raw).strip())[0]
        if not key or key in known:
            continue
        disp = redact(_MENTION_RE.sub(_sub_mention, raw).strip())[0]
        uid = m.get("user", "")
        if uid == bot_uid:
            spk = "trợ lý"
        else:
            spk = labels.get(uid, "người dùng")
            if uid:
                present.setdefault(uid, spk)
        rendered.append(f"{spk}: {disp}")
    if not rendered:
        return ""
    header = ""
    if present:                        # chỉ kê người CÓ tin hiển thị (không kê người chỉ mention/đã dedup)
        who = ", ".join(lb + (" (người hỏi)" if uid == asker_id else "")
                        for uid, lb in present.items())
        header = f"Người tham gia: {who}\n"
    # Budget trừ header + 1 marker (chốt chặn cùng vòng trim ở dưới → out LUÔN ≤ limit dù nhiều gap).
    budget = max(0, limit - len(header) - (len(_GAP_MARK) + 1))
    # LUÔN giữ tin ĐẦU (chủ đề/HĐ gốc) — cắt ngắn nếu riêng nó đã vượt budget (không bao giờ mất tin đầu).
    if len(rendered[0]) + 1 > budget:
        rendered[0] = rendered[0][:max(0, budget - 1)]
    keep: set[int] = {0}
    used = len(rendered[0]) + 1
    order: list[int] = []             # middle picks theo thứ tự thêm (điểm cao→thấp) để trim khi vượt

    def _try(i: int) -> bool:
        nonlocal used
        cost = len(rendered[i]) + 1
        if i not in keep and used + cost <= budget:
            keep.add(i)
            used += cost
            return True
        return False

    for i in range(len(rendered) - 1, max(0, len(rendered) - 1 - _CTX_TAIL_KEEP), -1):
        _try(i)                                                # đuôi K tin: mạch đối thoại
    middle = [i for i in range(len(rendered)) if i not in keep]
    if middle:                                                 # phần giữa: chọn theo LIÊN QUAN
        scores = _relevance_scores(question, [rendered[i] for i in middle], rank_fn)
        for _s, i in sorted(zip(scores, middle), key=lambda x: (-x[0], -x[1])):
            if _try(i):
                order.append(i)

    def _render(ks: set[int]) -> str:
        lines: list[str] = []
        prev = -1
        for i in sorted(ks):
            if prev != -1 and i > prev + 1:
                lines.append(_GAP_MARK)                        # đánh dấu chỗ đã lược cho LLM biết
            lines.append(rendered[i])
            prev = i
        return header + "\n".join(lines)

    out = _render(keep)
    while len(out) > limit and order:      # marker của các gap đẩy vượt limit → bỏ middle pick điểm thấp nhất
        keep.discard(order.pop())
        out = _render(keep)
    return out


def _review_head(result: AnalysisResult, has_findings: bool = True) -> str:
    """Câu MỞ ĐẦU reply rà soát (văn phong pháp lý như thư gửi khách). `has_findings=False` → câu kết luận
    KHÔNG có vấn đề (tránh mâu thuẫn 'đề xuất điều chỉnh' rồi 'không phát hiện gì')."""
    ctype = (result.contract_type or "").strip()
    client = (result.protected_party or "").strip()
    what = ctype or "hợp đồng"
    tail = f" nhằm bảo vệ quyền lợi của {client}" if client else ""
    if has_findings:
        return f"Sau khi rà soát {what}{tail}, chúng tôi đề xuất điều chỉnh một số nội dung sau:"
    return (f"Sau khi rà soát {what}{tail}, chúng tôi không phát hiện điều khoản rủi ro hay "
            "lỗi soạn thảo rõ ràng trong nội dung được cung cấp.")


def _risk_segments(result: AnalysisResult) -> list[tuple[int, int, str, str, bool]]:
    """(số hiển thị, index0, clause, ĐOẠN văn xuôi, cần-nút-'Đồng ý sửa') cho MỖI rủi ro — dùng CHUNG cho
    text reply (Zalo/web) và Slack blocks. VĂN XUÔI PHÁP LÝ ĐÁNH SỐ (kiểu thư gửi khách). NHÃN in đậm
    markdown `**…**` (Slack→`*…*` qua slackify; text/Zalo→bỏ dấu qua strip_md — không kênh nào lộ `**`):
      **(N) Tại điều khoản “<clause>”:** <rủi ro>[; dấu hiệu trái quy định tại <điều luật>…].
      **Nội dung hiện tại:** “<evidence>”.
      **Đề xuất sửa như sau:**  (rồi '**Tiếng Việt:**'/'**Tiếng Anh:**' khi có điều khoản mới song ngữ)
      **Căn cứ:** <bối cảnh + căn cứ pháp lý>.
    Nút 'Đồng ý sửa' CHỈ hiện khi CHƯA có điều khoản mới inline (tránh trùng — rủi ro illegal/must_fix đã auto)."""
    sugg = {f.get("clause", ""): (f.get("suggestion") or "").strip() for f in result.fallbacks}
    out: list[tuple[int, int, str, str, bool]] = []
    for idx, r in enumerate(result.risks):
        num = idx + 1
        risk_txt = (r.get("risk") or "").strip().rstrip(".")
        core = f"**({num}) Tại điều khoản “{r['clause']}”:** {risk_txt}."
        if r.get("legal_status") == "illegal":       # nêu trái luật bằng văn phong pháp lý (không icon)
            vl = (r.get("violated_law") or "").strip()
            core += f" Điều khoản này có dấu hiệu trái quy định{(' tại ' + vl) if vl else ' của pháp luật'}" \
                    "; phần vi phạm có thể bị tuyên vô hiệu."
        lines = [core]
        ev = (r.get("evidence") or "").strip()
        if ev:
            lines.append(f"**Nội dung hiện tại:** “{ev[:600]}”.")
        cc = r.get("counter_clause") or {}
        _disc = _AI_DISCLOSURE_LEGAL.strip()          # bỏ công bố AI nếu lọt vào nội dung (chống lặp 2 lần)
        vi = (cc.get("vi") or "").replace(_disc, "").strip()
        en = (cc.get("en") or "").replace(_disc, "").strip()
        has_inline = bool(vi)
        if has_inline:                               # rủi ro quan trọng: điều khoản mới dán-được-ngay (song ngữ)
            lines.append("**Đề xuất sửa như sau:**")
            lines.append(f"**Tiếng Việt:** {vi}")
            if en:
                lines.append(f"**Tiếng Anh:** {en}")
        else:                                        # rủi ro nhẹ: gợi ý sửa (bản dán-được qua nút 'Đồng ý sửa')
            s = sugg.get(r["clause"], "")
            if s:
                s = re.sub(r"^\s*đề xuất\s*:?\s*", "", s, flags=re.IGNORECASE)
                lines.append(f"**Đề xuất sửa:** {s.rstrip('.')}.")
        reason = (cc.get("rationale") or "").strip() or (r.get("legal_basis") or "").strip()
        if reason:
            lines.append(f"**Căn cứ:** {reason.rstrip('.')}.")
        out.append((num, idx, r["clause"], "\n".join(lines), not has_inline))
    return out


def _drafting_segments(result: AnalysisResult, start_num: int) -> list[tuple[int, str, str]]:
    """Lỗi soạn thảo / khác biệt VN–EN → ĐÁNH SỐ TIẾP sau rủi ro. Trả (num, đoạn văn xuôi, dclause-cho-nút).
    Có `drafting_issues` CÓ CẤU TRÚC → format THẺ nhãn-đậm (giống risk) + `dclause` để gắn nút 'Đồng ý sửa'
    (fix đã inline → nút = GHI NHẬN); không có cấu trúc → fallback chuỗi `drafting_notes` cũ, dclause="" (KHÔNG nút)."""
    out: list[tuple[int, str, str]] = []
    issues = result.drafting_issues or []
    if issues:
        for it in issues:
            num = start_num + len(out)
            loc = (it.get("location") or "").strip()
            issue = (it.get("issue") or "").strip().rstrip(".")
            head = (f"**({num}) Lỗi soạn thảo tại “{loc}”:** {issue}." if loc
                    else f"**({num}) Lỗi soạn thảo:** {issue}.")
            lines = [head]
            fv, fe = (it.get("fix_vi") or "").strip(), (it.get("fix_en") or "").strip()
            if fv or fe:
                lines.append("**Đề xuất sửa như sau:**")
                if fv:
                    lines.append(f"**Tiếng Việt:** {fv}")
                if fe:
                    lines.append(f"**Tiếng Anh:** {fe}")
            out.append((num, "\n".join(lines), loc or issue[:80]))
        return out
    for note in result.drafting_notes or []:              # fallback (không cấu trúc): chuỗi cũ, KHÔNG nút
        n = (note or "").strip()
        if n:
            num = start_num + len(out)
            out.append((num, f"({num}) {n}", ""))
    return out


_POLICY_HEAD = "Vi phạm chính sách công ty (playbook):"


def _policy_lines(result: AnalysisResult) -> list[str]:
    """Mục 'Vi phạm chính sách công ty' (playbook org) — TÁCH khỏi trái-luật-VN. Rỗng khi flag OFF/không vi phạm."""
    pv = getattr(result, "policy_violations", None) or []
    if not pv:
        return []
    out = [_POLICY_HEAD]
    for v in pv:
        clause = (v.get("clause") or "").strip()
        rule = (v.get("rule_text") or "").strip()
        out.append(f"- {clause + ': ' if clause else ''}trái chính sách \"{rule}\".")
    return out


_HUMAN_NOTE = "Các nội dung nêu trên cần luật sư đối chiếu bản gốc trước khi áp dụng."
_FAST_NOTE_MARK = "Bản RÀ NHANH"   # tiền tố (TEXT, không icon) note RÀ NHANH (analysis._finish_analyze) → surface đầu reply


def _review_doc(result: AnalysisResult, prefix: str = "", case_id: str = "") -> list[Block]:
    """NGUỒN CHUNG cho reply rà soát → serialize theo kênh (text/Slack). Mỗi Block = 1 khối: câu mở đầu ·
    mỗi rủi ro (kèm nút 'Đồng ý sửa' qua `action` — Slack dùng, text bỏ qua) · lỗi soạn thảo · chiến lược ·
    vi phạm playbook · ghi chú human-review. KHÔNG gồm công bố AI (caller tự gắn 1 lần). Nội dung rủi ro/
    drafting lấy từ `_risk_segments`/`_drafting_segments` → GIỮ NGUYÊN văn phong, chỉ đổi cách lắp ráp."""
    risk_segs = _risk_segments(result)
    draft_segs = _drafting_segments(result, len(risk_segs) + 1)     # đánh số TIẾP sau rủi ro
    has = bool(risk_segs or draft_segs)
    doc = [Block(prefix + _review_head(result, has_findings=has))]
    # Cảnh báo RÀ NHANH (nếu có) lên NGAY sau câu mở đầu — nguồn CHUNG result.notes (web/Next render notes;
    # Slack/text bỏ notes nên surface tại đây), để người dùng không nhầm fast với deep. Idempotent (1 note).
    for n in result.notes:
        if n.startswith(_FAST_NOTE_MARK):
            doc.append(Block(n))
            break
    for num, idx, _clause, seg, needs_draft in risk_segs:
        # Nút 'Đồng ý sửa' NHẤT QUÁN: chưa có điều khoản inline → SOẠN (draft); đã có → GHI NHẬN (confirm:1).
        action = None
        if case_id:
            val = {"c": case_id[:120], "i": idx} if needs_draft else {"c": case_id[:120], "i": idx, "confirm": 1}
            action = {"label": "Đồng ý sửa", "action_id": "amend_ok", "value": val}
        doc.append(Block(seg, key=f"lg_amend_{num}", action=action))
    for num, seg, dclause in draft_segs:              # lỗi soạn thảo — có cấu trúc → kèm nút 'Đồng ý sửa'
        action = None
        if case_id and dclause:                       # fix đã inline → nút = GHI NHẬN (ghi audit, không LLM)
            action = {"label": "Đồng ý sửa", "action_id": "amend_ok",
                      "value": {"c": case_id[:120], "confirm": 1, "dc": dclause[:80]}}
        doc.append(Block(seg, key=f"lg_draft_{num}", action=action))
    if result.strategy:
        doc.append(Block(result.strategy))
    if (pl := _policy_lines(result)):
        doc.append(Block("\n".join(pl)))
    if result.needs_human_review:
        doc.append(Block(_HUMAN_NOTE))
    return doc


def format_chat_reply(result: AnalysisResult, lang: str = "vi") -> str:
    """Trả lời rà soát HĐ (text/Zalo) — serialize `_review_doc` → văn xuôi pháp lý đánh số + công bố AI 1 lần.
    text/Zalo KHÔNG render markdown → strip_md gỡ dấu `**` nhãn (Slack giữ đậm qua _analysis_blocks slackify)."""
    out = _with_ai_disclosure(strip_md(to_text(_review_doc(result))))
    return out if len(out) <= _MAX_REPLY else out[:_MAX_REPLY] + "…"


def _context_from_result(result: AnalysisResult) -> str:
    risks = "; ".join(f"{r['clause']} ({r.get('priority', '')})" for r in result.risks)
    return f"Rủi ro: {risks or 'không'}. Chiến lược: {result.strategy[:400]}"


_NEGO_STATUS = {"continue": "Tiếp tục đàm phán", "close": "Nên chốt thỏa thuận",
                "walk_away": "Nên cân nhắc rút khỏi đàm phán (walk-away)"}


def format_negotiation_reply(r: dict, lang: str = "vi") -> str:
    """Định dạng 1 vòng đàm phán (negotiate_round) cho Slack — VĂN PHONG PHÁP LÝ, KHÔNG icon (đồng bộ với
    reply rà soát/tra cứu): trạng thái + đánh giá + chiến lược + sổ nhượng-bộ + câu trả lời gửi đối tác."""
    lines = [f"*Trạng thái:* {_NEGO_STATUS.get(r.get('status'), 'Tiếp tục đàm phán')}"]
    if r.get("assessment"):
        lines.append(f"*Đánh giá phản hồi đối tác:* {r['assessment']}")
    if r.get("strategy"):
        lines.append(f"*Chiến lược vòng tới:* {r['strategy']}")
    st = r.get("state") or {}
    if st.get("secured"):
        lines.append("*Đã chốt:* " + "; ".join(st["secured"]))
    if st.get("conceded"):
        lines.append("*Ta đã nhượng:* " + "; ".join(st["conceded"]))
    if r.get("walk_away_recommended"):
        lines.append("*Lưu ý:* điểm sống còn (red-line) bị chặn và ta có phương án thay thế (BATNA) — "
                     "nên cân nhắc rút khỏi đàm phán.")
    moves = r.get("next_moves") or []
    if moves:
        mv = []
        for m in moves:
            flag = " (gần điểm sống còn — cân nhắc)" if m.get("near_red_line") else ""
            ret = f" — đổi lấy: {m['in_return_for']}" if m.get("in_return_for") else ""
            mv.append(f"- Nhượng: {m.get('offer', '')}{ret}{flag}")
        lines.append("*Nước đi đề xuất (thang nhượng-bộ):*\n" + "\n".join(mv))
    reply = r.get("reply_vi") if lang == "vi" else (r.get("reply_en") or r.get("reply_vi"))
    if reply:
        lines.append(f"*Câu trả lời đề xuất gửi đối tác:*\n{reply}")
    if not r.get("grounded"):
        lines.append("(Khung sơ bộ — chưa cấu hình AI.)")
    out = _with_ai_disclosure("\n\n".join(lines))
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
                 store: ConversationStorePort, default_tenant: str = "VN",
                 rank_fn=None) -> None:
        self.service = service
        self.parser = parser
        self.store = store
        self.default_tenant = default_tenant
        # rank_fn (cross-encoder, dùng chung với KB retrieval): chấm điểm LIÊN QUAN tin-thread vs câu
        # hỏi khi pack ngữ cảnh thread nhiều người (M4b). None → fallback lexical/recency trong builder.
        self.rank_fn = rank_fn
        # Lock PER-CONVERSATION (in-process): tin cùng 1 hội thoại xử lý tuần tự → hết race
        # load→sửa→save (last-write-wins). Hội thoại khác nhau vẫn chạy SONG SONG. Đủ cho 1 instance;
        # đa-instance cần Redis lock (xem docs/internal/scale-concurrency.md).
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _conv_lock(self, conversation_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(conversation_id, threading.Lock())

    def reply_ex(self, conversation_id: str, text: str | None = None, attachment: bytes | None = None,
                 filename: str | None = None, lang: str = "vi",
                 thread_msgs: list[dict] | None = None, bot_uid: str = "",
                 asker_id: str = "", names: dict[str, str] | None = None,
                 in_thread: bool = False,
                 on_progress: "Callable[[dict], None] | None" = None) -> ChatReply:
        with self._conv_lock(conversation_id):     # tuần tự hóa theo hội thoại (chống race)
            conv = self.store.get(conversation_id) or Conversation(id=conversation_id)
            # PERSIST-FIRST: lưu tin user (đã REDACT PII) TRƯỚC khi xử lý → lỗi bất ngờ trong `_handle`
            # KHÔNG làm mất tin (dữ liệu audit/flywheel/debug, KHÔNG để hiển thị lại). `_handle` chỉ đọc
            # conv.context/nego_state — không đọc history → prepend an toàn. Chống DUP (retry / user tự
            # gửi lại y hệt): turn cuối đã là user + content giống → không append lần 2.
            user_msg = redact((text or "").strip())[0] or "(đã gửi tệp)"
            # Catch-up thread (mention giữa hội thoại / link thread): ngữ cảnh EPHEMERAL — dedup với
            # history đã lưu + tin hiện tại, KHÔNG persist (history vẫn chỉ chứa tin đi qua bot).
            thread_context = ""
            if thread_msgs:
                # known = nội dung đã có (history) + tin hiện tại. Thêm bản CHUẨN-HOÁ-GIỐNG-BUILDER
                # (bóc MỌI mention rồi redact) để dedup đúng cả khi tin hiện tại còn tag @người-khác.
                cur_norm = redact(_MENTION_RE.sub("", (text or "")).strip())[0]
                known = {m.get("content", "") for m in conv.history} | {user_msg, cur_norm}
                thread_context = _build_thread_context(
                    thread_msgs, bot_uid, known, question=(text or ""),
                    asker_id=asker_id, names=names, rank_fn=self.rank_fn)
            if not (conv.history and conv.history[-1].get("role") == "user"
                    and conv.history[-1].get("content") == user_msg):
                conv.add("user", user_msg)
                conv.updated_at = datetime.now(timezone.utc).isoformat()
                self.store.save(conv)               # save #1 — tin user đã BỀN (trước điểm có thể chết)
            res = self._handle(conv, text, attachment, filename, lang, thread_context, in_thread,
                               on_progress=on_progress)
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

    def _handle(self, conv: Conversation, text, attachment, filename, lang,
                thread_context: str = "", in_thread: bool = False,
                on_progress: "Callable[[dict], None] | None" = None) -> ChatReply:
        org = default_org(self.default_tenant)
        # Bảng help CHỈ khi CHƯA vào deal/thread. Đang rà soát (đã analyze → conv.context) hoặc giữa thread
        # thì "help me…"/"giúp…" là HỎI TIẾP, KHÔNG phải xin hướng dẫn dùng bot (user báo: upload file →
        # hỏi → hỏi lại thì bot trả HELP thay vì trả lời tiếp).
        if attachment is None and not conv.context and not thread_context and _is_help_query(text or ""):
            from legalguard.domain.help import format_help_text
            return ChatReply(format_help_text("slack"))
        if attachment is None and _is_trust_query(text or ""):     # meta-câu-hỏi về độ tin cậy → công bố
            from legalguard.domain.trust import format_trust_text
            return ChatReply(format_trust_text())
        # XUẤT FILE theo LỆNH CHAT (Word có comment): user muốn nhận KẾT QUẢ dạng file, KHÔNG phải rà soát lại
        # (phản ánh thật: "thêm comment vào tệp này" → bot rà soát lại). Có case rà soát gần nhất → trả file;
        # chưa có → hướng dẫn. Gate attachment None (kèm file = rà soát mới) + không phải câu hỏi.
        if attachment is None and _wants_file_export(text or "") and not _is_question(text or ""):
            if conv.last_case_id:
                return ChatReply("Đang tạo file Word có nhận xét (comment) cho bản rà soát gần nhất — "
                                 "sẽ gửi vào đây trong giây lát…", "export_doc", conv.last_case_id)
            if not (text and any(s in text.lower() for s in _SIGNALS)):   # không kèm HĐ để rà → hướng dẫn
                return ChatReply("Chưa có kết quả rà soát nào trong phiên để xuất file. Vui lòng gửi/đính "
                                 "kèm hợp đồng để tôi rà soát trước, rồi yêu cầu xuất file có nhận xét.")
        # Yêu cầu rà soát CẢ hợp đồng nhưng KHÔNG kèm file / KHÔNG dán nội dung → hướng dẫn ĐÍNH KÈM. CHỈ khi
        # CHƯA vào deal/thread (fresh): đang trong deal/thread → là follow-up ("re-review điều khoản X") →
        # để nhánh followup trả lời theo ngữ cảnh, KHÔNG chặn thành prompt. (File trong thread đã được
        # _process xử lý trước đó; tới đây nghĩa là không có file → fresh review-request mới hướng dẫn đính kèm.)
        if attachment is None and not conv.context and not thread_context \
                and len((text or "").strip()) < 200 and _wants_whole_contract_review(text or ""):
            return ChatReply(
                "Bạn muốn rà soát hợp đồng — vui lòng ĐÍNH KÈM lại file hợp đồng (.pdf/.docx/.txt/ảnh) "
                "hoặc DÁN nội dung hợp đồng vào tin nhắn để tôi rà soát và đề xuất sửa. (Nếu đã có kết quả "
                "rà soát trong thread, các nút 'Đồng ý sửa' ở tin đó vẫn dùng lại được.)")
        contract, source = None, None
        if attachment is not None:
            source = SourceMeta.of(attachment, filename or "file")   # audit: hash file gốc
            try:
                contract = self.parser.extract_text(attachment, filename or "file")
            except ValueError as exc:
                return ChatReply(f"Không đọc được file: {exc}")
        elif (text and not _is_question(text) and any(s in text.lower() for s in _SIGNALS)
              and not thread_context     # có ngữ cảnh thread → text là CHỈ DẪN về thread, KHÔNG phải HĐ mới
              and not (conv.context and (_is_counter_offer(text) or len(text.strip()) < 220))):
            contract = text                            # tín hiệu HĐ & KHÔNG phải câu hỏi → rà soát
            # ĐANG TRONG DEAL: phản hồi đối tác HOẶC tin NGẮN (<220 ký tự) → KHÔNG re-analyze (tin ngắn không
            # phải HĐ mới; để rơi xuống nhánh đàm phán). Đo từ test live: tin từ chối "chúng tôi không thể đổi…"
            # từng bị re-analyze oan vì chứa từ khóa HĐ ("trọng tài") → guardrail walk-away không chạy.
            # CÓ thread_context (mention giữa thread/link): chỉ dẫn kiểu "nhận xét điều khoản phía trên" có
            # từ khóa HĐ nhưng KHÔNG phải HĐ mới → để rơi xuống nhánh followup-theo-ngữ-cảnh (fix live test C).

        if contract and contract.strip():                 # → RÀ SOÁT
            # 'Bên mình bảo vệ' từ chỉ dẫn (caption file / tin ngắn) — KHÔNG parse từ HĐ dán dài (nhiễu).
            hint = _extract_protected_hint(text or "") if (attachment is not None
                                                           or len(text or "") < 300) else ""
            position = NegotiationPosition(protected_party=hint) if hint else None
            # Slack MẶC ĐỊNH fast (~7-30s kể cả HĐ dài nhờ map-reduce) — deep ~2-15' quá lâu cho chat.
            # Opt-in deep khi user yêu cầu rõ ("rà kỹ"/"sâu"/"deep"/"chi tiết") → chấp nhận chờ.
            a_mode = "deep" if _wants_deep_review(text or "") else "fast"
            try:
                result = self.service.analyze(contract, org, lang=lang, position=position,
                                              source=source, on_progress=on_progress, mode=a_mode)
            except (ValueError, LLMError) as exc:
                return ChatReply(f"Xin lỗi, chưa xử lý được: {exc}")
            conv.context = _context_from_result(result)    # nhớ deal đang bàn
            conv.last_case_id = result.case_id or ""        # → xuất file (comment/redline) theo lệnh chat sau này
            # Seed red-line đàm phán = các rủi ro must_fix (điểm sống còn KHÔNG nhượng) → vòng đàm phán sau
            # có bộ nhớ cấu trúc + guardrail walk-away tất định.
            red = [r["clause"] for r in result.risks if r.get("priority") == "must_fix" and r.get("clause")]
            conv.nego_state = state_to_json(NegotiationState(red_lines=red))
            return ChatReply(format_chat_reply(result, lang), "analysis", result.case_id or "", result)
        # TRÌNH BÀY LẠI (biến thể giọng): trong deal + yêu cầu đổi định dạng/giọng ("bản email", "rút gọn",
        # "trang trọng hơn"…) → viết lại nội dung tư vấn GẦN NHẤT, GIỮ NGUYÊN substance. (Demo: "format lại")
        if conv.context and _is_reformat_request(text or "") and _previous_review(conv):
            return ChatReply(self._reformat(conv, text or "", lang))
        # Trong deal: tin là PHẢN HỒI/COUNTER của đối tác → VÒNG ĐÀM PHÁN có cấu trúc (không phải Q&A chung).
        if conv.context and _is_counter_offer(text or ""):
            return ChatReply(self._negotiate(conv, text or "", lang, org.id, thread_context),
                             "negotiate", "")
        # MENTION TRONG THREAD → LUÔN trả lời THEO NGỮ CẢNH (kể cả câu giống tra cứu luật — user đã tham
        # chiếu nội dung cụ thể trong thread). Kích hoạt khi: có thread_context (đọc được tin trước), HOẶC
        # đang trong thread + có deal context (thread_context có thể bị dedup rỗng khi bot đã thấy các tin
        # đó — nhưng conv.context vẫn giữ deal → vẫn phải trả lời sát thread, không rơi xuống lookup KB chung).
        if thread_context or (in_thread and conv.context):
            return ChatReply(self._followup(conv, text or "", lang, thread_context))
        # Follow-up theo deal — TRỪ câu hỏi pháp lý CHUNG (→ ưu tiên lookup template+dẫn nguồn cho nhất quán).
        if conv.context and not _is_legal_lookup(text or ""):
            return ChatReply(self._followup(conv, text or "", lang, thread_context))
        if text and _looks_like_question(text):            # → TRA CỨU LUẬT có grounding (template + nguồn)
            answer, snippets = self.service.lookup(text, org, lang=lang)
            if snippets:                                   # hiện nguồn (dẫn điều/khoản) gọn dưới câu trả lời
                srcs = " · ".join(s.source for s in snippets[:3])
                answer = f"{answer}\n\nNguồn tham khảo: {srcs}"
            return ChatReply(_with_ai_disclosure(answer), "lookup", text)   # công bố AI văn phong pháp lý (không icon)
        if conv.context:                                   # có deal, không phải câu hỏi → follow-up
            return ChatReply(self._followup(conv, text or "", lang))
        return ChatReply("Gửi giúp em nội dung điều khoản / file hợp đồng để rà soát, "
                         "hoặc đặt câu hỏi pháp lý nhé.")

    def _reformat(self, conv: Conversation, request: str, lang: str) -> str:
        """Biến thể GIỌNG/ĐỊNH DẠNG cho nội dung tư vấn GẦN NHẤT. 'email/thư' → bọc THƯ trang trọng TẤT ĐỊNH
        (giữ 100% substance, không LLM). Giọng khác (rút gọn/mềm hơn…) → model NHANH viết lại, prompt CẤM
        đổi số liệu/điều luật/đề xuất. Công bố AI 1 lần. Lỗi/offline → trả nguyên bản (không mất nội dung)."""
        prev = _previous_review(conv)
        if not prev:
            return "Chưa có nội dung tư vấn nào trong hội thoại để trình bày lại."
        if _EMAIL_VARIANT_RE.search(request):        # deterministic — an toàn substance tuyệt đối
            return _with_ai_disclosure(to_email_wrap(prev))
        llm = self.service.judge if self.service.judge.available else self.service.reasoner
        if not llm.available:                        # offline → không viết lại được, trả nguyên bản
            return _with_ai_disclosure(prev)
        tail = " Viết bằng tiếng Việt." if lang == "vi" else " Write in English."
        prompt = (
            "Dưới đây là NỘI DUNG TƯ VẤN pháp lý đã soạn. Hãy TRÌNH BÀY LẠI đúng theo yêu cầu của khách. "
            "TUYỆT ĐỐI GIỮ NGUYÊN mọi số liệu, tên điều luật, tên các bên, và đề xuất sửa (kể cả song ngữ "
            "Việt/Anh nếu có) — KHÔNG thêm/bớt nội dung pháp lý, CHỈ đổi GIỌNG VĂN và ĐỊNH DẠNG.\n"
            f"Yêu cầu của khách: {request}\n\nNội dung:\n{prev}" + tail)
        try:
            return _with_ai_disclosure(llm.complete(prompt))
        except LLMError:
            return _with_ai_disclosure(prev)         # lỗi → trả nguyên bản, không mất nội dung

    def _negotiate(self, conv: Conversation, partner_message: str, lang: str, org_id: str = "",
                   thread_context: str = "") -> str:
        """Vòng đàm phán đa phiên trên Slack: bối cảnh deal + SỔ nhượng-bộ + tin đối tác → round có cấu trúc.
        Sổ nhượng-bộ (`conv.nego_state`) mang qua các vòng → agent NHỚ đã nhượng/chốt gì (không 'quên' do
        context free-text cắt cụt) + guardrail walk-away theo red-line. org_id → win-rate flywheel cô lập org.
        `thread_context` (catch-up khi mention giữa thread) nối vào deal context — EPHEMERAL, không persist."""
        state = state_from_json(conv.nego_state)
        deal = conv.context + (f"\n\nDiễn biến trong thread (tham khảo):\n{thread_context}"
                               if thread_context else "")
        try:
            r = self.service.negotiate_round(deal, partner_message, position=None,
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

    def _followup(self, conv: Conversation, question: str, lang: str, thread_context: str = "") -> str:
        # BỎ turn cuối = câu hỏi HIỆN TẠI (persist-first đã append TRƯỚC _handle) — nếu không, câu hỏi
        # lặp 2 lần trong prompt (bản redact trong hist + bản raw ở "Câu hỏi tiếp"). Khôi phục hành vi
        # trước persist-first (khi ấy history CHƯA có turn hiện tại).
        hist = "\n".join(f"{m['role']}: {m['content']}" for m in conv.history[:-1][-6:])
        tail = ", tiếng Việt." if lang == "vi" else ", in English."
        tc = (f"Nội dung thread trước đó (tham khảo, do người dùng trao đổi trong kênh):\n"
              f"{thread_context}\n\n") if thread_context else ""
        prompt = (f"Bối cảnh rà soát hợp đồng:\n{conv.context}\n\n{tc}Lịch sử hội thoại:\n{hist}\n\n"
                  f"Câu hỏi tiếp của khách: {question}\nTrả lời CHUYÊN NGHIỆP, súc tích, đi thẳng vấn đề" + tail)
        try:
            return _with_ai_disclosure(self.service.reasoner.complete(prompt))   # công bố AI đồng bộ
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


_DOC_EXT = (".pdf", ".docx", ".doc", ".txt")     # tài liệu HĐ — ưu tiên
_IMG_EXT = (".png", ".jpg", ".jpeg")             # ảnh scan — chỉ dùng khi không có tài liệu


def _latest_contract_file(msgs: list[dict]) -> tuple[str | None, str | None]:
    """Tìm FILE hợp đồng GẦN NHẤT trong các tin thread (dùng khi user yêu cầu rà soát mà không đính kèm
    lại — file đã có sẵn trong thread). BỎ file do BOT đăng; ưu tiên TÀI LIỆU (.pdf/.docx/…) mới nhất,
    chỉ khi không có mới tới ẢNH scan (tránh vớ nhầm screenshot). Trả (url, tên) hoặc (None, None).
    `msgs` cần key `files` ([{url, name}]) do sender.fetch_thread cung cấp."""
    def _find(exts: tuple[str, ...]) -> tuple[str | None, str | None]:
        for m in reversed(msgs):
            if m.get("bot_id"):                  # bỏ file do bot đăng (điều khoản sửa, memo…)
                continue
            for f in (m.get("files") or []):
                name = (f.get("name") or "").lower()
                if f.get("url") and name.endswith(exts):
                    return f["url"], f.get("name", "file")
        return None, None

    url, name = _find(_DOC_EXT)
    return (url, name) if url else _find(_IMG_EXT)


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
        btn("Hữu ích", "fb_helpful", "primary"),
        btn("Chưa đúng", "fb_wrong", "danger"),
        btn("Còn thiếu", "fb_incomplete")]}]


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
        {"type": "button", "text": {"type": "plain_text", "text": "Thử lại", "emoji": False},
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


# Nút GHI KẾT QUẢ đàm phán CŨ (oc_*) — reply MỚI dùng _review_action_blocks (Chốt/Sửa lại). GIỮ map này
# cho TƯƠNG THÍCH NGƯỢC: tin phân tích đã gửi trước đây vẫn còn nút oc_* → handler interactions xử lý được
# (builder _outcome_blocks đã bỏ — không dựng nút oc_* mới nữa).
_OC_RESULT = {"oc_accepted": "accepted", "oc_partial": "partial", "oc_rejected": "rejected"}


# Nút QUYẾT ĐỊNH trên reply RÀ SOÁT — GỘP kết quả đàm phán + feedback thành 2 nút:
#   Chốt  → outcome=accepted + feedback=helpful  (đồng ý, chốt deal)
#   Sửa lại → outcome=rejected + feedback=wrong  (cần chỉnh, chưa ổn)
# value mang cả {k: kind, r: ref-feedback, c: case_id} (với reply phân tích, ref == case_id).
_RV_ACTION = {"rv_close": ("accepted", "helpful"), "rv_revise": ("rejected", "wrong")}


def _review_action_blocks(kind: str, ref: str) -> list[dict]:
    val = json.dumps({"k": kind, "r": ref[:300], "c": ref[:120]}, ensure_ascii=False)

    def btn(txt: str, aid: str, style: str | None = None) -> dict:
        b = {"type": "button", "text": {"type": "plain_text", "text": txt, "emoji": True},
             "action_id": aid, "value": val}
        if style:
            b["style"] = style
        return b

    els = [btn("Chốt", "rv_close", "primary"), btn("Sửa lại", "rv_revise", "danger")]
    if ref:                                    # có case_id → nút tải BẢN ĐỐI CHIẾU .docx (redline)
        els.append(btn("📄 Bản đối chiếu", "redline_dl"))
    return [{"type": "actions", "block_id": "lg_review", "elements": els}]


def _record_deal_outcome(service: AnalysisService, org_id: str, case_id: str, result: str) -> int:
    """Ghi Outcome cho MỌI điều khoản (fallback) của 1 case → nuôi win-rate. Trả số điều đã ghi (0 nếu
    không có case / sai org). Cô lập org để chống ghi chéo công ty."""
    if not case_id:
        return 0
    case = service.get_case(case_id)
    if case is None or getattr(case, "org_id", None) != org_id:
        return 0
    # Ghi theo clause của risks ∪ fallbacks (agent thỉnh thoảng bỏ fallback → vẫn nuôi win-rate theo risk).
    clauses = list(dict.fromkeys(
        c for c in ([r.get("clause", "") for r in (case.risks or [])]
                    + [f.get("clause", "") for f in (case.fallbacks or [])]) if c))
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


def _redline_items_from_case(case) -> list[dict]:
    """Dựng items cho bản đối chiếu từ case ĐÃ LƯU: mỗi rủi ro → cũ (evidence) + mới (counter_clause.vi/en
    hoặc suggestion fallback) + căn cứ. THUẦN (test offline)."""
    sugg = {f.get("clause", ""): (f.get("suggestion") or "") for f in (case.fallbacks or [])}
    items = []
    for r in (case.risks or []):
        cc = r.get("counter_clause") or {}
        items.append({"clause": r.get("clause", ""), "evidence": r.get("evidence", ""),
                      "vi": cc.get("vi") or sugg.get(r.get("clause", ""), ""), "en": cc.get("en", ""),
                      "rationale": cc.get("rationale") or r.get("legal_basis", ""),
                      "legal_status": r.get("legal_status", "unfavorable"),
                      "violated_law": r.get("violated_law", "")})
    return items


def _send_redline(service: AnalysisService, sender: ChatSenderPort, org_id: str, case_id: str,
                  send_to: str, thread_ts: str | None) -> None:
    """Chạy nền (nút 📄): nạp case (cô lập org) → dựng bản ĐỐI CHIẾU .docx → upload vào thread. Lỗi/không
    hỗ trợ → báo text (bản đối chiếu vẫn tải được trên web /app)."""
    try:
        _safe_send(sender, send_to, "Đang tạo bản đối chiếu (.docx), chờ giây lát…", thread_ts)  # phản hồi tức thì khi bấm
        case = service.get_case(case_id)
        if case is None or getattr(case, "org_id", None) != org_id:
            _safe_send(sender, send_to, "Không tìm thấy hồ sơ rà soát để tạo bản đối chiếu "
                       "(có thể đã hết hạn).", thread_ts)
            return
        items = _redline_items_from_case(case)
        if not items:
            _safe_send(sender, send_to, "Không có điều khoản để tạo bản đối chiếu.", thread_ts)
            return
        rl = service.compile_redline(items, protected_party=getattr(case, "protected_party", "") or "")
        from legalguard.adapters.outbound.docx_export import DocxUnavailable, redline_to_docx
        try:
            data = redline_to_docx(rl)
        except DocxUnavailable:
            _safe_send(sender, send_to, "Chưa bật xuất Word trên máy chủ (cần group export). "
                       "Bản đối chiếu vẫn tải được trên web /app.", thread_ts)
            return
        ok = sender.upload_file(send_to, "ban-doi-chieu-sua-doi.docx", data, thread_ts,
                                title="Bản đối chiếu sửa đổi",
                                comment="Bản đối chiếu sửa đổi — điều khoản cũ (gạch ngang) → đề xuất mới. "
                                        "Luật sư đối chiếu bản gốc trước khi áp dụng.")
        if not ok:
            _safe_send(sender, send_to, "Chưa gửi được file (kiểm tra scope files:write của bot). "
                       "Bản đối chiếu vẫn tải được trên web /app.", thread_ts)
    except Exception:  # noqa: BLE001 — task nền: lỗi không được làm sập
        _log.exception("Lỗi tạo bản đối chiếu (%s)", case_id)
        _safe_send(sender, send_to, "Xin lỗi, chưa tạo được bản đối chiếu. Vui lòng thử lại.", thread_ts)


def _comment_items_from_case(case) -> list[dict]:
    """Items cho FILE WORD CÓ COMMENT từ case đã lưu — như redline nhưng GIỮ text RỦI RO (nội dung comment).
    Mỗi rủi ro → đoạn trích (evidence) + rủi ro + căn cứ + đề xuất song ngữ. THUẦN (test offline)."""
    sugg = {f.get("clause", ""): (f.get("suggestion") or "") for f in (case.fallbacks or [])}
    items = []
    for r in (case.risks or []):
        cc = r.get("counter_clause") or {}
        items.append({"clause": r.get("clause", ""), "evidence": r.get("evidence", ""),
                      "risk": r.get("risk", ""),
                      "vi": cc.get("vi") or sugg.get(r.get("clause", ""), ""), "en": cc.get("en", ""),
                      "rationale": cc.get("rationale") or r.get("legal_basis", ""),
                      "legal_status": r.get("legal_status", "unfavorable"),
                      "violated_law": r.get("violated_law", "")})
    # LỖI SOẠN THẢO cũng vào file comment (đúng ngữ nghĩa 'chú thích mọi lỗi'): location→clause/evidence
    # (mỏ neo), issue→risk, fix_vi/fix_en→đề xuất. legal_status='unfavorable' (lỗi soạn thảo, không xếp trái luật).
    for it in (getattr(case, "drafting_issues", None) or []):
        loc = (it.get("location") or "").strip()
        issue = (it.get("issue") or "").strip()
        items.append({"clause": f"Lỗi soạn thảo{(' tại ' + loc) if loc else ''}",
                      "evidence": issue or loc, "risk": issue,
                      "vi": (it.get("fix_vi") or "").strip(), "en": (it.get("fix_en") or "").strip(),
                      "rationale": "Lỗi soạn thảo / khác biệt Việt–Anh",
                      "legal_status": "unfavorable", "violated_law": ""})
    return items


def _send_comment_doc(service: AnalysisService, sender: ChatSenderPort, org_id: str, case_id: str,
                      send_to: str, thread_ts: str | None) -> None:
    """Chạy nền (lệnh chat 'xuất file/thêm comment'): nạp case (cô lập org) → dựng FILE WORD CÓ COMMENT
    (mỗi điều khoản 1 bong bóng nhận xét) → upload vào thread. Lỗi/không hỗ trợ → báo text (web /app vẫn có)."""
    try:
        case = service.get_case(case_id)
        if case is None or getattr(case, "org_id", None) != org_id:
            _safe_send(sender, send_to, "Không tìm thấy hồ sơ rà soát để tạo file (có thể đã hết hạn). "
                       "Vui lòng gửi lại hợp đồng để rà soát.", thread_ts)
            return
        items = _comment_items_from_case(case)
        if not items:
            _safe_send(sender, send_to, "Bản rà soát không có điều khoản nào để gắn nhận xét.", thread_ts)
            return
        doc_data = {"items": items, "protected_party": getattr(case, "protected_party", "") or "",
                    "contract_type": getattr(case, "contract_type", "") or "",
                    "title": "HỢP ĐỒNG — BẢN RÀ SOÁT CÓ NHẬN XÉT"}
        from legalguard.adapters.outbound.docx_export import DocxUnavailable, comment_to_docx
        try:
            data = comment_to_docx(doc_data)
        except DocxUnavailable as exc:
            _safe_send(sender, send_to, f"Chưa tạo được file Word có comment ({exc}). "
                       "Bản đối chiếu/ghi nhớ vẫn tải được trên web /app.", thread_ts)
            return
        ok = sender.upload_file(send_to, "ra-soat-co-nhan-xet.docx", data, thread_ts,
                                title="Bản rà soát có nhận xét",
                                comment="File Word có nhận xét (comment) trên từng điều khoản — mở bằng "
                                        "Microsoft Word để xem. Luật sư đối chiếu bản gốc trước khi áp dụng.")
        if not ok:
            _safe_send(sender, send_to, "Chưa gửi được file (kiểm tra scope files:write của bot). "
                       "File vẫn tải được trên web /app.", thread_ts)
    except Exception:  # noqa: BLE001 — task nền: lỗi không được làm sập
        _log.exception("Lỗi tạo file có comment (%s)", case_id)
        _safe_send(sender, send_to, "Xin lỗi, chưa tạo được file có nhận xét. Vui lòng thử lại.", thread_ts)


# Nút "Đồng ý sửa" per-risk (Slack) — actions block DƯỚI section rủi ro (không accessory bên phải → chữ
# full-width). value mang {c: case_id, i: index0}; handler nạp lại case (đã BỀN) → draft_counter_clause. KHÔNG
# cần store in-process: case đã persist với risks+fallbacks (sống sót restart, không TTL — bền hơn _RetryStore).
def _block_to_slack(b: Block) -> list[dict]:
    """1 Block → 1 Slack section (chữ FULL-WIDTH) + (nếu có action) 1 `actions` block DƯỚI mang nút 'Đồng ý sửa'.
    Nút ĐẶT DƯỚI (không phải accessory bên phải) → chữ dùng trọn chiều rộng, dễ đọc văn bản pháp lý DÀI và
    đồng nhất với block không nút (chiến lược/must-fix). `key`→block_id."""
    sec: dict = {"type": "section", "text": {"type": "mrkdwn", "text": b.clean()[:2900]}}
    if b.key:
        sec["block_id"] = b.key
    if not b.action:
        return [sec]
    act: dict = {"type": "actions", "elements": [{
        "type": "button", "text": {"type": "plain_text", "text": b.action["label"], "emoji": False},
        "action_id": b.action["action_id"],
        "value": json.dumps(b.action["value"], ensure_ascii=False)}]}
    if b.key:
        act["block_id"] = f"{b.key}_act"        # block_id riêng (Slack yêu cầu duy nhất)
    return [sec, act]


def _post_response_url(response_url: str, body: dict) -> None:
    """Cập nhật TIN GỐC của interaction qua `response_url` — cách TIN CẬY cho tin có `blocks` (trả blocks
    TRỰC TIẾP trong HTTP response hay bị Slack BỎ QUA, chỉ nhận text). Best-effort, nuốt lỗi (cập nhật UI phụ)."""
    if not response_url:
        return
    try:
        import httpx
        httpx.post(response_url, json=body, timeout=10)
    except Exception:  # noqa: BLE001 — cập nhật UI là phụ, lỗi không làm hỏng luồng chính
        _log.exception("POST response_url lỗi")


async def _slack_update_msg(payload: dict, body: dict) -> dict:
    """Cập nhật TIN GỐC của interaction. Trả `replace_original` TRỰC TIẾP trong HTTP response hay bị Slack
    BỎ QUA (đo thực tế workspace này — cả text lẫn blocks) → POST qua `response_url`. AWAIT NGAY trong request
    (run_in_threadpool — POST sync chạy off-event-loop) để Slack nhận lệnh đổi ~cùng lúc ack, KHÔNG đợi bg
    lên lịch sau response (bớt độ trễ). Thiếu response_url → fallback trả trực tiếp. `body` = text/blocks…"""
    upd = {"replace_original": True, **body}
    resp_url = payload.get("response_url", "")
    if resp_url:
        await run_in_threadpool(_post_response_url, resp_url, upd)
        return {"ok": True}
    return upd


def _mark_button_agreed(blocks: list, clicked_block_id: str) -> list | None:
    """Sau khi bấm 'Đồng ý sửa': thay actions block ĐÃ BẤM (khớp block_id) bằng SECTION nổi bật
    '✅ *Đã đồng ý sửa*' → user thấy RÕ mục nào đã đồng ý (✅ xanh, cỡ thường — không mờ như context),
    nút biến mất (không bấm trùng), trạng thái lưu trong tin. ✅ = icon-TRẠNG-THÁI (ngoại lệ có chủ đích cho
    quy tắc bỏ icon nội dung). THUẦN. Trả blocks mới; None nếu không khớp (caller giữ nguyên tin)."""
    if not clicked_block_id:
        return None
    out, hit = [], False
    for b in blocks or []:
        if b.get("type") == "actions" and b.get("block_id") == clicked_block_id:
            out.append({"type": "section", "block_id": clicked_block_id,
                        "text": {"type": "mrkdwn", "text": "✅ *Đã đồng ý sửa*"}})
            hit = True
        else:
            out.append(b)
    return out if hit else None


def _analysis_blocks(result: AnalysisResult, case_id: str, prefix: str = "") -> list[dict]:
    """Slack blocks reply rà soát HĐ — serialize `_review_doc` (nguồn chung với text): mỗi Block → 1 section
    (full-width) + nút 'Đồng ý sửa' ở actions block dưới, + công bố AI (context) + cap 50-block Slack."""
    blocks = [blk for b in _review_doc(result, prefix, case_id) for blk in _block_to_slack(b)]
    blocks.append({"type": "context",
                   "elements": [{"type": "mrkdwn", "text": _AI_DISCLOSURE_LEGAL.strip()}]})
    # Slack chặn 50 block/tin → HĐ nhiều rủi ro có thể vượt → chat.postMessage LỖI (im lặng, mất reply).
    # Chừa chỗ cho nút Chốt/Sửa lại (+1 ở _process): giữ ≤48, cắt phần giữa + ghi chú, GIỮ dòng công bố cuối.
    if len(blocks) > 48:
        disclosure = blocks[-1]
        blocks = blocks[:46] + [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": "…(rút gọn — còn mục chưa hiển thị; xem đầy đủ trên web /app)"}}, disclosure]
    return _slackify_blocks(blocks)          # **đậm**→*đậm* (strategy/segment LLM có thể dùng markdown chuẩn)


def _format_amend(clause: str, original: str, cc: dict) -> str:
    """Điều khoản sửa (song ngữ) sau 'Đồng ý sửa' — hiện NGUYÊN VĂN điều khoản CŨ (trích HĐ) → điều khoản
    MỚI, để luật sư biết chính xác thay đoạn nào. Văn phong pháp lý, không icon."""
    vi = (cc.get("vi") or "").strip()
    en = (cc.get("en") or "").strip()
    parts = [f"*Đề xuất sửa đổi:* {clause}"]
    if original and original.strip() and original.strip() != clause.strip():
        parts += ["", "*Điều khoản hiện tại (trích hợp đồng):*", original.strip()]
    parts += ["", "*Điều khoản đề xuất (Tiếng Việt):*", vi or "(chưa soạn được)"]
    if en:
        parts += ["", "*Suggested clause (English):*", en]
    if not cc.get("grounded", True):
        parts.append("\n(Bản khung sơ bộ — cần luật sư hoàn thiện trước khi áp dụng.)")
    return _with_ai_disclosure("\n".join(parts))


def _record_agreed_fix(service: AnalysisService, org_id: str, case_id: str, clause: str) -> None:
    """Ghi EVENT 'đã đồng ý sửa' (audit + tín hiệu risk-hợp-lệ). result='agreed_fix' — KHÔNG lọt win-rate
    (win_rates chỉ tính accepted/partial/rejected) nên không pha loãng flywheel. Lỗi ghi → bỏ qua (phụ)."""
    try:
        service.record_outcome(Outcome(
            id=uuid.uuid4().hex, org_id=org_id, case_id=case_id, clause=clause,
            tactic="agreed_amendment", result="agreed_fix",
            created_at=datetime.now(timezone.utc).isoformat()))
    except Exception:  # noqa: BLE001 — ghi event là phụ, không chặn luồng chính
        _log.exception("Không ghi được event 'đồng ý sửa' (%s)", case_id)


def _confirm_drafting_fix(service: AnalysisService, sender: ChatSenderPort, org_id: str, case_id: str,
                          clause: str, send_to: str, thread_ts: str | None) -> None:
    """Nút 'Đồng ý sửa' cho LỖI SOẠN THẢO (đề xuất fix ĐÃ hiển thị inline) → chỉ ghi event agreed_fix +
    báo nhận. KHÔNG gọi LLM, KHÔNG cần nạp case (clause mang trong value nút; outcome cô lập theo org đã auth)."""
    try:
        _record_agreed_fix(service, org_id, case_id, clause)
        _safe_send(sender, send_to, f"Đã ghi nhận đồng ý sửa lỗi soạn thảo: {clause} "
                   "(đề xuất đã nêu ở phần rà soát trên).", thread_ts)
    except Exception:  # noqa: BLE001 — task nền: lỗi không được làm sập
        _log.exception("Lỗi ghi nhận sửa soạn thảo (%s)", case_id)
        _safe_send(sender, send_to, "Xin lỗi, chưa ghi nhận được. Vui lòng thử lại.", thread_ts)


def _confirm_amend(service: AnalysisService, sender: ChatSenderPort, org_id: str, case_id: str,
                   idx: int, send_to: str, thread_ts: str | None) -> None:
    """Nút 'Xác nhận áp dụng' — cho rủi ro ĐÃ có điều khoản mới INLINE trong reply. Chỉ GHI event
    agreed_fix (audit/flywheel) + báo nhận; KHÔNG gọi LLM soạn lại (điều khoản mới đã hiển thị sẵn)."""
    try:
        case = service.get_case(case_id)
        if case is None or getattr(case, "org_id", None) != org_id or idx is None or idx < 0:
            _safe_send(sender, send_to, "Không tìm thấy hồ sơ rà soát (có thể đã hết hạn).", thread_ts)
            return
        risks = case.risks or []
        if idx >= len(risks):
            _safe_send(sender, send_to, "Không xác định được điều khoản.", thread_ts)
            return
        clause = risks[idx].get("clause", "")
        _record_agreed_fix(service, org_id, case_id, clause)
        _safe_send(sender, send_to, f"Đã ghi nhận đồng ý sửa điều khoản: {clause} "
                   "(điều khoản đề xuất đã nêu trong phần rà soát ở trên).", thread_ts)
    except Exception:  # noqa: BLE001 — task nền: lỗi không được làm sập
        _log.exception("Lỗi xác nhận áp dụng (%s)", case_id)
        _safe_send(sender, send_to, "Xin lỗi, chưa ghi nhận được. Vui lòng thử lại.", thread_ts)


def _run_amend(service: AnalysisService, sender: ChatSenderPort, org_id: str, case_id: str,
               idx: int, send_to: str, thread_ts: str | None) -> None:
    """Chạy nền: nạp case (cô lập org) → soạn điều khoản sửa cho rủi ro thứ `idx` → gửi vào thread.
    Tách khỏi handler interactions (phải ack <3s); draft_counter_clause gọi LLM nên chậm.
    Dùng NGUYÊN VĂN `evidence` (đoạn trích HĐ) làm điều khoản gốc → LLM viết lại CHÍNH đoạn đó (cũ→mới
    đúng nghĩa); thiếu evidence → lùi về nhãn `clause`."""
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
        original = (r.get("evidence") or "").strip() or clause      # nguyên văn từ HĐ; thiếu → nhãn
        _record_agreed_fix(service, org_id, case_id, clause)         # audit + tín hiệu risk-hợp-lệ
        fb = next((f for f in (case.fallbacks or []) if f.get("clause") == clause), {})
        cc = service.draft_counter_clause(
            clause=original, risk=r.get("risk", ""), suggestion=fb.get("suggestion", ""),
            legal_basis=fb.get("legal_basis") or r.get("legal_basis", ""))
        _safe_send(sender, send_to, _md_to_slack(_format_amend(clause, original, cc)), thread_ts)
    except Exception:  # noqa: BLE001 — task nền: lỗi soạn không được làm sập, báo khách nhẹ nhàng
        _log.exception("Không soạn được điều khoản sửa (%s)", case_id)
        _safe_send(sender, send_to, "Xin lỗi, chưa soạn được điều khoản sửa. Vui lòng thử lại.", thread_ts)


def _slackify_blocks(blocks: list[dict]) -> list[dict]:
    """Chuyển markdown→Slack cho MỌI text mrkdwn trong block (section.text + context.elements)."""
    for b in blocks:
        t = b.get("text")
        if isinstance(t, dict) and t.get("type") == "mrkdwn":
            t["text"] = _md_to_slack(t["text"])
        for el in b.get("elements", []) if isinstance(b.get("elements"), list) else []:
            if isinstance(el, dict) and el.get("type") == "mrkdwn":
                el["text"] = _md_to_slack(el["text"])
    return blocks


def _mrkdwn_blocks(text: str, limit: int = 2900, max_blocks: int = 12) -> list[dict]:
    """Chia reply thành NHIỀU section block Slack (mỗi block ≤ limit; Slack chặn 3000 ký tự/section).
    Cắt ở ranh giới DÒNG để không vỡ chữ/cụt câu (reply HĐ nhiều rủi ro thường > 2900). Quá dài →
    giữ `max_blocks` block + ghi chú xem bản đầy đủ trên web."""
    text = _md_to_slack(text)                 # **đậm**→*đậm* + tiêu đề (Slack không render markdown chuẩn)
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


# Permalink Slack: https://<ws>.slack.com/archives/<CHANNEL>/p<16 số>[?thread_ts=<root>...]
# p1720512345678901 → ts 1720512345.678901 (chèn dấu chấm trước 6 số cuối). Event text có thể wrap
# link dạng <url> hoặc <url|label> — regex chặn ở khoảng trắng/>/| nên match cả trong wrap.
_PERMALINK_RE = re.compile(
    r"https://[\w.-]+\.slack\.com/archives/(?P<ch>[A-Z0-9]+)/p(?P<pts>\d{16})"
    r"(?:\?[^\s>|]*?thread_ts=(?P<root>\d+\.\d+)[^\s>|]*)?")


def _parse_permalink(text: str) -> tuple[str, str, str] | None:
    """Rút (channel, root_thread_ts, chuỗi-link-khớp) từ permalink Slack trong tin. None nếu không có.
    Link trỏ 1 reply trong thread (?thread_ts=) → root = thread_ts; link tin gốc → root = chính ts đó
    (conversations.replies với tin lẻ trả về đúng 1 tin — vẫn đúng)."""
    m = _PERMALINK_RE.search(text or "")
    if not m:
        return None
    ts = f"{m.group('pts')[:10]}.{m.group('pts')[10:]}"
    return m.group("ch"), m.group("root") or ts, m.group(0)


def _process(handler: ChatHandler, sender: ChatSenderPort, key: str, send_to: str,
             text: str, file_url: str | None, filename: str | None,
             thread_ts: str | None = None, max_bytes: int = 10 * 1024 * 1024,
             supports_buttons: bool = False, reply_prefix: str = "",
             thread_fetch: tuple[str, str] | None = None, thread_required: bool = False,
             bot_uid: str = "", asker_id: str = "", resolve_names: bool = False) -> None:
    """Chạy nền: tải file (nếu có) + [đọc thread ngữ cảnh] + analyze + gửi reply (webhook chỉ ack nhanh).

    `thread_fetch=(channel, root_ts)`: đọc toàn bộ thread làm NGỮ CẢNH (catch-up khi mention giữa hội
    thoại — M2, hoặc thread từ permalink — M3). `thread_required=True` (link do user dán): đọc không
    được → báo lỗi thân thiện thay vì trả lời thiếu ngữ cảnh. `resolve_names` (M4): tra tên hiển thị
    người nói/được-mention trong thread (users.info) → attribution ai-nói-gì; lỗi → nhãn ẩn danh."""
    # Đọc thread TRƯỚC khi giữ lock hội thoại (HTTP call — không chặn tin khác cùng thread).
    thread_msgs: list[dict] = []
    if thread_fetch is not None:
        try:
            thread_msgs = sender.fetch_thread(*thread_fetch)
        except Exception:  # noqa: BLE001 — ngữ cảnh là phụ: lỗi đọc → degrade (trừ khi bắt buộc)
            _log.exception("Không đọc được thread %s", thread_fetch)
        if thread_required and not thread_msgs:
            _safe_send(sender, send_to,
                       "Chưa đọc được thread được dẫn — có thể bot chưa ở trong kênh đó "
                       "(mời bot bằng /invite) hoặc thread không tồn tại.", thread_ts)
            return
    names: dict[str, str] = {}
    if thread_msgs and resolve_names:                # M4a: tên thật người nói + người được mention
        ids = {m.get("user", "") for m in thread_msgs if m.get("user")}
        for m in thread_msgs:                        # cả user được CO-MENTION trong text (chưa chắc đã nói)
            ids |= {t[2:-1] for t in _MENTION_RE.findall(m.get("text") or "")}
        ids.discard(bot_uid)
        ids.discard("")
        try:
            names = sender.resolve_names(sorted(ids))
        except Exception:  # noqa: BLE001 — tên là phụ: lỗi → builder dùng nhãn ẩn danh Người A/B/C
            _log.warning("resolve_names lỗi — dùng nhãn ẩn danh", exc_info=True)
    # Yêu cầu rà soát CẢ hợp đồng nhưng KHÔNG kèm file trực tiếp + KHÔNG dán nội dung (tin ngắn) → dùng
    # FILE HĐ GẦN NHẤT trong thread (user đã đính kèm ở tin trước). Tin DÀI = đã dán HĐ → analyze bản dán,
    # KHÔNG lấy file cũ trong thread. Không thấy file nào → _handle hướng dẫn đính kèm.
    if not file_url and thread_msgs and len((text or "").strip()) < 200 \
            and _wants_whole_contract_review(text or ""):
        turl, tfn = _latest_contract_file(thread_msgs)
        if turl:
            file_url, filename = turl, tfn
    # Ack ngay khi sắp PHÂN TÍCH HĐ (lâu ~vài phút). Câu hỏi tra cứu (lookup) nhanh → KHÔNG ack. Yêu cầu
    # rà soát mà KHÔNG có file (trực tiếp/thread) → sẽ hướng dẫn đính kèm → KHÔNG ack (tránh 'Đã nhận HĐ' sai).
    will_analyze = bool(file_url) or (
        bool(text) and not _is_question(text) and any(s in text.lower() for s in _SIGNALS)
        # chỉ BỎ ack cho yêu cầu rà soát NGẮN không file (→ hướng dẫn đính kèm); HĐ DÁN dài vẫn ack + analyze.
        and not (len((text or "").strip()) < 200 and _wants_whole_contract_review(text or "")))
    on_progress = None
    if will_analyze:
        ack_ts = _safe_send(sender, send_to, _ACK, thread_ts)
        # Heartbeat tiến triển (A1): cập nhật TẠI CHỖ ack (chat.update) khi agent flag thêm rủi ro. Chỉ khi
        # sender hỗ trợ update (Slack) + có ts ack. Callback optional → default None = 0 đổi hành vi/accuracy.
        if ack_ts and hasattr(sender, "update"):
            on_progress = _make_progress_cb(sender, send_to, ack_ts)
    elif text and _looks_like_question(text) and not (_wants_file_export(text) and not _is_question(text)):
        # lookup/follow-up cũng chậm (~30s) → ack để không "chờ im". BỎ ack CHỈ khi tin thật sự route sang
        # XUẤT FILE (điều kiện Y HỆT _handle: _wants_file_export AND not _is_question) — khi ấy đã có ack
        # "đang tạo file…". Câu HỎI chứa từ khóa file ("cho tôi file… ?") vẫn route lookup → GIỮ ack (không im).
        _safe_send(sender, send_to, "Đang tra cứu văn bản pháp luật, vui lòng chờ trong giây lát…", thread_ts)
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
        res = handler.reply_ex(key, text=text, attachment=attachment, filename=filename,
                               thread_msgs=thread_msgs, bot_uid=bot_uid,
                               asker_id=asker_id, names=names,
                               in_thread=thread_fetch is not None,
                               on_progress=on_progress)
        reply = (reply_prefix + res.text) if reply_prefix else res.text   # vd "🔄 (cập nhật…)" khi chạy lại từ tin sửa
        if res.kind == "export_doc" and res.ref:   # LỆNH CHAT xuất file: gửi ack + dựng Word có comment & upload
            _safe_send(sender, send_to, reply, thread_ts)   # ack "đang tạo file…"
            org = default_org(handler.default_tenant)
            _send_comment_doc(handler.service, sender, org.id, res.ref, send_to, thread_ts)
            return
        if supports_buttons and res.kind:          # gắn nút feedback (Slack) cho câu trả lời thật
            if res.kind == "analysis" and res.result is not None:
                # Reply rà soát: MỖI rủi ro 1 section + nút 'Đồng ý sửa' (→ soạn điều khoản sửa), rồi
                # 2 nút quyết định Chốt / Sửa lại (gộp kết quả đàm phán + feedback). prefix vd "🔄" khi chạy lại.
                blocks = _analysis_blocks(res.result, res.ref, reply_prefix)
                blocks += _review_action_blocks(res.kind, res.ref)
            else:
                # Chia reply thành nhiều block (không cụt ở 2900) rồi mới tới nút feedback.
                blocks = [*_mrkdwn_blocks(reply), *_feedback_blocks(res.kind, res.ref)]
    except Exception:  # noqa: BLE001 — task nền: lỗi bất ngờ → vẫn báo khách kèm nút 🔁, không sập im lặng
        _log.exception("Lỗi xử lý tin nhắn (%s)", key)
        _send_error_with_retry(sender, send_to, key,
                               (key, send_to, text, file_url, filename, thread_ts), thread_ts,
                               "Xin lỗi, có lỗi khi xử lý. Vui lòng thử lại.", supports_buttons)
        return
    # Slack + reply text THÔ (reformat/followup/help/trust/error — res.kind rỗng nên không build blocks):
    # vẫn phải qua presentation.md_to_slack, nếu không markdown `**đậm**` do LLM sinh sẽ RÒ ra Slack dạng
    # chữ (Slack chỉ render MỘT `*`). Các nhánh có blocks đã slackify sẵn; text field khi đó chỉ là fallback.
    if supports_buttons and blocks is None:
        reply = _md_to_slack(reply)
    _safe_send(sender, send_to, reply, thread_ts, blocks)


def _safe_send(sender: ChatSenderPort, send_to: str, text: str, thread_ts: str | None,
               blocks: list | None = None) -> str | None:
    try:
        return sender.send(send_to, text, thread_ts, blocks)   # ts (Slack) → cho phép chat.update heartbeat
    except Exception:  # noqa: BLE001 — gửi lỗi (token sai/channel sai) không làm sập task nền
        _log.exception("Không gửi được reply (%s)", send_to)
        return None


def _make_progress_cb(sender: ChatSenderPort, send_to: str, ack_ts: str):
    """Callback THROTTLE cập nhật ack "đang phân tích… đã tìm N rủi ro" (Slack chat.update). Chỉ update khi
    #rủi ro TĂNG và cách lần trước ≥8s (chống spam rate-limit); lỗi nuốt (tiến triển là phụ)."""
    state = {"n": 0, "t": 0.0}

    def _cb(ev: dict) -> None:
        n = int(ev.get("risks", 0) or 0)
        now = time.monotonic()
        if n <= state["n"] or now - state["t"] < 8:
            return
        state["n"], state["t"] = n, now
        try:
            # KHÔNG dùng '(tiếp tục)…' — sau khi xong, reply đầy đủ gửi ở tin MỚI, ack này ở lại; câu phải
            # đúng cả lúc đang chạy lẫn lúc đã xong (đã phát hiện N rủi ro — sự thật, không gây hiểu nhầm).
            sender.update(send_to, ack_ts, f"Đang rà soát hợp đồng… đã phát hiện {n} rủi ro.")
        except Exception:  # noqa: BLE001 — heartbeat phụ, không làm hỏng task nền
            _log.debug("chat.update heartbeat lỗi", exc_info=True)

    return _cb


def build_channels_router(handler: ChatHandler, *, slack_signing_secret: str = "",
                          zalo_oa_secret: str = "", zalo_app_id: str = "",
                          slack_sender: ChatSenderPort | None = None,
                          zalo_sender: ChatSenderPort | None = None,
                          max_upload_bytes: int = 10 * 1024 * 1024,
                          mention_only: bool = True,
                          resolve_names: bool = True) -> APIRouter:
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
                # MENTION GATE (đồng bộ nhánh tin mới): tin sửa phải CÓ mention bot (tag còn nguyên
                # trong text tin sửa) hoặc DM — không thì user đang sửa tin nói với người khác.
                if mention_only and event.get("channel_type") != "im" \
                        and not _mentions(new_text, bot_uid):
                    return {"ok": True}
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
                                        max_upload_bytes, True, "_(Cập nhật theo tin đã sửa)_\n")
                return {"ok": True}
            # Bỏ qua tin của bot (tránh vòng lặp tự trả lời) + các subtype không phải tin mới
            # (message_changed/deleted...). file_share = tin nhắn kèm file → vẫn xử lý.
            if event.get("bot_id") or (etype == "message"
                                       and event.get("subtype") not in (None, "file_share")):
                return {"ok": True}
            channel = event.get("channel", "")
            text = event.get("text", "")
            bot_uid = ((payload.get("authorizations") or [{}])[0]).get("user_id") or ""
            # MENTION GATE (TRƯỚC dedup): chỉ trả lời khi được GỌI ĐÍCH DANH (@bot) hoặc DM — không mention
            # = user đang nói với người khác → bot IM LẶNG tuyệt đối (không ack/log ồn). app_mention tự nó
            # là mention. bot_uid thiếu (hiếm) → không xác minh được → im lặng (strict, an toàn). Đặt TRƯỚC
            # dedup để event bị-gate KHÔNG chiếm slot dedup của cặp (message ⇄ app_mention) cùng ts — nếu
            # không, event message bị gate loại vẫn ăn slot khiến app_mention (qua gate) bị dedup oan.
            is_dm = event.get("channel_type") == "im"
            mentioned = etype == "app_mention" or _mentions(text, bot_uid)
            if mention_only and not (is_dm or mentioned):
                return {"ok": True}
            # Dedup theo (channel, ts) — KHÔNG dedup theo loại event: event `message` chắc chắn
            # mang `files`, còn `app_mention` không đảm bảo → event nào tới trước thì xử lý.
            ts = event.get("ts") or event.get("event_ts") or ""
            if ts and _seen_dup((channel, ts)):
                return {"ok": True}
            # Bóc tag @bot khỏi nội dung (user ID bot có sẵn trong payload `authorizations`).
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
            # M3 — mention + PERMALINK thread: đọc toàn bộ thread được dẫn làm ngữ cảnh. V1 chỉ cho
            # CÙNG kênh (quyền riêng tư: kênh khác bot có thể là member nhưng NGƯỜI HỎI thì không).
            thread_fetch: tuple[str, str] | None = None
            thread_required = False
            link = _parse_permalink(text)
            if link:
                l_ch, l_root, l_url = link
                if l_ch != channel:
                    if slack_sender and slack_sender.available:
                        background.add_task(_safe_send, slack_sender, channel,
                                            "Vì lý do quyền riêng tư, bot chỉ đọc được thread trong "
                                            "CÙNG kênh này. Vui lòng dùng link thread của kênh hiện tại.",
                                            thread_ts)
                    return {"ok": True}
                thread_fetch, thread_required = (l_ch, l_root), True
                # Bỏ link (kể cả dạng wrap <url|label>) khỏi câu hỏi; không còn gì → mặc định tóm tắt.
                text = re.sub(r"<" + re.escape(l_url) + r"(\|[^>]*)?>", " ", text)
                text = text.replace(l_url, " ").strip(" .,;:–—-")
                if not text:
                    text = "Tóm tắt nội dung thread được tham chiếu, nêu các điểm chính và việc cần làm."
            elif event.get("thread_ts") and event.get("thread_ts") != event.get("ts"):
                # M2 — mention GIỮA thread: catch-up các tin bot đã bỏ qua (do mention-gate) để trả lời
                # đúng ngữ cảnh; dedup/redact/budget ở _build_thread_context.
                thread_fetch = (channel, event["thread_ts"])
            if slack_sender and slack_sender.available:         # ack nhanh, xử lý nền + gửi reply
                url, fn = _slack_file(event)
                background.add_task(_process, handler, slack_sender, key, channel, text,
                                    url, fn, thread_ts, max_upload_bytes, True,
                                    thread_fetch=thread_fetch, thread_required=thread_required,
                                    bot_uid=bot_uid, asker_id=event.get("user", ""),
                                    resolve_names=resolve_names)
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
                    return await _slack_update_msg(payload,
                                             {"text": "Phiên thử lại đã hết hạn — vui lòng gửi lại tin nhắn."})
                conv_key, send_to, r_text, r_url, r_fn, r_thread = payload_r   # conv_key riêng với retry_id
                background.add_task(_process, handler, slack_sender, conv_key, send_to,
                                    r_text, r_url, r_fn, r_thread, max_upload_bytes, True)
                return await _slack_update_msg(payload,
                                         {"text": "Đang thử lại — kết quả sẽ được gửi vào thread…"})

            if aid == "amend_ok":                  # nút per-risk: soạn điều khoản sửa HOẶC xác nhận áp dụng
                if not (slack_sender and slack_sender.available):
                    return {"ok": True}
                container = payload.get("container") or {}
                msg = payload.get("message") or {}
                send_to = (payload.get("channel") or {}).get("id", "")
                thread_ts = container.get("thread_ts") or msg.get("thread_ts") or msg.get("ts")
                # Đổi nút '✅ Đã đồng ý sửa' NGAY: AWAIT cập nhật response_url TRONG request (immediate),
                # RỒI mới spawn việc chậm (soạn LLM/ghi DB) vào bg → nút đổi trước, không đợi LLM. Cập nhật qua
                # response_url (Slack bỏ qua `blocks` ở HTTP response trực tiếp trên workspace này).
                new_blocks = _mark_button_agreed(msg.get("blocks") or [], action.get("block_id", ""))
                resp = ({"ok": True} if new_blocks is None else
                        await _slack_update_msg(payload, {"text": "Đã đồng ý sửa", "blocks": new_blocks}))
                # Việc chậm (ghi DB / soạn điều khoản LLM) chạy SAU cập nhật nút.
                if ctx.get("dc"):                  # LỖI SOẠN THẢO (fix inline) → chỉ GHI NHẬN (clause trong value)
                    background.add_task(_confirm_drafting_fix, handler.service, slack_sender, org.id,
                                        ctx.get("c", ""), ctx.get("dc", ""), send_to, thread_ts)
                else:
                    # confirm=1: rủi ro ĐÃ có điều khoản mới inline → chỉ ghi event (nhanh); else → soạn (LLM).
                    task = _confirm_amend if ctx.get("confirm") else _run_amend
                    background.add_task(task, handler.service, slack_sender, org.id,
                                        ctx.get("c", ""), ctx.get("i", -1), send_to, thread_ts)
                return resp

            if aid == "redline_dl":                # nút 📄 Bản đối chiếu → dựng .docx + upload vào thread
                if not (slack_sender and slack_sender.available):
                    return {"ok": True}
                container = payload.get("container") or {}
                msg = payload.get("message") or {}
                send_to = (payload.get("channel") or {}).get("id", "")
                thread_ts = container.get("thread_ts") or msg.get("thread_ts") or msg.get("ts")
                background.add_task(_send_redline, handler.service, slack_sender, org.id,
                                    ctx.get("c", ""), send_to, thread_ts)
                return {"ok": True}

            if aid in _RV_ACTION:                  # nút QUYẾT ĐỊNH gộp: Chốt / Sửa lại
                result, rating = _RV_ACTION[aid]
                n = _record_deal_outcome(handler.service, org.id, ctx.get("c", ""), result)  # win-rate
                try:                               # + feedback golden-set (lỗi DB KHÔNG được làm 500)
                    handler.service.record_feedback(Feedback(
                        id=uuid.uuid4().hex, org_id=org.id, kind=ctx.get("k", "analysis"),
                        ref=ctx.get("r", ""), rating=rating, note=f"slack:{user}",
                        created_at=datetime.now(timezone.utc).isoformat()))
                except Exception:  # noqa: BLE001 — feedback là phụ; vẫn ack để Slack không retry
                    _log.exception("Không ghi được feedback từ Slack")
                msg = (f"Đã chốt — ghi nhận kết quả cho {n} điều khoản. Cảm ơn bạn."
                       if aid == "rv_close" else
                       "Đã ghi nhận: cần sửa lại. Cảm ơn phản hồi của bạn.")
                return await _slack_update_msg(payload, {"text": msg})

            if aid in _OC_RESULT:                  # (tương thích ngược) nút kết quả đàm phán tin CŨ → flywheel
                n = _record_deal_outcome(handler.service, org.id, ctx.get("c", ""), _OC_RESULT[aid])
                return await _slack_update_msg(payload,
                                         {"text": f"Đã ghi nhận kết quả cho {n} điều khoản. Cảm ơn bạn."})

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
            # Thay tin gốc bằng xác nhận (qua response_url — trực tiếp bị Slack bỏ qua) — ack <3s, không hammer LLM.
            return await _slack_update_msg(payload,
                                     {"text": "Đã ghi nhận phản hồi của bạn. Cảm ơn bạn."})

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
