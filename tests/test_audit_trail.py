"""Chế độ luật sư — HỒ SƠ KIỂM CHỨNG AI (audit trail). compile_audit_trail THUẦN, test offline."""
from legalguard.domain.audit import compile_audit_trail

_CASE = {
    "id": "abc123", "org_id": "acme", "tenant": "VN", "created_at": "2026-07-02T10:00:00+00:00",
    "source_name": "hopdong.pdf", "source_sha256": "deadbeef" * 8, "source_bytes": 1024, "text_chars": 800,
    "needs_human_review": True,
    "risks": [
        {"clause": "Điều 2 — Phạt", "risk": "Phạt 15% vượt trần 8%", "severity": "high",
         "legal_status": "illegal", "violated_law": "Điều 301 LTM 2005", "legal_basis": "Điều 301"},
        {"clause": "Điều 3 — Luật áp dụng", "risk": "Luật Đức bất lợi", "severity": "high",
         "legal_status": "unfavorable", "source": "premium_tactics.md"},
    ],
    "trace": [
        {"tool": "search_legal_knowledge", "observation": "Điều 301: mức phạt không quá 8%"},
        {"tool": "flag_risk", "observation": "Đã ghi nhận rủi ro Điều 2"},
    ],
}


def test_audit_has_all_sections_and_fingerprint():
    md = compile_audit_trail(_CASE)
    for sec in ("HỒ SƠ KIỂM CHỨNG AI", "Tài liệu được rà soát", "Phát hiện của AI",
                "Dấu vết tác nhân AI", "Kiểm soát con người", "Tuyên bố & trách nhiệm"):
        assert sec in md
    assert "deadbeef" * 8 in md                      # vân tay SHA-256 (bằng chứng đúng tài liệu)
    assert "không thay thế ý kiến pháp lý" in md      # disclaimer chống-UPL bắt buộc
    assert "Chữ ký" in md                             # ô ký kiểm chứng của luật sư


def test_audit_renders_findings_and_trace():
    md = compile_audit_trail(_CASE)
    assert "Điều 2 — Phạt" in md and "TRÁI LUẬT" in md      # risk illegal gắn nhãn
    assert "Điều 301 LTM 2005" in md                        # căn cứ (violated_law)
    assert "search_legal_knowledge" in md and "flag_risk" in md   # dấu vết agent
    assert "2 rủi ro" in md and "2 bước" in md              # đếm đúng


def test_audit_prefills_reviewer_and_note():
    md = compile_audit_trail(_CASE, reviewer="LS Nguyễn Văn A", note="Đã đối chiếu, đồng ý Điều 2")
    assert "LS Nguyễn Văn A" in md and "Đã đối chiếu, đồng ý Điều 2" in md


def test_audit_handles_empty_case():
    md = compile_audit_trail({"id": "x", "risks": [], "trace": []})
    assert "Không có rủi ro" in md and "Không có dấu vết" in md   # không vỡ khi rỗng
