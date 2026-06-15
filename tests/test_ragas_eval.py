"""Test offline cho lớp eval RAGAS — KHÔNG cần cài group `eval` cũng chạy được.

RAGAS chỉ import bên trong `run_ragas`/`_build_judge` (cần judge LLM thật), nên phần
dựng sample (`_build_samples`, `_render_response`) chạy hoàn toàn ở stub → vào được CI.
"""
from types import SimpleNamespace

from evaluation.ragas_eval import _aggregate, _build_samples, _render_response
from evaluation.run_eval import _load_golden
from legalguard.config.container import build_service


def test_render_response_lists_risks_then_summary():
    result = SimpleNamespace(
        risks=[{"clause": "Arbitration", "risk": "Beijing venue", "severity": "high"}],
        summary="Propose a neutral seat.",
    )
    text = _render_response(result)
    assert "Arbitration: Beijing venue [high]" in text
    assert text.strip().endswith("Propose a neutral seat.")


def test_render_response_handles_no_risks():
    text = _render_response(SimpleNamespace(risks=[], summary="All clear."))
    assert "No material risks identified." in text


def test_build_samples_offline_shape():
    samples = _build_samples(build_service(kb_strategy="keyword"))
    assert len(samples) == len(_load_golden())
    for s in samples:
        assert s["user_input"]                       # contract = câu hỏi
        assert s["retrieved_contexts"]               # luôn có ít nhất 1 (placeholder nếu rỗng)
        assert s["response"]                         # output đã render


def test_build_samples_carries_reference_when_present():
    # golden.json đã có 'reference' cho mọi case → bật được metric reference-based.
    samples = _build_samples(build_service(kb_strategy="keyword"))
    assert all("reference" in s and s["reference"] for s in samples)


def test_aggregate_means_and_skips_nan():
    # EvaluationResult.scores = list per-sample dict; mean bỏ qua NaN (judge lỗi).
    nan = float("nan")
    result = SimpleNamespace(scores=[
        {"faithfulness": 1.0, "answer_relevancy": 0.8},
        {"faithfulness": nan, "answer_relevancy": 0.6},
    ])
    assert _aggregate(result) == {"faithfulness": 1.0, "answer_relevancy": 0.7}


def test_aggregate_empty_is_safe():
    assert _aggregate(SimpleNamespace(scores=[])) == {}
