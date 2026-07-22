"""Unit test cho L3 query-router thuần `route_intent` — chọn NĂNG LỰC tất định (không LLM, không side-effect).

Kiểm: mỗi năng lực + THỨ TỰ ưu tiên (analyze > negotiate/lookup; help chỉ khi chưa vào deal…).
"""
from legalguard.adapters.inbound.channels import (
    INTENT_ANALYZE,
    INTENT_EXPORT_DOC,
    INTENT_FOLLOWUP,
    INTENT_INPUT,
    INTENT_LOOKUP,
    INTENT_NEGOTIATE,
    INTENT_TRUST,
    route_intent,
)


def R(text="", *, has_attachment=False, contract_detected=False, has_context=False,
      has_thread_context=False, in_thread=False, has_prev_review=False, has_last_case=False):
    return route_intent(text, has_attachment=has_attachment, contract_detected=contract_detected,
                        has_context=has_context, has_thread_context=has_thread_context,
                        in_thread=in_thread, has_prev_review=has_prev_review,
                        has_last_case=has_last_case)


# ── Flag-driven (không phụ thuộc regex — chắc chắn) ──
def test_empty_no_context_is_input():
    assert R("") == INTENT_INPUT


def test_contract_detected_is_analyze():
    assert R("bất kỳ nội dung nào", contract_detected=True) == INTENT_ANALYZE


def test_attachment_contract_is_analyze():
    assert R("", has_attachment=True, contract_detected=True) == INTENT_ANALYZE


def test_thread_context_is_followup():
    assert R("nhận xét điều khoản phía trên", has_thread_context=True) == INTENT_FOLLOWUP


def test_in_thread_with_deal_is_followup():
    assert R("ý này thì sao", in_thread=True, has_context=True) == INTENT_FOLLOWUP


def test_deal_plain_statement_is_followup():
    # có deal, không phải câu hỏi pháp lý chung / không phải counter → follow-up
    assert R("cảm ơn bạn nhé", has_context=True) == INTENT_FOLLOWUP


# ── Ưu tiên (robust) ──
def test_analyze_beats_negotiate_and_lookup():
    # contract_detected có ưu tiên cao hơn đàm phán/tra cứu
    assert R("Chúng tôi chỉ giảm phạt xuống 12%?", contract_detected=True,
             has_context=True) == INTENT_ANALYZE


def test_help_suppressed_when_in_deal():
    # "help" khi ĐÃ vào deal → KHÔNG ra bảng help (là hỏi tiếp) → followup
    assert R("help me hiểu điều này", has_context=True) in (INTENT_FOLLOWUP, INTENT_LOOKUP)


# ── Predicate-driven (dùng câu thực tế đã biết khớp) ──
def test_lookup_question():
    assert R("Trần lãi suất cho vay theo Bộ luật Dân sự là bao nhiêu?") == INTENT_LOOKUP


def test_negotiate_counter_offer_in_deal():
    assert R("Chúng tôi chỉ giảm phạt xuống 12% và giữ thanh toán 90 ngày.",
             has_context=True) == INTENT_NEGOTIATE


def test_export_doc_with_last_case():
    out = R("xuất file word có nhận xét", has_last_case=True)
    assert out == INTENT_EXPORT_DOC


def test_trust_query():
    assert R("độ tin cậy của bạn thế nào?") == INTENT_TRUST
