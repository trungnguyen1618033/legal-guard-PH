"""Sinh PHIẾU LUẬT SƯ DUYỆT từ bộ 20 HĐ benchmark (scripts/fast_bench_live.CASES) → docs/internal/
fast-bench-lawyer-review.{csv,md}. Luật sư điền → (1) golden nhãn THẬT (thay smoke tác-giả-gán), (2) ca
FEW-SHOT calibrate (đánh dấu 'Dùng few-shot=Y' + viện dẫn điều luật). Chạy: uv run python -m scripts.bench_to_review
"""
from __future__ import annotations

import csv
import os

from scripts.fast_bench_live import CASES

LABEL_VI = {"illegal": "TRÁI LUẬT", "unfavorable": "BẤT LỢI", "clean": "VÔ HẠI/tiêu chuẩn"}
OUT_DIR = "docs/internal"


def _clause_text(contract: str, anchor: str) -> str:
    """Rút NGUYÊN VĂN điều khoản: từ anchor tới 'Điều ' kế tiếp (hoặc hết)."""
    i = contract.find(anchor)
    if i < 0:
        return ""
    rest = contract[i:]
    j = rest.find("\nĐiều ", 1)
    return " ".join((rest[:j] if j > 0 else rest).split()).strip()


def _rows() -> list[dict]:
    rows = []
    n = 0
    for c in CASES:
        for cl in c.clauses:
            n += 1
            rows.append({
                "STT": n, "HĐ": c.name, "Lĩnh vực": c.domain, "Điều khoản": cl.anchor,
                "Nội dung điều khoản": _clause_text(c.text, cl.anchor),
                "Nhãn ĐỀ XUẤT": LABEL_VI[cl.label], "Lý do đề xuất (neo luật VN)": cl.why,
                # cột luật sư điền:
                "Luật sư ĐỒNG Ý? (Y/N)": "", "Nhãn ĐÚNG (nếu khác)": "",
                "Điều luật viện dẫn": "", "Ghi chú luật sư": "", "Dùng FEW-SHOT? (Y/N)": "",
            })
    return rows


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    rows = _rows()
    cols = list(rows[0].keys())

    csv_path = f"{OUT_DIR}/fast-bench-lawyer-review.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:   # utf-8-sig → Excel mở tiếng Việt đúng
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    n_ill = sum(1 for c in CASES for cl in c.clauses if cl.label == "illegal")
    n_unf = sum(1 for c in CASES for cl in c.clauses if cl.label == "unfavorable")
    n_cln = sum(1 for c in CASES for cl in c.clauses if cl.label == "clean")
    md_path = f"{OUT_DIR}/fast-bench-lawyer-review.md"
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("# Phiếu luật sư duyệt — bộ benchmark rà soát nhanh (fast-path)\n\n")
        fh.write(f"**{len(CASES)} hợp đồng · {len(rows)} điều khoản** "
                 f"(đề xuất: {n_ill} TRÁI LUẬT · {n_unf} BẤT LỢI · {n_cln} VÔ HẠI).\n\n")
        fh.write("## Mục đích\n"
                 "Nhãn hiện tại do **kỹ sư gán** (neo luật VN), CHƯA luật sư xác nhận → chỉ dùng smoke/regression. "
                 "Luật sư duyệt để: (1) biến thành **golden THẬT** (đo độ chính xác đáng tin, bỏ caveat); "
                 "(2) chọn ca **FEW-SHOT calibrate** dạy AI ranh giới báo-dư (đánh 'Dùng FEW-SHOT=Y').\n\n")
        fh.write("## Cách điền (mỗi điều khoản)\n"
                 "- **Đồng ý? (Y/N)**: nhãn đề xuất đúng chưa.\n"
                 "- **Nhãn đúng**: nếu N → ghi TRÁI LUẬT / BẤT LỢI / VÔ HẠI.\n"
                 "- **Điều luật viện dẫn**: điều/khoản luật VN cụ thể (vd 'Điều 301 LTM', 'Điều 468 BLDS').\n"
                 "- **Dùng FEW-SHOT? (Y/N)**: ca điển hình đáng đưa vào prompt dạy AI.\n\n"
                 "> Nhãn: **TRÁI LUẬT** = vi phạm quy định bắt buộc (có thể vô hiệu) · **BẤT LỢI** = hợp pháp "
                 "nhưng thiệt cho bên được bảo vệ · **VÔ HẠI** = tiêu chuẩn/cân bằng, KHÔNG nên cảnh báo.\n\n")
        cur = None
        for r in rows:
            if r["HĐ"] != cur:
                cur = r["HĐ"]
                fh.write(f"\n### HĐ `{cur}` ({r['Lĩnh vực']})\n\n")
            fh.write(f"**({r['STT']}) {r['Điều khoản']} — đề xuất: {r['Nhãn ĐỀ XUẤT']}**\n\n")
            fh.write(f"> {r['Nội dung điều khoản']}\n\n")
            fh.write(f"- Lý do đề xuất: {r['Lý do đề xuất (neo luật VN)']}\n")
            fh.write("- Luật sư — Đồng ý (Y/N): ____  | Nhãn đúng: ____  | Điều luật: ____  | "
                     "Few-shot (Y/N): ____\n")
            fh.write("- Ghi chú: \n\n")

    print(f"✅ Đã sinh phiếu duyệt ({len(rows)} điều khoản, {len(CASES)} HĐ):")
    print(f"   - {md_path}  (đọc/điền tay cho luật sư)")
    print(f"   - {csv_path}  (Excel round-trip → nạp lại golden)")
    print("Gợi ý: gửi bản .md hoặc .csv cho luật sư; nhận lại → merge nhãn THẬT + rút ca few-shot.")


if __name__ == "__main__":
    main()
