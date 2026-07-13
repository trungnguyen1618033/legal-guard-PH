"""Nghĩa vụ & hạn chót (giai đoạn SAU KÝ) — THUẦN domain, KHÔNG import adapter.

Trích nghĩa-vụ-có-mốc từ hợp đồng (qua `LLMPort`), quy mốc tương đối → ngày, lọc sắp-đến-hạn, và sinh
digest KÊNH-AGNOSTIC (text). Mọi kênh (Slack/Zalo/web/MCP) dùng chung qua `AnalysisService` — không lặp
logic theo kênh. Trích là bước ISOLATED khỏi vòng agent → KHÔNG ảnh hưởng accuracy phân tích.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta

from legalguard.domain.ports import LLMPort

_log = logging.getLogger(__name__)

_KINDS = {"payment", "delivery", "renewal", "termination_notice", "warranty", "other"}

_SYSTEM = ("Bạn là trợ lý pháp lý. Trích NGHĨA VỤ CÓ MỐC THỜI GIAN/HẠN từ hợp đồng. "
           "Chỉ trả JSON array, không giải thích.")

_PROMPT = """Liệt kê các NGHĨA VỤ CÓ MỐC THỜI GIAN/HẠN trong hợp đồng (thanh toán, giao hàng, gia hạn,
hạn báo chấm dứt, bảo hành…). CHỈ nghĩa vụ thực sự có yếu tố thời gian. Trả JSON array, mỗi phần tử:
{{"kind":"payment|delivery|renewal|termination_notice|warranty|other","description":"...",
"due_date":"YYYY-MM-DD nếu có ngày tuyệt đối, else rỗng",
"rule":"mốc tương đối nếu không có ngày, vd '30 ngày trước ngày hết hạn hợp đồng'",
"party":"bên chịu","consequence":"hệ quả nếu lỡ","source_clause":"trích điều khoản gốc ngắn"}}
Không có nghĩa vụ có mốc → trả [].

HỢP ĐỒNG:
{contract}"""


def _field(o, name: str):
    """Đọc field từ Obligation (object) HOẶC dict — cho digest/upcoming dùng được cả hai."""
    return o.get(name) if isinstance(o, dict) else getattr(o, name, None)


def _norm_date(s) -> str:
    s = str(s or "").strip()
    return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else ""


_REL_RE = re.compile(r"(\d+)\s*ngày\s*trước.*?(hết hạn|kết thúc|chấm dứt|gia hạn)", re.IGNORECASE)


def resolve_due_date(rule: str, *, contract_end: date | None) -> str:
    """Quy mốc TƯƠNG ĐỐI → ngày tuyệt đối khi đủ dữ kiện: 'N ngày trước ngày hết hạn' + contract_end →
    contract_end − N ngày. Thiếu dữ kiện → '' (nghĩa vụ vẫn hiện, chỉ KHÔNG đặt lịch nhắc). THUẦN."""
    if not rule or contract_end is None:
        return ""
    m = _REL_RE.search(rule)
    if not m:
        return ""
    return (contract_end - timedelta(days=int(m.group(1)))).isoformat()


def _parse_obligations(raw: str) -> list[dict]:
    """Bóc JSON array (chịu ```fence / prose quanh). Rác/không phải list → []. THUẦN, test offline."""
    if not raw:
        return []
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out: list[dict] = []
    for d in data if isinstance(data, list) else []:
        if not (isinstance(d, dict) and str(d.get("description") or "").strip()):
            continue
        kind = str(d.get("kind") or "other").strip()
        out.append({
            "kind": kind if kind in _KINDS else "other",
            "description": str(d.get("description") or "").strip(),
            "due_date": _norm_date(d.get("due_date")),
            "rule": str(d.get("rule") or "").strip(),
            "party": str(d.get("party") or "").strip(),
            "consequence": str(d.get("consequence") or "").strip(),
            "source_clause": str(d.get("source_clause") or "").strip(),
        })
    return out


def extract_obligations(reasoner: LLMPort, contract_text: str, *,
                        contract_end: date | None = None) -> list[dict]:
    """Trích nghĩa-vụ-có-mốc (1 call LLM) + quy mốc tương đối→ngày khi đủ dữ kiện. Offline/stub → [].
    Trả list[dict] (CHƯA gắn id/org/case — `AnalysisService` gắn). THUẦN với LLMPort (không import adapter)."""
    if reasoner is None or not getattr(reasoner, "available", False) or not (contract_text or "").strip():
        return []
    try:
        raw = reasoner.complete(_PROMPT.format(contract=contract_text[:12000]), system=_SYSTEM)
    except Exception:  # noqa: BLE001 — trích là phụ: lỗi LLM → [] (KHÔNG chặn analyze)
        _log.exception("extract_obligations lỗi LLM")
        return []
    items = _parse_obligations(raw)
    for it in items:
        if not it["due_date"] and it["rule"]:
            it["due_date"] = resolve_due_date(it["rule"], contract_end=contract_end)
    return items


def upcoming(obligations: list, today: date, within_days: int) -> list:
    """Lọc nghĩa vụ pending có due_date trong [today, today+within], sắp theo due_date tăng dần. THUẦN.
    Nghĩa vụ chưa có due_date bị bỏ khỏi NHẮC (vẫn nằm ở list đầy đủ)."""
    lim = today + timedelta(days=within_days)
    out = [o for o in obligations
           if (_field(o, "status") or "pending") == "pending"
           and _norm_date(_field(o, "due_date"))
           and today <= date.fromisoformat(_norm_date(_field(o, "due_date"))) <= lim]
    out.sort(key=lambda o: _norm_date(_field(o, "due_date")))
    return out


def format_obligation_digest(items: list, today: date) -> str:
    """Digest KÊNH-AGNOSTIC (text) — Slack/Zalo/web dùng chung. `items` đã được caller lọc. Rỗng → ''."""
    if not items:
        return ""
    lines = ["Nghĩa vụ & hạn chót sắp tới:"]
    for o in items:
        due = _norm_date(_field(o, "due_date"))
        desc = _field(o, "description") or "(nghĩa vụ)"
        cons = _field(o, "consequence") or ""
        when = f"còn {(date.fromisoformat(due) - today).days} ngày (hạn {due})" if due else "chưa xác định ngày"
        lines.append(f"- {desc} — {when}" + (f"; nếu lỡ: {cons}" if cons else ""))
    return "\n".join(lines)
