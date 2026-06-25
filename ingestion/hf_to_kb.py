"""ETL: dataset mở HF `th1nhng0/vietnamese-legal-documents` → file KB .md (front-matter + chunk-ready).

Tận dụng dataset mở (CC BY 4.0): ~178k văn bản (content_html), 518k metadata (tinh_trang_hieu_luc,
ngày hiệu lực, loại VB...), + đồ thị quan hệ (Văn bản căn cứ / sửa đổi / thay thế). Biến mỗi văn bản
thành 1 file `.md` đúng format KB của ta (front-matter status/effective_date + thân chia theo Điều).

Hai phần TÁCH BIỆT:
- TRANSFORM (thuần, test offline): `to_kb_markdown`, `map_status`, `doc_type_from`, `iso_date`,
  `html_to_text`, `safe_filename` — không phụ thuộc mạng/lib, là phần tái dùng cốt lõi.
- FETCH (I/O): `fetch_sample` qua datasets-server HTTP API (sample nhỏ, không cần lib). Bulk thật nên
  dùng thư viện `datasets` + join parquet local (xem hướng dẫn cuối file) — API không hợp quy mô lớn.

Chạy sample:  uv run python -m ingestion.hf_to_kb --pages 4 --keyword "hóa đơn" --out knowledge_base/_ingested
"""
from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

_DATASET = "th1nhng0/vietnamese-legal-documents"
_API = "https://datasets-server.huggingface.co/rows"

# ---- TRANSFORM (thuần, test offline) -------------------------------------------------

# tinh_trang_hieu_luc (giá trị thật trong dataset) → status chuẩn của KB.
def map_status(vn: str | None) -> str:
    s = (vn or "").strip().lower()
    if not s:
        return "in_force"                      # thiếu → coi như còn hiệu lực
    if "một phần" in s:
        return "in_force"                      # hết hiệu lực MỘT PHẦN → phần lớn còn áp dụng
    if "hết hiệu lực" in s or "ngưng" in s or "hết hạn" in s:
        return "expired"
    return "in_force"                          # "Còn hiệu lực" và mặc định khác


_DOC_TYPE = {
    "luật": "luat", "bộ luật": "luat", "pháp lệnh": "phap_lenh", "hiến pháp": "hien_phap",
    "nghị định": "nghi_dinh", "nghị quyết": "nghi_quyet", "thông tư": "thong_tu",
    "thông tư liên tịch": "thong_tu", "quyết định": "quyet_dinh", "chỉ thị": "chi_thi",
}


def doc_type_from(loai_van_ban: str | None) -> str:
    s = (loai_van_ban or "").strip().lower()
    return _DOC_TYPE.get(s, re.sub(r"\s+", "_", s) or "khac")


def iso_date(s: str | None) -> str:
    """'03/09/1999' → '1999-09-03'. Rỗng/không hợp lệ → ''."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else ""


class _TextExtractor(HTMLParser):
    _BLOCK = {"p", "br", "div", "tr", "li", "h1", "h2", "h3", "h4", "table"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(html: str) -> str:
    """HTML văn bản luật → text thuần, giữ xuống dòng theo block để chunker bắt được 'Điều N'."""
    p = _TextExtractor()
    p.feed(html or "")
    text = unicodedata.normalize("NFC", "".join(p.parts))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def safe_filename(so_ky_hieu: str | None, doc_id: str | int) -> str:
    """'70/2025/NĐ-CP' → '70-2025-nd-cp.md'. Khử dấu, ascii-an toàn; fallback theo id."""
    base = (so_ky_hieu or f"doc-{doc_id}").strip().replace("Đ", "D").replace("đ", "d")
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").lower()
    return f"{base or f'doc-{doc_id}'}.md"


def to_kb_markdown(meta: dict, content_html: str) -> tuple[str, str] | None:
    """1 record (metadata + content_html) → (filename, nội dung .md có front-matter). None nếu rỗng text."""
    body = html_to_text(content_html)
    if not body:
        return None
    fm = {
        "doc_id": meta.get("so_ky_hieu") or f"id-{meta.get('id')}",
        "title": (meta.get("title") or "").strip(),
        "doc_type": doc_type_from(meta.get("loai_van_ban")),
        "status": map_status(meta.get("tinh_trang_hieu_luc")),
        "effective_date": iso_date(meta.get("ngay_co_hieu_luc")),
        "expiry_date": iso_date(meta.get("ngay_het_hieu_luc")),
        "issuer": (meta.get("co_quan_ban_hanh") or "").strip(),
        "source": "th1nhng0/vietnamese-legal-documents (vbpl.vn, CC BY 4.0) — auto-ingest, CẦN luật sư duyệt",
    }
    lines = ["---"] + [f"{k}: {v}" for k, v in fm.items() if v != ""] + ["---", ""]
    header = f"{fm['title']} — {fm['doc_id']}. Trạng thái: {meta.get('tinh_trang_hieu_luc') or 'Còn hiệu lực'}."
    return safe_filename(meta.get("so_ky_hieu"), meta.get("id")), "\n".join(lines) + header + "\n\n" + body


# Quan hệ trong dataset → field front-matter (nền cho document-aware closure sau này).
_REL_FIELD = {
    "văn bản được sửa đổi": "amends", "văn bản bị sửa đổi": "amended_by",
    "văn bản thay thế": "replaces", "văn bản bị thay thế": "replaced_by",
    "văn bản căn cứ": "based_on", "văn bản dẫn chiếu": "references",
    "văn bản được hướng dẫn": "guides", "văn bản hướng dẫn": "guided_by",
}


def relationship_field(rel: str | None) -> str | None:
    return _REL_FIELD.get((rel or "").strip().lower())


# ---- FETCH (I/O qua datasets-server HTTP API — chỉ hợp SAMPLE nhỏ) --------------------

def _get_rows(config: str, offset: int, length: int, retries: int = 6) -> list[dict]:
    url = (f"{_API}?dataset={urllib.parse.quote(_DATASET)}&config={config}"
           f"&split=data&offset={offset}&length={length}")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return [row["row"] for row in json.load(r).get("rows", [])]
        except Exception:  # noqa: BLE001 — 502/timeout tạm thời → backoff rồi thử lại
            if attempt == retries - 1:
                return []
            time.sleep(1.5 * (attempt + 1))
    return []


def fetch_sample(pages: int = 3, page_size: int = 100, keyword: str | None = None,
                 start: int = 0) -> list[tuple[dict, str]]:
    """Lấy SAMPLE: page metadata + content cùng cửa sổ offset, join theo id, lọc client-side theo keyword.
    Chỉ để demo/kiểm thử trên dữ liệu thật — bulk thật dùng `datasets` (xem cuối file)."""
    kw = (keyword or "").strip().lower()
    out: list[tuple[dict, str]] = []
    for i in range(pages):
        off = start + i * page_size
        meta = {str(r["id"]): r for r in _get_rows("metadata", off, page_size)}
        content = {str(r["id"]): r.get("content_html", "") for r in _get_rows("content", off, page_size)}
        for doc_id, html in content.items():
            m = meta.get(doc_id)
            if not m:
                continue
            if kw:
                hay = " ".join(str(m.get(f, "")) for f in
                               ("title", "loai_van_ban", "nganh", "linh_vuc", "so_ky_hieu")).lower()
                if kw not in hay:
                    continue
            out.append((m, html))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest HF legal dataset → KB .md (sample qua HTTP API)")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--page-size", type=int, default=100)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--keyword", default=None, help="lọc client-side theo title/loại/ngành")
    ap.add_argument("--out", default="knowledge_base/_ingested")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for meta, html in fetch_sample(args.pages, args.page_size, args.keyword, args.start):
        res = to_kb_markdown(meta, html)
        if not res:
            continue
        fname, content = res
        (out_dir / fname).write_text(content, encoding="utf-8")
        written += 1
        print(f"  ✓ {fname}  [{map_status(meta.get('tinh_trang_hieu_luc'))}]  {meta.get('title','')[:50]}")
    print(f"\nĐã ghi {written} file vào {out_dir}/ (auto-ingest — CẦN luật sư duyệt trước khi dùng tư vấn).")


if __name__ == "__main__":
    main()

# --- Bulk thật (chạy local, cần `uv add datasets`): -----------------------------------
#   from datasets import load_dataset
#   meta = load_dataset(_DATASET, "metadata", split="data")          # 518k, ~125MB
#   meta_by_id = {str(r["id"]): r for r in meta}                      # index trong RAM
#   for r in load_dataset(_DATASET, "content", split="data", streaming=True):  # 178k text
#       m = meta_by_id.get(str(r["id"]))
#       if m: write to_kb_markdown(m, r["content_html"])
#   rel = load_dataset(_DATASET, "relationships", split="data")       # đồ thị → edges (closure)
