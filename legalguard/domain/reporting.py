"""Render báo cáo rà soát hợp đồng (concierge deliverable) — logic thuần, song ngữ.

Tạo Markdown từ AnalysisResult theo `lang` ("en" mặc định | "vi"). Không I/O →
thuộc domain. Bản PDF (cần lib) sẽ là outbound adapter thêm sau, dùng lại Markdown này.
"""
from __future__ import annotations

from legalguard.domain.models import AnalysisResult
from legalguard.domain.tenants import Tenant

_SEV = {
    "en": {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟡 Low"},
    "vi": {"high": "🔴 Cao", "medium": "🟠 Trung bình", "low": "🟡 Thấp"},
}
_PRIO = {
    "en": {"must_fix": "🔴 Must keep", "negotiate": "🟠 Negotiate", "acceptable": "🟢 Acceptable"},
    "vi": {"must_fix": "🔴 Phải giữ", "negotiate": "🟠 Thương lượng", "acceptable": "🟢 Chấp nhận được"},
}

_L = {
    "en": {
        "title": "# Contract Review Report — Legal Guard",
        "market": "Market", "arb": "Domestic arbitration",
        "disclaimer": "> ⚠️ AI-assisted report. Recommendations require legal-expert review before use.",
        "summary": "## Summary", "none": "_(none)_", "strategy": "## Negotiation strategy",
        "prio": "Priority",
        "risks": "Risks found", "risk": "Risk", "tactic": "Suggested tactic",
        "reply": "Reply to partner (EN)", "winrate": "Historical win-rate",
        "legal_basis": "Legal basis",
        "no_risk": "_No clear risky clauses detected._",
        "review": "## ⚖️ Needs expert review", "reason": "Reason",
        "review_default": "high-severity clauses present", "todo": "_(pending)_",
    },
    "vi": {
        "title": "# Báo cáo Rà soát Hợp đồng — Legal Guard",
        "market": "Thị trường", "arb": "Trọng tài nội địa",
        "disclaimer": "> ⚠️ Báo cáo hỗ trợ bởi AI. Khuyến nghị cần chuyên gia pháp lý duyệt trước khi áp dụng.",
        "summary": "## Tóm tắt", "none": "_(không có)_", "strategy": "## Chiến lược đàm phán",
        "prio": "Ưu tiên",
        "risks": "Rủi ro phát hiện", "risk": "Rủi ro", "tactic": "Chiến thuật đề xuất",
        "reply": "Câu gửi đối tác (EN)", "winrate": "Tỉ lệ thắng lịch sử",
        "legal_basis": "Căn cứ pháp lý",
        "no_risk": "_Không phát hiện điều khoản rủi ro rõ ràng._",
        "review": "## ⚖️ Cần chuyên gia duyệt", "reason": "Lý do",
        "review_default": "có điều khoản rủi ro cao", "todo": "_(chưa có)_",
    },
}


def render_markdown_report(result: AnalysisResult, tenant: Tenant, lang: str = "en") -> str:
    t = _L.get(lang, _L["en"])
    sev = _SEV.get(lang, _SEV["en"])
    prio = _PRIO.get(lang, _PRIO["en"])
    fb = {f["clause"]: f for f in result.fallbacks}

    lines: list[str] = [
        t["title"], "",
        f"**{t['market']}:** {tenant.country} ({tenant.id}) · **{t['arb']}:** {tenant.arbitration_body}",
        "", t["disclaimer"], "",
        t["summary"], result.summary or t["none"], "",
    ]
    if result.strategy:
        lines += [t["strategy"], result.strategy, ""]
    lines += [f"## {t['risks']} ({len(result.risks)})"]
    if result.risks:
        for i, r in enumerate(result.risks, 1):
            f = fb.get(r["clause"], {})
            head = f"### {i}. {r['clause']} — {sev.get(r['severity'], r['severity'])}"
            if r.get("priority"):
                head += f" · {prio.get(r['priority'], r['priority'])}"
            lines += [
                head,
                f"- **{t['risk']}:** {r['risk']}",
                f"- **{t['tactic']}:** {f.get('suggestion', t['todo'])}",
            ]
            if f.get("english_reply"):
                lines += [f"- **{t['reply']}:** _{f['english_reply']}_"]
            if f.get("win_rate") is not None:
                lines += [f"- **{t['winrate']}:** {int(f['win_rate'] * 100)}%"]
            basis = r.get("legal_basis") or f.get("legal_basis")
            if basis:
                lines += [f"- **{t['legal_basis']}:** {basis}"]
            lines += [""]
    else:
        lines += [t["no_risk"], ""]

    if result.needs_human_review:
        reasons = "; ".join(result.review_reasons) or t["review_default"]
        lines += [t["review"], f"{t['reason']}: {reasons}", ""]

    if result.notes:
        lines += ["---", *[f"_{n}_" for n in result.notes]]

    return "\n".join(lines)
