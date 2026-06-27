"""Phase C — gộp các điều khoản đã chọn thành BẢN GHI NHỚ SỬA ĐỔI (memo) cho luật sư.

Đầu vào: danh sách mục (risk/fallback đã chọn, có thể đã sửa tay). Đầu ra: memo có cấu trúc + Markdown
(bảng: Điều | Vấn đề | TRÁI LUẬT/bất-lợi | Căn cứ | Đề xuất sửa | Ưu tiên) — deliverable chính dán/gửi.
Thuần (test offline). Xuất .docx ở adapter `outbound/docx_export.py` (python-docx, opt-in).
"""
from __future__ import annotations

from dataclasses import dataclass, field

_STATUS_VI = {"illegal": "⚖️ TRÁI LUẬT", "unfavorable": "Bất lợi"}
_PRIORITY_VI = {"must_fix": "Phải sửa", "negotiate": "Thương lượng", "acceptable": "Chấp nhận được"}


@dataclass
class MemoRow:
    clause: str
    issue: str
    legal_status: str            # illegal | unfavorable
    violated_law: str = ""
    legal_basis: str = ""
    suggestion: str = ""         # đề xuất sửa (có thể luật sư sửa tay)
    priority: str = ""


@dataclass
class AmendmentMemo:
    rows: list[MemoRow] = field(default_factory=list)
    markdown: str = ""
    illegal_count: int = 0
    title: str = "BẢN GHI NHỚ SỬA ĐỔI HỢP ĐỒNG"


def compile_memo(items: list[dict], title: str = "", protected_party: str = "") -> AmendmentMemo:
    """Gộp mục đã chọn → memo (rows + Markdown). Mỗi item: {clause, issue/risk, legal_status, violated_law,
    legal_basis, suggestion, priority}. Sắp TRÁI LUẬT trước, rồi must_fix → negotiate → acceptable."""
    rows = [MemoRow(
        clause=(it.get("clause") or "").strip(),
        issue=(it.get("issue") or it.get("risk") or "").strip(),
        legal_status=it.get("legal_status", "unfavorable"),
        violated_law=(it.get("violated_law") or "").strip(),
        legal_basis=(it.get("legal_basis") or "").strip(),
        suggestion=(it.get("suggestion") or "").strip(),
        priority=it.get("priority", ""),
    ) for it in items if (it.get("clause") or "").strip()]
    _order = {"must_fix": 0, "negotiate": 1, "acceptable": 2}
    rows.sort(key=lambda r: (r.legal_status != "illegal", _order.get(r.priority, 3)))

    head = title.strip() or "BẢN GHI NHỚ SỬA ĐỔI HỢP ĐỒNG"
    lines = [f"# {head}"]
    if protected_party.strip():
        lines.append(f"_Bên được bảo vệ: **{protected_party.strip()}**_")
    lines += ["", "| # | Điều khoản | Vấn đề | Tính chất | Căn cứ pháp lý | Đề xuất sửa | Ưu tiên |",
              "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        nature = _STATUS_VI.get(r.legal_status, r.legal_status)
        if r.legal_status == "illegal" and r.violated_law:
            nature += f" ({r.violated_law})"
        basis = (r.legal_basis or "").replace("\n", " ").replace("|", "/")[:120]
        lines.append(f"| {i} | {_cell(r.clause)} | {_cell(r.issue)} | {nature} | {_cell(basis)} | "
                     f"{_cell(r.suggestion)} | {_PRIORITY_VI.get(r.priority, r.priority)} |")
    illegal = sum(r.legal_status == "illegal" for r in rows)
    lines += ["", f"_Tổng: {len(rows)} điều khoản — {illegal} TRÁI LUẬT (có thể vô hiệu), "
              f"{len(rows) - illegal} bất lợi._",
              "", "⚠️ _Bản ghi nhớ do AI hỗ trợ soạn — luật sư cần đối chiếu bản gốc trước khi sử dụng._"]
    return AmendmentMemo(rows=rows, markdown="\n".join(lines), illegal_count=illegal, title=head)


def _cell(s: str) -> str:
    """An toàn cho ô bảng Markdown: bỏ xuống dòng + thoát dấu '|'."""
    return (s or "").replace("\n", " ").replace("|", "/").strip() or "—"
