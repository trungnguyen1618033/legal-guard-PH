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


def to_kb_markdown(meta: dict, content_html: str,
                   relations: dict[str, list[str]] | None = None,
                   domain: str | None = None) -> tuple[str, str] | None:
    """1 record (metadata + content_html [+ relations]) → (filename, nội dung .md có front-matter).
    None nếu rỗng text. `relations` (từ `group_relationships`) → ghi cạnh đồ thị (amends/replaced_by/...)
    vào front-matter — CHÍNH là dữ liệu để closure/changelog/impact/lược đồ sáng lên ở quy mô lớn.
    `domain`: nhãn lĩnh vực (vd 'xay_dung') → domain-scoped retrieval lọc theo lĩnh vực (chống
    cạnh-tranh-toàn-cục khi mở rộng KB — kb-expansion-plan trụ cột 1)."""
    body = html_to_text(content_html)
    if not body:
        return None
    fm: dict[str, str] = {
        "doc_id": meta.get("so_ky_hieu") or f"id-{meta.get('id')}",
        "title": (meta.get("title") or "").strip(),
        "doc_type": doc_type_from(meta.get("loai_van_ban")),
        "domain": (domain or "").strip(),
        "status": map_status(meta.get("tinh_trang_hieu_luc")),
        "effective_date": iso_date(meta.get("ngay_co_hieu_luc")),
        "expiry_date": iso_date(meta.get("ngay_het_hieu_luc")),
        "issuer": (meta.get("co_quan_ban_hanh") or "").strip(),
    }
    for field, refs in (relations or {}).items():     # cạnh đồ thị: 'amends: a; b' (parser đọc dấu ;,)
        joined = "; ".join(dict.fromkeys(r.strip() for r in refs if r.strip()))
        if joined:
            fm[field] = joined
    # Nếu VB này SỬA ĐỔI VB khác → tự rút điều bị sửa từ thân (article-level scope cho impact + bôi vàng),
    # thay vì khai tay `amends_articles`. Rule tất định (extract_article_changes), không LLM.
    if (relations or {}).get("amends"):
        from legalguard.adapters.outbound.legal_chunker import extract_article_changes
        arts = "; ".join(dict.fromkeys(c["article"] for c in extract_article_changes(body)))
        if arts:
            fm["amends_articles"] = arts
    fm["source"] = "th1nhng0/vietnamese-legal-documents (vbpl.vn, CC BY 4.0) — auto-ingest, CẦN luật sư duyệt"
    lines = ["---"] + [f"{k}: {v}" for k, v in fm.items() if v != ""] + ["---", ""]
    header = f"{fm['title']} — {fm['doc_id']}. Trạng thái: {meta.get('tinh_trang_hieu_luc') or 'Còn hiệu lực'}."
    return safe_filename(meta.get("so_ky_hieu"), meta.get("id")), "\n".join(lines) + header + "\n\n" + body


def group_relationships(pairs: list[tuple[str, str]]) -> dict[str, list[str]]:
    """[(loại_quan_hệ_VN, số_hiệu_VB_liên_quan)] → {front_matter_field: [doc_ref...]} (khử trùng, giữ thứ tự).

    Tách khỏi schema dataset để TEST OFFLINE: batch trích các cặp (loại, số hiệu) từ config `relationships`
    rồi gom qua hàm này. Bỏ qua loại không map được (vd 'văn bản căn cứ' → based_on vẫn giữ nếu cần)."""
    out: dict[str, list[str]] = {}
    for rel_type, ref in pairs:
        field = relationship_field(rel_type)
        ref = (ref or "").strip()
        if field and ref:
            out.setdefault(field, [])
            if ref not in out[field]:
                out[field].append(ref)
    return out


# Quan hệ dataset (config `relationships`) → field front-matter. HƯỚNG ĐÃ VERIFY bằng cặp thật
# (NĐ 70/2025 ⇄ NĐ 123/2020): nhãn mô tả vai trò của `other_doc_id`; `doc_id` là CHỦ THỂ.
# Quy luật: "được/bị X" = source làm X cho other; "X" (chủ động) = other làm X cho source.
_REL_FIELD = {
    "văn bản được sửa đổi": "amends",            # source SỬA other        (VERIFIED)
    "văn bản được bổ sung": "amends",            # source BỔ SUNG other
    "văn bản sửa đổi": "amended_by",             # other sửa source        (VERIFIED)
    "văn bản bổ sung": "amended_by",             # other bổ sung source    (VERIFIED)
    "văn bản hết hiệu lực": "replaces",          # source làm other hết hiệu lực (thay thế)
    "văn bản quy định hết hiệu lực": "replaced_by",        # other làm source hết hiệu lực
    "văn bản bị hết hiệu lực 1 phần": "amends",            # source làm other hết hiệu lực 1 phần
    "văn bản quy định hết hiệu lực 1 phần": "amended_by",
    "văn bản được hd, qđ chi tiết": "guides",    # source HƯỚNG DẪN other
    "văn bản hd, qđ chi tiết": "guided_by",      # other hướng dẫn source
    "văn bản căn cứ": "based_on", "văn bản dẫn chiếu": "references",
    # nhãn dạng đầy đủ (nguồn khác có thể dùng) — giữ tương thích:
    "văn bản bị sửa đổi": "amended_by", "văn bản thay thế": "replaces",
    "văn bản bị thay thế": "replaced_by", "văn bản được hướng dẫn": "guides",
    "văn bản hướng dẫn": "guided_by",
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


def rel_pairs_by_source(rel_rows: list[dict], id_to_ref: dict[str, str]
                        ) -> dict[str, list[tuple[str, str]]]:
    """Config `relationships` → {source_id: [(loại_quan_hệ, số_hiệu_VB_liên_quan)]} (cho group_relationships).

    PHÒNG THỦ tên cột (schema dataset có thể khác): thử nhiều tên cho source-id / loại / VB-đích; nếu đích
    chỉ có id thì tra `id_to_ref` (id→số hiệu). Bỏ qua hàng thiếu trường. Tách riêng để TEST OFFLINE."""
    out: dict[str, list[tuple[str, str]]] = {}
    for r in rel_rows:
        # Schema THẬT th1nhng0: doc_id (nguồn, int), other_doc_id (đích, là id), relationship (loại).
        src = str(r.get("doc_id") or r.get("id") or r.get("source_id") or r.get("from_id") or "")
        rel_type = (r.get("relationship") or r.get("loai_quan_he") or r.get("relation") or "")
        ref = (r.get("related_so_ky_hieu") or r.get("so_ky_hieu") or "")
        if not ref:                                   # đích thường chỉ là id → tra số hiệu
            rid = str(r.get("other_doc_id") or r.get("related_id") or r.get("to_id") or "")
            ref = id_to_ref.get(rid, "")
        if src and rel_type and ref:
            out.setdefault(src, []).append((str(rel_type), str(ref)))
    return out


def run_bulk(out: str = "knowledge_base/_ingested", limit: int | None = None,
             keyword: str | None = None, in_force_only: bool = False, min_year: int = 0,
             central_only: bool = False, mirror_dir: str | None = None, dry_run: bool = False,
             types: str | None = None, domain_label: str | None = None) -> int:
    """CON BATCH bulk: join metadata + content + relationships của th1nhng0 (CC BY 4.0, vbpl.vn) → KB .md
    KÈM cạnh đồ thị (amends/replaced_by/guides…) + hiệu lực. Trả số file đã ghi (dry_run: số SẼ ghi).

    `mirror_dir`: đọc parquet từ MIRROR LOCAL (data/legal-corpus-mirror/th1nhng0/data) — offline, không tải
    lại + không cần `datasets`. Không có → tải từ HF (cần `uv add datasets`).
    `keyword`: chỉ ingest VB có keyword trong title/loại/ngành/lĩnh vực (slice LIÊN QUAN sản phẩm, tránh
    nạp 178k VB nhiễu). `dry_run`: CHỈ đếm + báo phân bố, KHÔNG ghi file (khảo sát trước khi nạp thật).
    KHÔNG scrape TVPL (license). Idempotent: ghi đè theo số hiệu (re-run=cập nhật)."""
    import pyarrow.parquet as pq
    out_dir = Path(out)
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    kws = [k.strip().lower() for k in (keyword or "").split(",") if k.strip()]   # nhiều keyword = OR
    type_allow = {t.strip() for t in (types or "").split(",") if t.strip()}      # lọc doc_type quy phạm

    if mirror_dir:                                    # OFFLINE: đọc parquet mirror trực tiếp
        md = Path(mirror_dir)
        meta = pq.read_table(md / "metadata.parquet").to_pylist()
        meta_by_id = {str(r["id"]): r for r in meta}
        id_to_ref = {i: (m.get("so_ky_hieu") or "") for i, m in meta_by_id.items()}
        rel_rows = pq.read_table(md / "relationships.parquet").to_pylist()
        rels = rel_pairs_by_source(rel_rows, id_to_ref)
        cpath = str(md / "content.parquet")
    else:                                             # ONLINE: tải từ HF
        try:
            from datasets import load_dataset
        except ImportError:
            raise SystemExit("Cần cài: uv add datasets (hoặc dùng --mirror-dir).") from None
        meta = load_dataset(_DATASET, "metadata", split="data")
        meta_by_id = {str(r["id"]): r for r in meta}
        id_to_ref = {i: (m.get("so_ky_hieu") or "") for i, m in meta_by_id.items()}
        try:
            rel_rows = list(load_dataset(_DATASET, "relationships", split="data"))
            rels = rel_pairs_by_source(rel_rows, id_to_ref)
        except Exception:  # noqa: BLE001 — không có relationships → vẫn ingest nội dung + hiệu lực
            rels = {}
            print("⚠️ Không nạp được relationships — bỏ cạnh đồ thị, vẫn ghi hiệu lực/nội dung.")

    def _match(m: dict) -> bool:
        if in_force_only and map_status(m.get("tinh_trang_hieu_luc")) != "in_force":
            return False                           # bỏ VB hết hiệu lực (giữ KB sạch, hiện hành)
        if type_allow and doc_type_from(m.get("loai_van_ban")) not in type_allow:
            return False                           # chỉ loại quy phạm (bỏ Quyết định/Chỉ thị hành chính nhiễu)
        if central_only:                           # chỉ VB TRUNG ƯƠNG (bỏ VB tỉnh/địa phương nhiễu)
            sk = (m.get("so_ky_hieu") or "").upper()
            if "UBND" in sk or "-HĐND" in sk or "/HĐND" in sk:
                return False
        if min_year:                               # chỉ luật HIỆN ĐẠI (tránh luật cũ thập niên trước)
            eff = iso_date(m.get("ngay_co_hieu_luc"))
            if not eff or int(eff[:4]) < min_year:
                return False
        if not kws:
            return True
        hay = " ".join(str(m.get(f, "") or "") for f in
                       ("title", "loai_van_ban", "nganh", "linh_vuc", "so_ky_hieu")).lower()
        return any(k in hay for k in kws)          # khớp BẤT KỲ keyword (OR)

    # content.parquet có cột HTML kiểu large_string → `datasets` cast sang string lỗi (>2GB). Đọc THẲNG
    # bằng pyarrow theo batch (giữ large_string, nhẹ RAM; ONLINE thì đã set cpath ở nhánh HF).
    if not mirror_dir:
        from huggingface_hub import hf_hub_download
        cpath = hf_hub_download(_DATASET, "data/content.parquet", repo_type="dataset")
    written = 0
    from collections import Counter
    by_type: Counter = Counter()                       # phân bố loại VB (cho dry_run khảo sát)
    for batch in pq.ParquetFile(cpath).iter_batches(batch_size=256):
        for r in batch.to_pylist():
            m = meta_by_id.get(str(r.get("id")))
            if not m or not _match(m):
                continue
            relations = group_relationships(rels.get(str(r.get("id")), []))
            res = to_kb_markdown(m, r.get("content_html", ""), relations=relations or None, domain=domain_label)
            if not res:                                # rỗng text (luật mới content trống — đã biết)
                continue
            by_type[doc_type_from(m.get("loai_van_ban"))] += 1
            written += 1
            if not dry_run:
                fname, content = res
                (out_dir / fname).write_text(content, encoding="utf-8")
            if written % 200 == 0:
                print(f"  … {written}", flush=True)
            if limit and written >= limit:
                break
        if limit and written >= limit:
            break
    verb = "SẼ ghi (dry-run)" if dry_run else f"đã ghi vào {out_dir}/"
    print(f"\nBulk: {written} file {verb} — phân bố loại: {dict(by_type.most_common())}")
    if not dry_run:
        print("(auto-ingest — CẦN luật sư duyệt + chạy accuracy_eval đo regression trước khi promote vào KB/VN.)")
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest HF legal dataset → KB .md (sample HTTP API hoặc --bulk)")
    ap.add_argument("--bulk", action="store_true", help="ingest toàn bộ (cần `datasets`) + cạnh đồ thị")
    ap.add_argument("--limit", type=int, default=None, help="giới hạn số file (cho bulk)")
    ap.add_argument("--in-force-only", action="store_true", help="chỉ VB còn hiệu lực (KB sạch, hiện hành)")
    ap.add_argument("--min-year", type=int, default=0, help="chỉ VB hiệu lực từ năm này (luật hiện đại)")
    ap.add_argument("--central-only", action="store_true", help="chỉ VB trung ương (bỏ VB tỉnh/UBND)")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--page-size", type=int, default=100)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--keyword", default=None, help="lọc client-side theo title/loại/ngành")
    ap.add_argument("--out", default="knowledge_base/_ingested")
    ap.add_argument("--mirror-dir", default=None,
                    help="đọc parquet mirror local (offline), vd data/legal-corpus-mirror/th1nhng0/data")
    ap.add_argument("--dry-run", action="store_true", help="chỉ đếm + báo phân bố, KHÔNG ghi file")
    ap.add_argument("--types", default=None,
                    help="chỉ loại quy phạm (vd nghi_dinh,thong_tu,luat,phap_lenh) — bỏ Quyết định/Chỉ thị")
    ap.add_argument("--domain-label", default=None, help="gắn nhãn domain (vd xay_dung) cho domain-scoped retrieval")
    args = ap.parse_args()

    if args.bulk:
        run_bulk(args.out, args.limit, args.keyword,
                 in_force_only=args.in_force_only, min_year=args.min_year,
                 central_only=args.central_only, mirror_dir=args.mirror_dir, dry_run=args.dry_run,
                 types=args.types, domain_label=args.domain_label)
        return

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
