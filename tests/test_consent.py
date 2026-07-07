"""Chế độ luật sư — MẪU VĂN BẢN ĐỒNG Ý. compile_consent THUẦN, test offline."""
from legalguard.domain.consent import compile_consent


def test_consent_fills_parties_and_date():
    md = compile_consent(party_a="Công ty TNHH ABC", party_b="LS Nguyễn Văn A",
                         date="07/07/2026", matter="Rà HĐ mua bán XNK")
    assert "Công ty TNHH ABC" in md and "LS Nguyễn Văn A" in md
    assert "07/07/2026" in md and "Rà HĐ mua bán XNK" in md
    # Có đủ điều khoản cốt lõi PDPL/nghề luật
    assert "chuyển dữ liệu tới hạ tầng AI" in md and "rút lại sự đồng ý" in md
    assert "không thay thế" in md.lower() or "KHÔNG phải dịch vụ tư vấn" in md


def test_consent_blank_when_no_params():
    md = compile_consent()
    assert "________________" in md                 # ô trống để ký tay
    assert "____/____/________" in md                # ngày trống


def test_consent_org_name_fallback_for_party_b():
    md = compile_consent(party_a="Khách X", org_name="Văn phòng LS Y")
    assert "Văn phòng LS Y" in md                    # party_b rỗng → dùng org_name


def test_consent_is_draft_warning():
    # Phải cảnh báo là DRAFT + văn bản của luật sư (không phải của Legal Guard) — tránh hiểu nhầm liability.
    md = compile_consent()
    assert "DRAFT" in md and "không phải của Legal Guard" in md
