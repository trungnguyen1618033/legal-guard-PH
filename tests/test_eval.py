from evaluation.run_eval import compare, run_eval


def test_eval_runs_and_returns_metrics():
    m = run_eval()  # stub offline
    assert m["cases"] == 5
    for key in ("precision", "recall", "f1", "groundedness"):
        assert 0.0 <= m[key] <= 1.0


def test_eval_groundedness_high_in_stub():
    # Stub luôn gắn source → groundedness phải = 1.0.
    assert run_eval()["groundedness"] == 1.0


def test_eval_detects_known_categories():
    # Stub phát hiện arbitration/payment/inspection → recall không tệ.
    assert run_eval()["recall"] >= 0.8


def test_compare_strategies_and_context_cost():
    table = compare(("keyword", "full"))
    assert set(table) == {"keyword", "full"}
    # full-context nạp toàn bộ KB → nhiều chunk hơn keyword top-k (trade-off chi phí).
    assert table["full"]["avg_chunks"] > table["keyword"]["avg_chunks"]
    assert table["full"]["avg_chars"] > table["keyword"]["avg_chars"]
