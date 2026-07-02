"""Chế độ luật sư — HỒ SƠ KIỂM CHỨNG AI (audit trail) cho một case rà soát.

Vì sao (business-upgrade-plan đòn bẩy 2): rào cản adoption #1 của luật sư = trust/liability; chuẩn nghề
thế giới hội tụ "luật sư phải VERIFY mọi output AI + lưu bằng chứng đã verify" (ABA Formal Op. 512 7/2024;
Singapore MinLaw Guide 3/2026 human-in-the-loop). LĐLSVN chưa có hướng dẫn AI → bán sự yên tâm.

`compile_audit_trail` THUẦN (test offline): case (đã asdict) → memo markdown luật sư đính kèm hồ sơ để
CHỨNG MINH đã đối chiếu. Gồm: vân tay tài liệu (SHA-256, không lưu nội dung) · phát hiện AI + căn cứ ·
dấu vết agent (AI đã làm gì) · ô ký kiểm chứng của luật sư · tuyên bố "AI hỗ trợ, không thay luật sư".
"""
from __future__ import annotations

_SEV = {"high": "Cao", "medium": "Trung bình", "low": "Thấp"}
_STATUS = {"illegal": "⚖️ TRÁI LUẬT (có thể vô hiệu)", "unfavorable": "Bất lợi"}


def _cell(s: str, limit: int = 220) -> str:
    s = (s or "").replace("|", "\\|").replace("\n", " ").strip()
    return s[:limit]


def compile_audit_trail(case: dict, reviewer: str = "", note: str = "") -> str:
    """case (dict từ AnalysisCase) → memo markdown kiểm chứng. `reviewer`/`note`: điền sẵn nếu có."""
    risks = case.get("risks", []) or []
    trace = case.get("trace", []) or []
    lines: list[str] = []
    lines.append("# HỒ SƠ KIỂM CHỨNG AI — Rà soát hợp đồng")
    lines.append("")
    lines.append(f"- **Mã hồ sơ (case):** {case.get('id', '')}")
    lines.append(f"- **Thời điểm rà soát (UTC):** {case.get('created_at', '')}")
    lines.append(f"- **Tổ chức:** {case.get('org_id', '')} · **Quốc gia:** {case.get('tenant', '')}")
    lines.append("")

    lines.append("## 1. Tài liệu được rà soát (vân tay — nội dung KHÔNG lưu)")
    lines.append(f"- Tên tệp: `{case.get('source_name') or '(dán trực tiếp)'}`")
    lines.append(f"- SHA-256: `{case.get('source_sha256') or 'n/a'}` "
                 "— đối chiếu với văn bản gốc để xác nhận ĐÚNG tài liệu đã phân tích.")
    lines.append(f"- Kích thước: {case.get('source_bytes', 0)} bytes · "
                 f"{case.get('text_chars', 0)} ký tự (sau parse).")
    lines.append("")

    lines.append(f"## 2. Phát hiện của AI ({len(risks)} rủi ro) — cần luật sư đối chiếu bản gốc")
    if risks:
        lines.append("| # | Điều khoản | Rủi ro | Mức | Trạng thái | Căn cứ pháp lý |")
        lines.append("|---|---|---|---|---|---|")
        for i, r in enumerate(risks, 1):
            status = _STATUS.get(r.get("legal_status", ""), r.get("legal_status", "") or "—")
            # audit: ưu tiên violated_law (vi phạm cụ thể luật sư cần kiểm) rồi legal_basis; source cuối
            basis = r.get("violated_law") or r.get("legal_basis") or r.get("source") or "—"
            lines.append(f"| {i} | {_cell(r.get('clause', ''), 60)} | {_cell(r.get('risk', ''), 120)} "
                         f"| {_SEV.get(r.get('severity', ''), r.get('severity', '') or '—')} "
                         f"| {status} | {_cell(basis, 100)} |")
    else:
        lines.append("_(Không có rủi ro được gắn cờ.)_")
    lines.append("")

    lines.append(f"## 3. Dấu vết tác nhân AI ({len(trace)} bước) — AI đã làm gì")
    if trace:
        for s in trace:
            tool = s.get("tool", "?")
            obs = _cell(str(s.get("observation", "")), 160)
            lines.append(f"- `{tool}` → {obs}")
    else:
        lines.append("_(Không có dấu vết.)_")
    lines.append("")

    lines.append("## 4. Kiểm soát con người (human-in-the-loop)")
    flag = "CÓ — cần chuyên gia duyệt" if case.get("needs_human_review") else "Không bắt buộc"
    lines.append(f"- Hệ thống đánh dấu cần rà soát: **{flag}**")
    lines.append(f"- Luật sư kiểm chứng: **{reviewer or '________________'}**")
    lines.append("- Ngày kiểm chứng: ________________")
    lines.append(f"- Ghi chú/điều chỉnh của luật sư: {note or '________________'}")
    lines.append("")

    lines.append("## 5. Tuyên bố & trách nhiệm chuyên môn")
    lines.append("> Legal Guard là **công cụ hỗ trợ phân tích**, **không thay thế ý kiến pháp lý** của "
                 "luật sư. Kết quả trên do hệ thống AI tạo, có trích nguồn văn bản pháp luật còn hiệu "
                 "lực. Luật sư ký tên dưới đây xác nhận đã **ĐỐI CHIẾU** phát hiện của AI với văn bản "
                 "gốc và pháp luật hiện hành, và chịu trách nhiệm chuyên môn về ý kiến cuối cùng.")
    lines.append("")
    lines.append("Luật sư: ________________  Chữ ký: ________________  Ngày: ____/____/________")
    lines.append("")
    return "\n".join(lines)
