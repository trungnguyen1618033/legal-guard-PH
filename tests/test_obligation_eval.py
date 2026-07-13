"""Eval A — hàm chấm THUẦN (score_case/aggregate), test offline (không cần Qwen)."""
from evaluation.obligation_eval import aggregate, score_case


def test_score_case_all_matched_with_date():
    expected = [{"kind": "payment", "keywords": ["thanh toán", "đợt 2"], "due_date": "2026-09-01"},
                {"kind": "warranty", "keywords": ["bảo hành"]}]
    extracted = [{"kind": "payment", "description": "Thanh toán đợt 2 40%", "due_date": "2026-09-01"},
                 {"kind": "warranty", "description": "Bảo hành 12 tháng", "due_date": ""}]
    s = score_case(expected, extracted)
    assert s == {"tp": 2, "fp": 0, "fn": 0, "date_total": 1, "date_correct": 1}


def test_score_case_miss_extra_and_wrong_date():
    expected = [{"kind": "delivery", "keywords": ["bàn giao"], "due_date": "2026-10-15"},
                {"kind": "termination_notice", "keywords": ["báo chấm dứt"]}]      # sẽ bị bỏ sót
    extracted = [{"kind": "delivery", "description": "Bàn giao hạng mục", "due_date": "2026-10-20"},  # sai ngày
                 {"kind": "payment", "description": "Thanh toán abc", "due_date": ""}]                # FP
    s = score_case(expected, extracted)
    assert s["tp"] == 1 and s["fn"] == 1 and s["fp"] == 1
    assert s["date_total"] == 1 and s["date_correct"] == 0        # matched nhưng sai ngày


def test_score_case_nda_no_obligations():
    assert score_case([], []) == {"tp": 0, "fp": 0, "fn": 0, "date_total": 0, "date_correct": 0}
    # bịa ra nghĩa vụ khi HĐ không có → FP (chống bịa)
    assert score_case([], [{"kind": "payment", "description": "x"}])["fp"] == 1


def test_score_case_other_kind_is_catch_all():
    expected = [{"kind": "other", "keywords": ["đặt cọc"]}]
    extracted = [{"kind": "warranty", "description": "hoàn trả đặt cọc 15 ngày"}]   # kind khác nhưng expected=other
    assert score_case(expected, extracted)["tp"] == 1


def test_aggregate_metrics():
    agg = aggregate([{"tp": 3, "fp": 1, "fn": 1, "date_total": 2, "date_correct": 1}])
    assert agg["precision"] == 0.75 and agg["recall"] == 0.75 and agg["date_accuracy"] == 0.5
