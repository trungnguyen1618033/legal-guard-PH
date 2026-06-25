"""Regulatory change intelligence — chủ động: VB pháp luật MỚI → ảnh hưởng HĐ nào → cảnh báo.

Đây là moat "system-of-record": ta đã lưu các case rà soát kèm CĂN CỨ PHÁP LÝ tất định
(`legal_basis = 'file.md#Điều N: …'`). Khi một văn bản mới sửa đổi/thay thế/hướng dẫn một văn
bản cũ, mọi case từng viện dẫn văn bản cũ ĐỀU có nguy cơ lỗi thời → cảnh báo khách rà soát lại.

Logic ở đây THUẦN (offline, test được): nhận tập file bị tác động + các case (dict đã lưu) → liệt kê
mục (risk/fallback) viện dẫn file đó. Phần "VB mới → file bị tác động" do KB provider cung cấp
(`affected_files`, suy từ front-matter quan hệ amends/replaces/guides).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class RegulatoryImpact:
    """Một mục trong case viện dẫn văn bản vừa thay đổi — cần khách rà soát lại."""
    case_id: str
    org_id: str
    clause: str
    kind: str             # risk | fallback
    affected_file: str    # file luật bị tác động (đang được viện dẫn)
    relation: str         # amends | replaces | guides (cách VB mới tác động)
    new_doc_id: str       # số hiệu VB mới gây thay đổi
    basis: str            # nguyên căn cứ pháp lý đã gắn (để khách thấy chỗ cần soát)
    affected_article: str = ""   # điều luật bị tác động khớp (nếu lọc article-level), vd 'Điều 9'


_REL_VI = {"amends": "sửa đổi", "replaces": "thay thế", "guides": "hướng dẫn"}
_KIND_VI = {"risk": "rủi ro", "fallback": "phương án"}
_ARTICLE_RE = re.compile(r"Điều\s+\d+[a-z]?", re.IGNORECASE)


def norm_article(text: str) -> str:
    """Chuẩn hóa 'Điều' về dạng canonical 'điều 9' (lower, gộp khoảng trắng) để khớp. '' nếu không có."""
    m = _ARTICLE_RE.search(text or "")
    return re.sub(r"\s+", " ", m.group(0)).lower() if m else ""


def format_impact_alert(doc_id: str, impacts: list[dict], max_items: int = 15) -> str:
    """Soạn cảnh báo chủ động (text, dùng cho Slack/Zalo) từ kết quả `scan_cases` (dict đã `asdict`).

    Rỗng → '' (không có gì để gửi). Gom theo case để khách dễ đọc."""
    if not impacts:
        return ""
    cases: dict[str, list[dict]] = {}
    for i in impacts:
        cases.setdefault(i["case_id"], []).append(i)
    lines = [f"🛎️ *Cảnh báo pháp lý* — văn bản mới: *{doc_id.strip()}*",
             f"{len(cases)} hợp đồng đã rà soát có căn cứ bị ảnh hưởng, nên rà soát lại:"]
    for cid in list(cases)[:max_items]:
        items = cases[cid]
        rel = _REL_VI.get(items[0]["relation"], items[0]["relation"])
        clauses = ", ".join(dict.fromkeys(i["clause"] for i in items if i["clause"])) or "(điều khoản)"
        arts = ", ".join(dict.fromkeys(i.get("affected_article", "") for i in items
                                       if i.get("affected_article")))
        where = f"{items[0]['affected_file']}{' ' + arts if arts else ''}"
        lines.append(f"• *{cid}* — {clauses} (bị {rel}: {where})")
    if len(cases) > max_items:
        lines.append(f"… và {len(cases) - max_items} hợp đồng khác.")
    lines.append("Xem chi tiết tại trang Tra cứu (/lookup) hoặc API /impact/" + doc_id.strip() + ".")
    return "\n".join(lines)


def parse_basis(basis: str) -> tuple[str, str]:
    """Tách (file, điều) từ căn cứ 'file.md#Điều N: …'. ('','') nếu không có '#'."""
    if not basis or "#" not in basis:
        return "", ""
    file, rest = basis.split("#", 1)
    return file.strip(), norm_article(rest)


def parse_basis_file(basis: str) -> str:
    """Lấy tên FILE từ căn cứ (rỗng nếu không có '#'). Tiện ích quanh `parse_basis`."""
    return parse_basis(basis)[0]


def scan_cases(cases: list, affected: dict[str, dict], new_doc_id: str = "") -> list[RegulatoryImpact]:
    """Quét case (dict đã lưu) → mục viện dẫn file trong `affected`.

    `affected` = {filename: {"relation": str, "articles": list[str]}}. Nếu `articles` RỖNG → cảnh báo
    cả văn bản (doc-level). Nếu có → CHỈ cảnh báo mục viện dẫn đúng điều bị sửa (article-level, giảm
    báo động giả). Đọc cả `legal_basis` lẫn `source`; mỗi (case, kind, clause, file) báo 1 lần."""
    if not affected:
        return []
    # Chuẩn hóa danh sách điều bị tác động về set canonical để khớp nhanh.
    arts_by_file = {fn: {norm_article(a) for a in (info.get("articles") or []) if norm_article(a)}
                    for fn, info in affected.items()}
    out: list[RegulatoryImpact] = []
    seen: set[tuple] = set()
    for case in cases:
        cid = getattr(case, "id", "") or ""
        org = getattr(case, "org_id", "") or ""
        for kind, items in (("risk", getattr(case, "risks", None) or []),
                            ("fallback", getattr(case, "fallbacks", None) or [])):
            for it in items:
                clause = it.get("clause", "")
                for basis_field in ("legal_basis", "source"):
                    fn, art = parse_basis(it.get(basis_field, ""))
                    if not fn or fn not in affected:
                        continue
                    changed = arts_by_file[fn]
                    if changed and art and art not in changed:
                        continue        # article-level: điều được viện dẫn KHÔNG nằm trong điều bị sửa
                    key = (cid, kind, clause, fn)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(RegulatoryImpact(
                        case_id=cid, org_id=org, clause=clause, kind=kind,
                        affected_file=fn, relation=affected[fn]["relation"], new_doc_id=new_doc_id,
                        basis=it.get(basis_field, ""),
                        affected_article=art if changed else ""))
                    break       # mục này đã trúng → khỏi xét field còn lại
    return out
