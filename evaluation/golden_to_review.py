"""Sinh PHIẾU LUẬT SƯ DUYỆT từ golden set → CSV (mở Excel) + Markdown (đọc nhanh).

Mục đích: gửi luật sư xác nhận đáp án kỳ vọng (Đúng/Sai/Sửa) trước khi dùng làm chuẩn đo độ chính xác.
Chạy: uv run python -m evaluation.golden_to_review
Xuất vào docs/internal/ (gitignored — file nội bộ để gửi).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

_GOLDEN = Path("evaluation/accuracy_golden.json")
_OUT_DIR = Path("docs/internal")
_HEADERS = ["STT", "Câu hỏi", "Đáp án kỳ vọng (hệ thống)", "Căn cứ pháp lý",
            "Luật sư duyệt (Đúng/Sai)", "Sửa lại / Ghi chú"]


def _rows() -> list[list[str]]:
    cases = json.loads(_GOLDEN.read_text(encoding="utf-8"))["cases"]
    out = []
    for i, c in enumerate(cases, 1):
        expected = c.get("expected", "")
        if c.get("abstain"):
            expected = "(NGOÀI phạm vi KB → hệ thống PHẢI từ chối, không được bịa)"
        out.append([str(i), c["question"], expected, c.get("basis", ""), "", ""])
    return out


def write_review() -> tuple[Path, Path]:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = _rows()
    # CSV (Excel)
    csv_path = _OUT_DIR / "golden-set-lawyer-review.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig → Excel đọc tiếng Việt
        w = csv.writer(f)
        w.writerow(_HEADERS)
        w.writerows(rows)
    # Markdown (đọc nhanh / gửi chat)
    md_path = _OUT_DIR / "golden-set-lawyer-review.md"
    lines = ["# Phiếu luật sư duyệt — Golden set tra cứu pháp luật (Legal Guard)", "",
             "> Nhờ luật sư xác nhận **đáp án kỳ vọng** dưới đây Đúng/Sai (sửa nếu cần). Sau khi duyệt, "
             "dùng làm chuẩn đo độ chính xác công bố trên trang /trust. Phạm vi: LTM 2005, BLDS 2015, "
             "NĐ 123/2020 + 70/2025, TT 39/2014.", "",
             "| " + " | ".join(_HEADERS) + " |",
             "|" + "|".join(["---"] * len(_HEADERS)) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(cell.replace("|", "/") for cell in r) + " |")
    lines += ["", f"_Tổng {len(rows)} câu. Nguồn máy-đọc: evaluation/accuracy_golden.json._"]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, md_path


if __name__ == "__main__":
    csv_path, md_path = write_review()
    print(f"Đã tạo phiếu luật sư duyệt:\n  - {csv_path} (mở Excel)\n  - {md_path} (đọc/gửi nhanh)")
