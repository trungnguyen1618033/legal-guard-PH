"""Playbook công ty — đối chiếu hợp đồng với CHÍNH SÁCH cấp org. THUẦN domain (qua LLMPort judge),
KHÔNG import adapter. Dùng chung mọi kênh (Slack/Zalo/web/MCP) qua AnalysisService.

Mỗi chính sách active → 1 call judge (bounded theo SỐ CHÍNH SÁCH, không nhân theo số rủi ro) → điều khoản
nào vi phạm. BẢO THỦ (judge nói vi phạm rõ mới gắn). ISOLATED khỏi vòng agent → accuracy KHÔNG đổi.
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from legalguard.domain.ports import LLMPort

_log = logging.getLogger(__name__)

_SYS = "Bạn là trợ lý pháp lý. Kiểm hợp đồng có VI PHẠM chính sách công ty không. Chỉ trả JSON."
_PROMPT = """Chính sách công ty: "{rule}"

Các điều khoản trong hợp đồng:
{clauses}

Điều khoản nào (nếu có) VI PHẠM chính sách công ty trên? Trả JSON:
{{"violated": true/false, "clause": "tên điều khoản vi phạm, rỗng nếu không"}}
Không có vi phạm → {{"violated": false, "clause": ""}}."""


def _parse(raw: str) -> dict:
    """Bóc JSON object (chịu ```fence/prose). Rác → {}. THUẦN."""
    if not raw:
        return {}
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {}
    try:
        d = json.loads(m.group(0))
        return d if isinstance(d, dict) else {}
    except json.JSONDecodeError:
        return {}


def check_policy(risks: list, policies: list, judge: LLMPort | None) -> list[dict]:
    """Trả list vi phạm chính sách: [{policy_id, rule_text, severity, clause, kind}]. Offline/no-judge/
    không có chính sách → []. Mỗi policy 1 call judge (song song), bounded theo số chính sách."""
    if judge is None or not getattr(judge, "available", False) or not policies:
        return []
    actives = [p for p in policies if getattr(p, "active", True)]
    lines = [f"- {r.get('clause', '')}: {(r.get('evidence') or r.get('risk') or '')[:300]}"
             for r in risks if (r.get("clause") or r.get("evidence"))]
    if not actives or not lines:
        return []
    clauses = "\n".join(lines)

    def _check(p) -> dict | None:
        try:
            raw = judge.complete(_PROMPT.format(rule=p.rule_text, clauses=clauses), system=_SYS)
        except Exception:  # noqa: BLE001 — đối chiếu là phụ: lỗi → bỏ policy đó (không chặn analyze)
            _log.exception("check_policy lỗi judge (policy=%s)", getattr(p, "id", "?"))
            return None
        d = _parse(raw)
        if d.get("violated") is True:
            return {"policy_id": p.id, "rule_text": p.rule_text, "severity": p.severity,
                    "clause": str(d.get("clause") or "").strip(), "kind": p.kind}
        return None

    with ThreadPoolExecutor(max_workers=min(6, len(actives))) as pool:
        res = list(pool.map(_check, actives))
    return [v for v in res if v]
