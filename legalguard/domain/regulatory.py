"""Regulatory change intelligence — chủ động: VB pháp luật MỚI → ảnh hưởng HĐ nào → cảnh báo.

Đây là moat "system-of-record": ta đã lưu các case rà soát kèm CĂN CỨ PHÁP LÝ tất định
(`legal_basis = 'file.md#Điều N: …'`). Khi một văn bản mới sửa đổi/thay thế/hướng dẫn một văn
bản cũ, mọi case từng viện dẫn văn bản cũ ĐỀU có nguy cơ lỗi thời → cảnh báo khách rà soát lại.

Logic ở đây THUẦN (offline, test được): nhận tập file bị tác động + các case (dict đã lưu) → liệt kê
mục (risk/fallback) viện dẫn file đó. Phần "VB mới → file bị tác động" do KB provider cung cấp
(`affected_files`, suy từ front-matter quan hệ amends/replaces/guides).
"""
from __future__ import annotations

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


def parse_basis_file(basis: str) -> str:
    """Lấy tên FILE từ căn cứ 'file.md#Điều N: …' hoặc 'file.md#Điều N' (rỗng nếu không có '#')."""
    if not basis or "#" not in basis:
        return ""
    return basis.split("#", 1)[0].strip()


def scan_cases(cases: list, affected: dict[str, str], new_doc_id: str = "") -> list[RegulatoryImpact]:
    """Quét case (dict đã lưu) → mục viện dẫn file trong `affected` (={filename: relation}).

    Đọc cả `legal_basis` (căn cứ tất định) lẫn `source` của từng risk/fallback. Mỗi (case, kind,
    clause, file) chỉ báo 1 lần (khử trùng)."""
    if not affected:
        return []
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
                    fn = parse_basis_file(it.get(basis_field, ""))
                    if fn and fn in affected:
                        key = (cid, kind, clause, fn)
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(RegulatoryImpact(
                            case_id=cid, org_id=org, clause=clause, kind=kind,
                            affected_file=fn, relation=affected[fn], new_doc_id=new_doc_id,
                            basis=it.get(basis_field, "")))
                        break       # mục này đã trúng → khỏi xét field còn lại
    return out
