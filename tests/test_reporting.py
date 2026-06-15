from legalguard.domain.models import AnalysisResult
from legalguard.domain.reporting import render_markdown_report
from legalguard.domain.tenants import get_tenant


def _result() -> AnalysisResult:
    return AnalysisResult(
        tenant="VN",
        risks=[{"clause": "Trọng tài", "risk": "Bất lợi cho VN", "severity": "high"}],
        fallbacks=[{"clause": "Trọng tài", "suggestion": "Đề xuất SIAC Singapore",
                    "english_reply": "We propose SIAC Singapore as a neutral venue."}],
        needs_human_review=True,
        review_reasons=["rủi ro cao"],
        summary="Hợp đồng có 1 rủi ro cao.",
        trace=[],
        notes=["⚠️ Đang chạy ở chế độ STUB."],
    )


def test_report_contains_key_sections():
    md = render_markdown_report(_result(), get_tenant("VN"), "vi")
    assert "# Báo cáo Rà soát Hợp đồng" in md
    assert "Việt Nam" in md and "VIAC" in md
    assert "Trọng tài" in md
    assert "SIAC Singapore" in md           # fallback được map đúng clause
    assert "Câu gửi đối tác (EN)" in md      # câu đàm phán tiếng Anh hiển thị
    assert "Cần chuyên gia duyệt" in md      # human review hiển thị
    assert "STUB" in md                       # notes hiển thị


def test_report_handles_no_risk():
    clean = AnalysisResult("VN", [], [], False, [], "Sạch.", [], [])
    md = render_markdown_report(clean, get_tenant("VN"), "vi")
    assert "Không phát hiện điều khoản rủi ro" in md
    assert "Cần chuyên gia duyệt" not in md
