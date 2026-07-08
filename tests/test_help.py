"""Help/hướng dẫn — Slack intent (_is_help_query) + web /help + domain format_help_text (thuần)."""
from fastapi.testclient import TestClient

from legalguard.adapters.inbound.channels import _is_help_query
from legalguard.domain.help import format_help_text, help_sections


def test_is_help_query_matches_common_phrasings():
    for t in ["help", "/help", "trợ giúp", "hướng dẫn", "How to use", "hỗ trợ", "dùng thế nào"]:
        assert _is_help_query(t), t


def test_is_help_query_ignores_normal_questions():
    # Câu hỏi pháp lý / tin thường KHÔNG được nuốt vào help.
    for t in ["Phạt vi phạm hợp đồng tối đa bao nhiêu %?", "Chúng tôi không đồng ý điều khoản này",
              "Điều 301 quy định gì"]:
        assert not _is_help_query(t), t


def test_format_help_text_covers_all_four_sections():
    txt = format_help_text("slack")
    assert "HƯỚNG DẪN" in txt
    assert "trợ lý pháp lý AI" in txt                            # (1) giới thiệu
    assert "Chức năng chính" in txt and "party-aware" in txt     # (2) chức năng
    assert "Bắt đầu thế nào" in txt and "Tra cứu luật" in txt    # (3) cách dùng
    assert "Gặp sự cố" in txt and "Không đọc được file" in txt   # (4) sự cố
    assert "AI hỗ trợ" in txt                                    # minh bạch AI


def test_format_help_text_channel_differs_input_step():
    assert "Dán nội dung hợp đồng vào đây" in format_help_text("slack")
    assert "trang Rà soát" in format_help_text("web")


def test_format_help_text_optional_support_contact():
    assert "acme@x.vn" in format_help_text("slack", support_contact="acme@x.vn")
    assert "Cần hỗ trợ thêm" not in format_help_text("slack")   # trống → ẩn


def test_help_sections_structured_for_web():
    s = help_sections()
    assert {"intro", "features", "usage", "trouble"} <= s.keys()
    assert isinstance(s["intro"], str) and s["intro"]
    assert all(len(row) == 3 for row in s["features"] + s["usage"] + s["trouble"])  # (icon, title, desc)
    assert len(s["features"]) >= 6                                   # danh sách chức năng đầy đủ


def test_web_help_endpoint_renders_guide(tmp_path):
    from legalguard.adapters.inbound.http import build_api
    from legalguard.adapters.outbound.document_parser import PdfDocxParser
    from legalguard.adapters.outbound.revenue_log import CsvRevenueLog
    from legalguard.config.container import build_service
    from legalguard.domain.evidence import EvidenceService

    evidence = EvidenceService(CsvRevenueLog(str(tmp_path / "r.csv")))
    client = TestClient(build_api(build_service(), PdfDocxParser(), evidence, api_orgs={}))
    r = client.get("/help")
    assert r.status_code == 200
    body = r.text
    assert "Giới thiệu" in body and "Chức năng chính" in body and "Gặp sự cố" in body
    assert "Rà soát hợp đồng" in body
