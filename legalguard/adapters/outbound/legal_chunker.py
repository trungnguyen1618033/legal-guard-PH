"""Chunking nhận biết cấu trúc văn bản pháp luật VN (Phase 0 — xem docs/internal/legal-search-expansion.md).

Bài toán: văn bản luật VN có đơn vị nguyên tử là **Điều/Khoản/Điểm** — đó cũng là đích trích dẫn.
Cắt theo dấu xuống dòng (paragraph) làm vỡ ngữ cảnh điều luật và mất nhãn để dẫn nguồn. Module này:

- `nfc(text)`: chuẩn hóa Unicode NFC (dấu tiếng Việt precomposed) — bắt buộc, rẻ, chống vỡ
  exact-match/BM25/dedup khi nguồn trộn NFC/NFD (OCR, DOCX, paste).
- `chunk_legal(text)`: nếu phát hiện ≥2 mốc "Điều N" → cắt theo Điều (sub-split theo Khoản khi quá
  dài), kèm nhãn cấu trúc; nếu không (vd ma trận fallback dạng markdown) → fallback cắt theo paragraph.
- `extract_citations(text)`: rút dẫn chiếu (Điều/khoản/điểm, NĐ/TT/Luật ...) — hạt giống cho
  Phase 2 (citation graph + closure retrieval). Hiện trả ra để gắn metadata, chưa traverse.

Thuần Python, offline, không phụ thuộc model — an toàn cho test.
"""
from __future__ import annotations

import re
import unicodedata

# "Điều 12", "Điều 12a" (đầu dòng). Cho phép tiền tố markdown/trích dẫn (#, *, >, -, khoảng trắng)
# để không vỡ khi luật được dán dạng markdown ("## Điều 5", "**Điều 5.**", "> Điều 5").
_ARTICLE_RE = re.compile(r"(?m)^[#*>\s\-]*(Điều\s+\d+[a-z]?)\b")
# Khoản đánh số đầu dòng: "1.", "12." — để sub-split điều luật quá dài (cũng chịu tiền tố markdown).
_CLAUSE_RE = re.compile(r"(?m)^[#*>\s]*(\d+)\.\s")
# Dẫn chiếu trong thân văn bản (rút cho Phase 2). Bắt cả "khoản 1 Điều 5", "điểm a khoản 2 Điều 5",
# và tham chiếu văn bản: "Nghị định 13/2023", "Thông tư 20/2026/TT-BTC", "Luật ... 91/2025".
_CITATION_RES = (
    re.compile(r"(?:điểm\s+[a-zđ]+\s+)?(?:khoản\s+\d+\s+)?Điều\s+\d+[a-z]?", re.IGNORECASE),
    re.compile(r"(?:Nghị\s*định|Thông\s*tư|Luật|Quyết\s*định|Bộ\s*luật)[^.;\n]*?\d+/\d{4}(?:/[A-ZĐ\-]+)?",
               re.IGNORECASE),
)

# Điều dài hơn ngưỡng này (ký tự) → cố sub-split theo Khoản để chunk gọn, vẫn giữ nhãn Khoản.
_MAX_ARTICLE_CHARS = 1500


_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def nfc(text: str) -> str:
    """Chuẩn hóa Unicode NFC. Áp dụng lúc nạp KB và lúc nhận query."""
    return unicodedata.normalize("NFC", text)


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Tách khối metadata máy-đọc đầu file (giữa hai dòng '---') khỏi thân văn bản.

    Dùng cho lọc hiệu lực: status / effective_date / doc_type / doc_id ... Không có khối → ({}, text).
    Trả về (meta, body) — body đã bỏ front-matter để chunk như thường.
    """
    text = nfc(text)
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    return meta, text[m.end():]


def chunk_legal(text: str) -> list[tuple[str | None, str]]:
    """Trả [(nhãn cấu trúc | None, đoạn)]. Nhãn vd 'Điều 5' / 'Điều 5 khoản 2'.

    - ≥2 mốc 'Điều N' → cắt theo Điều (sub-split theo Khoản nếu quá dài).
    - else → fallback cắt theo paragraph (giữ tương thích KB markdown hiện tại).
    """
    text = nfc(text)
    marks = list(_ARTICLE_RE.finditer(text))
    if not marks:        # KHÔNG có mốc "Điều" (vd ma trận fallback) → cắt theo paragraph
        return [(None, p.strip()) for p in re.split(r"\n\s*\n", text) if p.strip()]
    # ≥1 Điều → cắt theo Điều (kể cả văn bản chỉ có 1 Điều như NĐ sửa đổi — để vào được legal_basis/closure)

    out: list[tuple[str | None, str]] = []
    preamble = text[: marks[0].start(1)].strip()
    if preamble:
        out.append((None, preamble))  # phần mở đầu trước Điều 1 (tên VB, căn cứ ...)
    for i, m in enumerate(marks):
        label = re.sub(r"\s+", " ", m.group(1)).strip()
        end = marks[i + 1].start(1) if i + 1 < len(marks) else len(text)
        body = text[m.start(1):end].strip()   # start(1): bỏ tiền tố markdown, body bắt đầu từ "Điều"
        if len(body) <= _MAX_ARTICLE_CHARS:
            out.append((label, body))
        else:
            out.extend(_split_by_clause(label, body))
    return out


def _split_by_clause(article_label: str, body: str) -> list[tuple[str | None, str]]:
    """Điều quá dài → tách theo Khoản; nhãn 'Điều N khoản K'. Không có Khoản → giữ nguyên.

    Mỗi mảnh khoản được gắn lại dòng tiêu đề Điều ('Điều N. ...') ở đầu — giữ neo ngữ cảnh khi embed
    (Contextual-Retrieval-lite), tránh chunk 'mồ côi' chỉ có '2. ...' mất chủ đề điều luật.
    """
    marks = list(_CLAUSE_RE.finditer(body))
    if len(marks) < 2:
        return [(article_label, body)]
    heading = body.split("\n", 1)[0].strip()   # "Điều N. Tiêu đề"
    out: list[tuple[str | None, str]] = []
    head = body[: marks[0].start(1)].strip()
    if head:
        out.append((article_label, head))  # câu dẫn của Điều trước khoản 1 (đã chứa heading)
    for i, m in enumerate(marks):
        end = marks[i + 1].start(1) if i + 1 < len(marks) else len(body)
        piece = body[m.start(1):end].strip()
        if piece:
            anchored = piece if piece.startswith(heading) else f"{heading} — {piece}"
            out.append((f"{article_label} khoản {m.group(1)}", anchored))
    return out


_ARTICLE_KEY_RE = re.compile(r"Điều\s+\d+[a-z]?", re.IGNORECASE)


def article_key(citation: str) -> str | None:
    """Từ một dẫn chiếu → khóa điều luật chuẩn hóa. None nếu không trỏ tới một Điều cụ thể.

    'khoản 1 Điều 300' → 'Điều 300'; 'Điều 294 của Luật này' → 'Điều 294';
    'Điều này' / 'Nghị định 13/2023' → None (không có số Điều). Dùng để nối dẫn chiếu ↔ chunk.
    """
    m = _ARTICLE_KEY_RE.search(nfc(citation))
    if not m:
        return None
    return "Điều " + re.sub(r"\s+", " ", m.group(0)).split(maxsplit=1)[1]


_SELF_DOC_RE = re.compile(
    r"^\s*,?\s*(?:của\s+)?(?:Luật|Bộ luật|Nghị định|Thông tư|Pháp lệnh|Nghị quyết|Quyết định)\s+này",
    re.IGNORECASE)
_DOC_NUM_RE = re.compile(r"\d+/\d{4}/[A-ZĐ][A-ZĐ0-9-]*")
# Số hiệu PHẢI có từ loại văn bản đứng trước ("Nghị định số 123/2020/NĐ-CP") mới coi là trỏ văn bản đích —
# tránh gán nhầm số hiệu vu vơ trong câu (vd "...tại 13/2023/NĐ-CP" thuộc mệnh đề khác).
_DOC_REF_RE = re.compile(
    r"(?:Nghị\s*định|Thông\s*tư|Bộ\s*luật|Luật|Pháp\s*lệnh|Quyết\s*định|Nghị\s*quyết)\s*(?:số\s*)?"
    r"(\d+/\d{4}/[A-ZĐ][A-ZĐ0-9-]*)", re.IGNORECASE)
_ARTICLE_POS_RE = re.compile(r"Điều\s+(\d+[a-z]?)", re.IGNORECASE)


def extract_article_refs(text: str) -> list[tuple[str, str | None]]:
    """Rút dẫn chiếu điều luật KÈM văn bản đích → [(khóa điều, doc_ref)].

    doc_ref: 'self' nếu '... của Luật/Nghị định này'; số hiệu (vd '123/2020/NĐ-CP') nếu trỏ văn bản
    khác; None nếu trống ngữ cảnh (mặc định coi là cùng văn bản). Đây là cạnh cho document-aware closure —
    phân giải 'Điều 9 của Nghị định 123/2020' về ĐÚNG văn bản, không đoán theo số điều.
    """
    text = nfc(text)
    out: list[tuple[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    for m in _ARTICLE_POS_RE.finditer(text):
        art = "Điều " + m.group(1)
        window = text[m.end():m.end() + 60]
        doc_ref: str | None = None
        dref = _DOC_REF_RE.search(window)
        if dref:                                  # số hiệu có từ loại VB đứng trước → trỏ văn bản khác
            doc_ref = dref.group(1).upper()
        elif _SELF_DOC_RE.match(window):          # '... của Luật/Nghị định này' → cùng văn bản
            doc_ref = "self"
        key = (art.lower(), doc_ref)
        if key not in seen:
            seen.add(key)
            out.append((art, doc_ref))
    return out


def extract_citations(text: str) -> list[str]:
    """Rút dẫn chiếu (đã chuẩn hóa khoảng trắng, khử trùng giữ thứ tự). Seed cho Phase 2 closure."""
    text = nfc(text)
    found: list[str] = []
    seen: set[str] = set()
    for rx in _CITATION_RES:
        for m in rx.finditer(text):
            cite = re.sub(r"\s+", " ", m.group(0)).strip(" .,;")
            key = cite.lower()
            if key not in seen:
                seen.add(key)
                found.append(cite)
    return found
