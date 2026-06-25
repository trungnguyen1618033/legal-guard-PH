from evaluation.legal_eval import (
    eval_closure,
    eval_in_force,
    eval_in_force_real,
    eval_retrieval,
)


def test_retrieval_eval_runs_offline_and_finds_articles():
    m = eval_retrieval(top_k=5)                 # keyword, offline, tất định
    assert m["cases"] >= 8
    assert m["recall@k"] >= 0.8                  # golden synthetic phải tìm được điều đúng
    assert 0.0 <= m["mrr"] <= 1.0


def test_closure_adds_recall_at_topk_1():
    c = eval_closure(top_k=1)                    # base lấy điều gốc; closure kéo điều dẫn chiếu
    assert c["closure_cases"] >= 1
    assert c["recall_on"] > c["recall_off"]      # closure phải tăng recall cụm điều
    assert c["delta"] > 0


def test_in_force_filter_metric():
    f = eval_in_force()
    assert f["still_good_law_accuracy"] == 1.0   # mặc định chỉ trả văn bản còn hiệu lực
    assert f["expired_shown_default"] is False
    assert f["expired_surfaced_on_historical"] is True


def test_in_force_real_corpus_filters_expired_tt39():
    g = eval_in_force_real()
    assert g["accuracy_on"] == 1.0               # bật lọc → 100% kết quả còn hiệu lực
    assert g["accuracy_on"] > g["accuracy_off"]  # tắt lọc → TT 39/2014 hết hiệu lực lọt vào
    assert any("tt_39_2014" in f for f in g["expired_in_off"])
