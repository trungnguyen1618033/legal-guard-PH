"""Kho embedding bền: tính 1 lần, tái dùng qua boot (mở khóa corpus lớn)."""
from legalguard.adapters.outbound.embedding_store import SqlEmbeddingStore


def _store(tmp_path):
    return SqlEmbeddingStore(f"sqlite:///{tmp_path / 'emb.db'}")


def test_get_or_embed_only_embeds_missing(tmp_path):
    calls: list[list[str]] = []

    def embed(texts):                       # đếm text thực sự gửi đi embed
        calls.append(list(texts))
        return [[float(len(t)), 1.0] for t in texts]

    st = _store(tmp_path)
    v1 = st.get_or_embed(["alpha", "beta", "gamma"], embed)
    assert len(v1) == 3 and calls[-1] == ["alpha", "beta", "gamma"]   # lần đầu embed cả 3

    v2 = st.get_or_embed(["alpha", "beta", "gamma"], embed)
    assert v2 == v1 and len(calls) == 1     # lần 2: KHÔNG embed lại (nạp từ DB)

    st.get_or_embed(["alpha", "beta", "gamma", "delta"], embed)
    assert calls[-1] == ["delta"]           # chỉ embed chunk MỚI (incremental)


def test_get_or_embed_persists_across_instances(tmp_path):
    embed = lambda ts: [[1.0, 0.0] for _ in ts]  # noqa: E731
    SqlEmbeddingStore(f"sqlite:///{tmp_path / 'p.db'}").get_or_embed(["x"], embed)
    calls = []

    def embed2(ts):
        calls.append(list(ts))
        return [[1.0, 0.0] for _ in ts]

    # instance MỚI (mô phỏng restart) → đọc lại từ DB, KHÔNG embed
    SqlEmbeddingStore(f"sqlite:///{tmp_path / 'p.db'}").get_or_embed(["x"], embed2)
    assert calls == []                       # boot lại không embed lại → giải đúng bài toán scale


def test_get_or_embed_returns_none_when_offline(tmp_path):
    assert _store(tmp_path).get_or_embed(["a"], lambda ts: None) is None


def test_rank_cosine_topk():
    vecs = [[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]]
    top = SqlEmbeddingStore.rank([1.0, 0.0], vecs, top_k=2)
    assert [i for i, _ in top] == [0, 2]     # gần [1,0] nhất: vec0 rồi vec2


def test_embedding_retriever_reuses_store_across_restart(tmp_path):
    # EmbeddingRetriever + store: instance #2 (mô phỏng restart) KHÔNG embed lại KB → boot nhanh.
    from legalguard.adapters.outbound.knowledge_base import EmbeddingRetriever
    st = _store(tmp_path)
    n_embedded = []

    def embed(texts):
        n_embedded.append(len(texts))
        return [[float(len(t) % 7), 1.0] for t in texts]

    r1 = EmbeddingRetriever("knowledge_base", "VN", embed, store=st)
    assert n_embedded and n_embedded[0] > 0          # lần đầu: embed các chunk KB
    first = sum(n_embedded)
    EmbeddingRetriever("knowledge_base", "VN", embed, store=st)   # "restart"
    assert sum(n_embedded) == first                  # lần 2: KHÔNG embed thêm chunk nào (nạp từ store)
    assert r1.retrieve("phạt vi phạm", top_k=2)       # vẫn truy hồi được
