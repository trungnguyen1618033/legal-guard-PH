"""Công bố độ tin cậy — nguồn chung cho /trust (web) + câu trả lời Slack."""
from legalguard.adapters.inbound.channels import _is_trust_query
from legalguard.domain.trust import format_trust_text, trust_report


def test_trust_report_structure():
    r = trust_report()
    assert r["methodology"] and r["metrics"] and r["disclaimer"]
    assert all("layer" in m and "desc" in m for m in r["methodology"])
    assert all({"name", "value", "note"} <= set(m) for m in r["metrics"])
    assert "không thay thế tư vấn" in r["disclaimer"]      # disclaimer trung thực


def test_format_trust_text_has_method_and_metrics():
    t = format_trust_text()
    assert "Độ tin cậy" in t and "Groundedness" in t and "không thay" in t.lower() or "tư vấn" in t


def test_is_trust_query_detects_meta_questions():
    assert _is_trust_query("Độ chính xác của hệ thống thế nào?")
    assert _is_trust_query("Làm sao tin được kết quả này?")
    assert _is_trust_query("accuracy?")
    assert not _is_trust_query("Mức phạt vi phạm hợp đồng tối đa bao nhiêu?")   # câu hỏi pháp lý
