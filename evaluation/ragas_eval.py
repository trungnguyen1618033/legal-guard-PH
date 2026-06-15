"""Lớp eval sâu bằng RAGAS — opt-in, dùng Qwen làm judge (KHÔNG chạy ở stub).

Khác với `run_eval.py` (keyword-matching, offline, free, là "fast gate" trong CI),
module này chấm chất lượng RAG bằng LLM-as-judge của RAGAS:

  • Faithfulness            — rủi ro/chiến lược có bịa so với KB không (↔ groundedness, sâu hơn)
  • Context Precision       — retriever xếp đúng chunk KB liên quan lên đầu không
  • Response Relevancy      — câu trả lời có đúng trọng tâm hợp đồng không
  (+ Context Recall + Factual Correctness nếu case có trường "reference")

Toàn bộ reference-free trừ khi golden case có "reference". Judge = Qwen qua endpoint
OpenAI-compatible (DashScope), nên KHÔNG cần OpenAI key — tái dùng QWEN_API_KEY.

Cài:  uv sync --group eval
Chạy: uv run python -m evaluation.ragas_eval
"""
from __future__ import annotations

import sys

from evaluation.run_eval import _load_golden
from legalguard.config.container import build_service
from legalguard.config.settings import settings
from legalguard.domain.tenants import default_org


def _require(cond: bool, msg: str) -> None:
    if not cond:
        print(msg)
        sys.exit(1)


def _build_judge():
    """Qwen (OpenAI-compatible DashScope) bọc thành judge LLM + embeddings cho RAGAS."""
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper

    llm = ChatOpenAI(model=settings.qwen_model, base_url=settings.qwen_base_url,
                     api_key=settings.qwen_api_key, temperature=0.0)
    # check_embedding_ctx_length=False: KHÔNG tiktoken-hoá → gửi text thô. Mặc định True khiến
    # OpenAIEmbeddings gửi mảng token-ID, endpoint DashScope (không phải OpenAI) sẽ từ chối.
    emb = OpenAIEmbeddings(model=settings.qwen_embed_model, base_url=settings.qwen_base_url,
                           api_key=settings.qwen_api_key, check_embedding_ctx_length=False)
    return LangchainLLMWrapper(llm), LangchainEmbeddingsWrapper(emb)


def _render_response(result) -> str:
    """Gộp output mà hệ thống trả cho user thành 1 câu trả lời để RAGAS chấm."""
    lines = [f"- {r['clause']}: {r['risk']} [{r.get('severity', '')}]" for r in result.risks]
    body = "\n".join(lines) if lines else "No material risks identified."
    return f"{body}\n\n{result.summary}".strip()


def _build_samples(service, top_k: int = 4) -> list[dict]:
    """Mỗi golden case → 1 sample RAGAS: contract (hỏi) / KB chunks (context) / output (đáp).

    Contexts lấy từ CHÍNH retriever agent dùng (`service.kb.for_org` — overlay + hybrid + rerank
    theo cấu hình), nên Context Precision đo đúng đối tượng. Lưu ý: dùng nguyên văn hợp đồng làm
    query là PROXY cho các truy vấn per-tool-call mà agent thực sự phát trong vòng ReAct.
    """
    org = default_org("VN")
    retriever = service.kb.for_org(org)
    samples = []
    for case in _load_golden():
        result = service.analyze(case["contract"], org, lang="en")
        contexts = [h.text for h in retriever.retrieve(case["contract"], top_k=top_k)]
        sample = {
            "user_input": case["contract"],
            "retrieved_contexts": contexts or ["(no knowledge-base context retrieved)"],
            "response": _render_response(result),
        }
        if case.get("reference"):           # bật metric reference-based khi có nhãn vàng
            sample["reference"] = case["reference"]
        samples.append(sample)
    return samples


def _aggregate(result) -> dict:
    """EvaluationResult.scores = list per-sample dict → điểm trung bình mỗi metric (bỏ NaN).

    RAGAS trả NaN cho sample judge lỗi (không raise), nên phải lọc NaN trước khi tính mean.
    """
    rows = result.scores
    if not rows:
        return {}
    out = {}
    for name in rows[0]:
        vals = [r[name] for r in rows
                if isinstance(r.get(name), (int, float)) and r[name] == r[name]]  # NaN != NaN
        out[name] = round(sum(vals) / len(vals), 3) if vals else float("nan")
    return out


def run_ragas(kb_strategy: str = "auto") -> dict:
    from ragas import EvaluationDataset, evaluate
    from ragas.metrics import Faithfulness, LLMContextPrecisionWithoutReference, ResponseRelevancy

    judge, emb = _build_judge()
    samples = _build_samples(build_service(kb_strategy=kb_strategy))

    metrics = [Faithfulness(), LLMContextPrecisionWithoutReference(), ResponseRelevancy()]
    if all("reference" in s for s in samples):   # chỉ thêm khi MỌI sample có nhãn vàng
        from ragas.metrics import FactualCorrectness, LLMContextRecall
        metrics += [LLMContextRecall(), FactualCorrectness()]

    dataset = EvaluationDataset.from_list(samples)
    result = evaluate(dataset=dataset, metrics=metrics, llm=judge, embeddings=emb)
    return _aggregate(result)   # {metric_name: mean_score}


if __name__ == "__main__":
    try:
        import ragas  # noqa: F401
    except ImportError:
        _require(False, "❌ Chưa cài RAGAS. Chạy:  uv sync --group eval")
    _require(bool(settings.qwen_api_key),
             "❌ RAGAS cần judge LLM thật (LLM-as-judge), không chạy ở stub.\n"
             "   Đặt QWEN_API_KEY trong .env rồi chạy lại.")

    scores = run_ragas()
    print(f"\n{'metric':32} {'score':>6}")
    for name, val in scores.items():
        shown = round(val, 3) if isinstance(val, (int, float)) else val
        print(f"{name:32} {shown:>6}")
