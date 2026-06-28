"""Sinh PHIẾU LUẬT SƯ DUYỆT từ golden set → CSV (Excel) + Markdown (đọc nhanh), PHÂN LOẠI theo lĩnh vực.

Mục đích: gửi luật sư xác nhận đáp án kỳ vọng (Đúng/Sai/Sửa). Nhóm theo lĩnh vực để giao đúng chuyên môn
+ thấy loại test (tra cứu / điểm thời gian / phân biệt / từ chối).
Chạy: uv run python -m evaluation.golden_to_review  → docs/internal/ (gitignored — file nội bộ để gửi).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

_GOLDEN = Path("evaluation/accuracy_golden.json")
_OUT_DIR = Path("docs/internal")
_TYPE_VI = {"tra_cuu": "Tra cứu", "diem_thoi_gian": "Điểm thời gian", "phan_biet": "Phân biệt",
            "tu_choi": "Từ chối (chống bịa)", "ap_dung": "Áp dụng tình huống",
            "bay_tien_de": "Bẫy tiền đề sai", "closure": "Dẫn chiếu chéo", "cap_nhat": "Cập nhật văn bản"}
_HEADERS = ["STT", "Lĩnh vực", "Loại", "Câu hỏi", "Đáp án kỳ vọng (hệ thống)", "Căn cứ pháp lý",
            "Luật sư duyệt (Đúng/Sai)", "Sửa lại / Ghi chú"]


def _load() -> list[dict]:
    return json.loads(_GOLDEN.read_text(encoding="utf-8"))["cases"]


def _expected(c: dict) -> str:
    return ("(NGOÀI phạm vi KB → hệ thống PHẢI từ chối, không được bịa)" if c.get("abstain")
            else c.get("expected", ""))


def write_review() -> tuple[Path, Path]:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = _load()
    # CSV (Excel) — phẳng, có cột Lĩnh vực/Loại để lọc-sắp.
    csv_path = _OUT_DIR / "golden-set-lawyer-review.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(_HEADERS)
        for i, c in enumerate(cases, 1):
            w.writerow([i, c.get("category", ""), _TYPE_VI.get(c.get("type", ""), c.get("type", "")),
                        c["question"], _expected(c), c.get("basis", ""), "", ""])
    # Markdown — NHÓM theo lĩnh vực (giao đúng luật sư chuyên môn).
    md_path = _OUT_DIR / "golden-set-lawyer-review.md"
    by_cat: dict[str, list[tuple[int, dict]]] = {}
    for i, c in enumerate(cases, 1):
        by_cat.setdefault(c.get("category", "Khác"), []).append((i, c))
    lines = ["# Phiếu luật sư duyệt — Golden set tra cứu pháp luật (Legal Guard)", "",
             "> Nhờ luật sư xác nhận **đáp án kỳ vọng** Đúng/Sai (sửa nếu cần) — phân theo lĩnh vực để giao "
             "đúng chuyên môn. Sau khi duyệt → chuẩn đo độ chính xác trên trang /trust.",
             f"> Tổng **{len(cases)} câu** / **{len(by_cat)} lĩnh vực**. Nguồn máy-đọc: `evaluation/accuracy_golden.json`."]
    for cat, items in by_cat.items():
        lines += ["", f"## {cat} ({len(items)} câu)", "",
                  "| STT | Loại | Câu hỏi | Đáp án kỳ vọng | Căn cứ | Đúng/Sai | Sửa lại |",
                  "|---|---|---|---|---|---|---|"]
        for i, c in items:
            cells = [str(i), _TYPE_VI.get(c.get("type", ""), ""), c["question"], _expected(c),
                     c.get("basis", ""), "", ""]
            lines.append("| " + " | ".join(x.replace("|", "/") for x in cells) + " |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, md_path


if __name__ == "__main__":
    csv_path, md_path = write_review()
    cats = {c.get("category") for c in _load()}
    print(f"Đã tạo phiếu ({len(_load())} câu, {len(cats)} lĩnh vực):\n  - {csv_path} (Excel)\n  - {md_path}")
