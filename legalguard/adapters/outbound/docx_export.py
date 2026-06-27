"""Xuất Bản ghi nhớ sửa đổi (Phase C) ra Word .docx — adapter opt-in (cần `python-docx`).

Tách khỏi domain (domain chỉ tạo memo thuần). `python-docx` ở group `export` → import LƯỜI; chưa cài →
`DocxUnavailable` để caller trả lỗi rõ (markdown vẫn dùng được). `memo_to_docx(memo_dict) -> bytes`.
"""
from __future__ import annotations

import io


class DocxUnavailable(RuntimeError):
    """python-docx chưa được cài (group `export`)."""


def memo_to_docx(memo: dict) -> bytes:
    """memo (dict từ `AnalysisService.compile_memo`) → bytes .docx. Bảng: Điều|Vấn đề|Tính chất|Căn cứ|
    Đề xuất|Ưu tiên. Raise DocxUnavailable nếu thiếu lib."""
    try:
        from docx import Document
    except ImportError as exc:  # noqa: TRY003
        raise DocxUnavailable("Cần cài: uv sync --group export (python-docx).") from exc

    _STATUS = {"illegal": "TRÁI LUẬT (có thể vô hiệu)", "unfavorable": "Bất lợi"}
    _PRIO = {"must_fix": "Phải sửa", "negotiate": "Thương lượng", "acceptable": "Chấp nhận được"}
    doc = Document()
    doc.add_heading(memo.get("title") or "BẢN GHI NHỚ SỬA ĐỔI HỢP ĐỒNG", level=0)
    rows = memo.get("rows", [])
    cols = ["#", "Điều khoản", "Vấn đề", "Tính chất", "Căn cứ pháp lý", "Đề xuất sửa", "Ưu tiên"]
    table = doc.add_table(rows=1, cols=len(cols))
    table.style = "Light Grid Accent 1"
    for c, name in zip(table.rows[0].cells, cols):
        c.text = name
    for i, r in enumerate(rows, 1):
        nature = _STATUS.get(r.get("legal_status"), r.get("legal_status", ""))
        if r.get("legal_status") == "illegal" and r.get("violated_law"):
            nature += f" — {r['violated_law']}"
        cells = table.add_row().cells
        vals = [str(i), r.get("clause", ""), r.get("issue", ""), nature,
                r.get("legal_basis", ""), r.get("suggestion", ""),
                _PRIO.get(r.get("priority"), r.get("priority", ""))]
        for cell, v in zip(cells, vals):
            cell.text = v or "—"
    illegal = memo.get("illegal_count", sum(r.get("legal_status") == "illegal" for r in rows))
    doc.add_paragraph(f"Tổng: {len(rows)} điều khoản — {illegal} TRÁI LUẬT, {len(rows) - illegal} bất lợi.")
    doc.add_paragraph("⚠️ Bản ghi nhớ do AI hỗ trợ soạn — luật sư cần đối chiếu bản gốc trước khi sử dụng.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
