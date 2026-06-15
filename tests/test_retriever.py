from legalguard.adapters.outbound.knowledge_base import (
    FullContextRetriever,
    HybridRetriever,
    KeywordRetriever,
    RerankRetriever,
    build_retriever,
)

KB = "knowledge_base"


class _StubLLM:
    name = "qwen"

    def __init__(self, available: bool):
        self._avail = available

    @property
    def available(self):
        return self._avail

    def complete(self, prompt, *, system=None):
        return "[STUB]"


def test_keyword_retriever_finds_arbitration():
    r = KeywordRetriever(KB, "VN")
    hits = r.retrieve("trọng tài Bắc Kinh", top_k=3)
    assert hits, "phải tìm được snippet liên quan trọng tài"
    assert any("trọng tài" in h.text.lower() for h in hits)


def test_keyword_retriever_empty_on_unknown_tenant():
    assert KeywordRetriever(KB, "ZZ").retrieve("bất kỳ") == []


def test_build_retriever_keyword_when_no_embed():
    assert isinstance(build_retriever(KB, "VN", embed_fn=None), KeywordRetriever)


def test_build_retriever_fallback_when_embed_raises():
    def broken(_texts):
        raise RuntimeError("embed down")

    assert isinstance(build_retriever(KB, "VN", embed_fn=broken), KeywordRetriever)


def _fake_embed(texts):
    keys = ("trọng tài", "thanh toán", "kiểm định")
    return [[float(k in t.lower()) for k in keys] for t in texts]


def test_hybrid_retriever_ranks_by_fusion():
    r = build_retriever(KB, "VN", embed_fn=_fake_embed)
    assert isinstance(r, HybridRetriever)            # keyword + embedding (RRF)
    hits = r.retrieve("trọng tài", top_k=1)
    assert hits and "trọng tài" in hits[0].text.lower()


def test_full_context_returns_entire_kb():
    r = build_retriever(KB, "VN", strategy="full")
    assert isinstance(r, FullContextRetriever)
    all_hits = r.retrieve("bất kỳ query nào", top_k=2)   # bỏ qua top_k → trả hết
    assert len(all_hits) >= 10                            # ma trận ~12 mục


def test_reranker_wraps_and_passthrough_when_llm_offline():
    r = build_retriever(KB, "VN", embed_fn=_fake_embed, reranker_llm=_StubLLM(available=False))
    assert isinstance(r, RerankRetriever)            # có wrap rerank
    hits = r.retrieve("trọng tài", top_k=2)          # llm offline → passthrough, vẫn trả kết quả
    assert hits and any("trọng tài" in h.text.lower() for h in hits)
