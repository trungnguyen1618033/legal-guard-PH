"""Nạp PHIẾU LUẬT SƯ ĐÃ ĐIỀN (docs/internal/fast-bench-lawyer-review.csv) → 3 đầu ra:
  1. docs/internal/fast-bench-golden.json  — nhãn THẬT lawyer-verified (fast_bench_live tự nạp override nếu có)
  2. docs/internal/fast-bench-fewshot.txt  — khối few-shot (từ ca 'Dùng FEW-SHOT=Y') dán vào fast_review._SYSTEM
  3. Báo cáo: tỉ lệ đồng thuận (AI vs luật sư), số nhãn ĐỔI, phân bố, hàng chưa điền.
Chạy SAU khi luật sư điền: uv run python -m scripts.bench_review_to_golden
"""
from __future__ import annotations

import csv
import json
import os
import re

CSV_IN = "docs/internal/fast-bench-lawyer-review.csv"
MD_IN = "docs/internal/fast-bench-lawyer-review.md"
GOLDEN_OUT = "docs/internal/fast-bench-golden.json"
FEWSHOT_OUT = "docs/internal/fast-bench-fewshot.txt"

_VI2CANON = {"TRÁI LUẬT": "illegal", "BẤT LỢI": "unfavorable", "VÔ HẠI": "clean"}


def _canon(vi: str) -> str:
    """VI (khoan dung) → illegal|unfavorable|clean|'' (không nhận ra)."""
    u = (vi or "").strip().upper()
    for k, v in _VI2CANON.items():
        if k in u:
            return v
    return ""


def _yes(s: str) -> bool:
    return (s or "").strip().lower() in ("y", "yes", "có", "co", "x", "1", "true")


def _debold(s: str) -> str:
    return (s or "").replace("**", "").strip()


def _read_md(path: str) -> list[dict]:
    """Parse phiếu .md luật sư ĐÃ ĐIỀN (thay '____' bằng đáp án, có/không bold **). Trả rows shape như CSV."""
    rows: list[dict] = []
    hd = domain = None
    cur: dict | None = None

    def grab(line: str, label: str) -> str:
        m = re.search(re.escape(label) + r":\s*(.*?)\s*(?:\||$)", line)
        return _debold(m.group(1)) if m else ""

    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        m = re.match(r"^### HĐ `(.+?)` \((.+?)\)", line)
        if m:
            hd, domain = m.group(1), m.group(2)
            continue
        m = re.match(r"^\*\*\((\d+)\) (.+?) — đề xuất: (.+?)\*\*", line)
        if m:
            if cur:
                rows.append(cur)
            cur = {"STT": m.group(1), "HĐ": hd, "Lĩnh vực": domain, "Điều khoản": m.group(2),
                   "Nhãn ĐỀ XUẤT": m.group(3), "Nội dung điều khoản": "", "Luật sư ĐỒNG Ý? (Y/N)": "",
                   "Nhãn ĐÚNG (nếu khác)": "", "Điều luật viện dẫn": "", "Ghi chú luật sư": "",
                   "Dùng FEW-SHOT? (Y/N)": ""}
            continue
        if cur is None:
            continue
        if line.startswith("> ") and not cur["Nội dung điều khoản"]:
            cur["Nội dung điều khoản"] = line[2:].strip()
        elif "Đồng ý (Y/N)" in line:
            cur["Luật sư ĐỒNG Ý? (Y/N)"] = grab(line, "Đồng ý (Y/N)")
            cur["Nhãn ĐÚNG (nếu khác)"] = grab(line, "Nhãn đúng")
            cur["Điều luật viện dẫn"] = grab(line, "Điều luật")
            cur["Dùng FEW-SHOT? (Y/N)"] = grab(line, "Few-shot (Y/N)")
        elif line.startswith("- Ghi chú:"):
            cur["Ghi chú luật sư"] = _debold(line.split(":", 1)[1])
    if cur:
        rows.append(cur)
    return rows


def _load_rows() -> tuple[list[dict], str]:
    """Ưu tiên CSV nếu đã điền; nếu CSV trống mà MD đã điền → parse MD."""
    csv_rows = []
    if os.path.exists(CSV_IN):
        with open(CSV_IN, encoding="utf-8-sig") as fh:
            csv_rows = list(csv.DictReader(fh))
    if any(r.get("Luật sư ĐỒNG Ý? (Y/N)", "").strip() for r in csv_rows):
        return csv_rows, CSV_IN
    if os.path.exists(MD_IN):
        md_rows = _read_md(MD_IN)
        if any(r.get("Luật sư ĐỒNG Ý? (Y/N)", "").strip() for r in md_rows):
            return md_rows, MD_IN
    if csv_rows:
        return csv_rows, CSV_IN
    raise SystemExit(f"Chưa thấy phiếu đã điền ({CSV_IN} hoặc {MD_IN}).")


def main() -> None:
    rows, src = _load_rows()
    print(f"Đọc phiếu từ: {src}")

    golden, fewshot = [], []
    reviewed = agreed = changed = unfilled = 0
    dist = {"illegal": 0, "unfavorable": 0, "clean": 0}
    warns = []

    for r in rows:
        agree = r.get("Luật sư ĐỒNG Ý? (Y/N)", "").strip()
        proposed = _canon(r.get("Nhãn ĐỀ XUẤT", ""))
        if not agree:                                  # chưa duyệt → bỏ qua (không đưa vào golden)
            unfilled += 1
            continue
        reviewed += 1
        if _yes(agree):
            final = proposed
            agreed += 1
        else:                                          # không đồng ý → lấy 'Nhãn ĐÚNG'
            final = _canon(r.get("Nhãn ĐÚNG (nếu khác)", ""))
            changed += 1
            if not final:
                warns.append(f"STT {r.get('STT')}: N nhưng 'Nhãn ĐÚNG' trống/không nhận ra → BỎ QUA")
                reviewed -= 1
                changed -= 1
                continue
        dist[final] = dist.get(final, 0) + 1
        rec = {"hd": r.get("HĐ", ""), "dieu": r.get("Điều khoản", ""), "label": final,
               "article": r.get("Điều luật viện dẫn", "").strip(),
               "note": r.get("Ghi chú luật sư", "").strip(),
               "clause": r.get("Nội dung điều khoản", "").strip()}
        golden.append(rec)
        if _yes(r.get("Dùng FEW-SHOT? (Y/N)", "")):
            fewshot.append(rec)

    if not golden:
        raise SystemExit("Không có hàng nào đã duyệt (cột 'Đồng ý Y/N' đều trống). Chưa merge được.")

    os.makedirs(os.path.dirname(GOLDEN_OUT), exist_ok=True)
    with open(GOLDEN_OUT, "w", encoding="utf-8") as fh:
        json.dump(golden, fh, ensure_ascii=False, indent=2)

    # Few-shot: khối dán vào prompt — nhãn + điều luật viện dẫn (GROUNDED, do luật sư chọn)
    LB = {"illegal": "NÊU (TRÁI LUẬT)", "unfavorable": "NÊU (BẤT LỢI)", "clean": "BỎ (vô hại)"}
    with open(FEWSHOT_OUT, "w", encoding="utf-8") as fh:
        fh.write("VÍ DỤ LUẬT SƯ DUYỆT (ranh giới báo-dư — dán vào _SYSTEM fast_review):\n")
        for r in fewshot:
            art = f" [{r['article']}]" if r["article"] else ""
            note = f" — {r['note']}" if r["note"] else ""
            fh.write(f"- '{r['clause'][:120]}' → {LB.get(r['label'], r['label'])}{art}{note}\n")

    print(f"✅ Merge xong: {reviewed} điều khoản đã duyệt / {len(rows)} tổng")
    print(f"   Đồng thuận AI↔luật sư: {agreed}/{reviewed} = {round(100*agreed/reviewed,1)}% "
          f"· ĐỔI nhãn: {changed} · chưa điền: {unfilled}")
    print(f"   Phân bố THẬT: {dist['illegal']} illegal · {dist['unfavorable']} unfavorable · {dist['clean']} clean")
    print(f"   Few-shot lawyer-chọn: {len(fewshot)} ca")
    print(f"   → {GOLDEN_OUT}  (fast_bench_live tự nạp override)")
    print(f"   → {FEWSHOT_OUT}  (khối dán prompt)")
    if warns:
        print("   ⚠️ CẢNH BÁO:")
        for w in warns:
            print(f"     - {w}")
    print("\nBƯỚC TIẾP: (1) chạy lại `fast_bench_live` → số trên golden THẬT; "
          "(2) cân nhắc chèn few-shot vào _SYSTEM rồi A/B (prompt_ab style).")


if __name__ == "__main__":
    main()
