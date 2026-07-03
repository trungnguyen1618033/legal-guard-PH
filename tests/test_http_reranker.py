import legalguard.adapters.outbound.http_reranker as hr_mod
from legalguard.adapters.outbound.http_reranker import HttpReranker


def test_unconfigured_returns_none():
    assert HttpReranker("").rerank("q", ["a", "b"]) is None
    assert HttpReranker("http://x:8080").rerank("q", []) is None


def test_maps_scores_back_to_input_order(monkeypatch):
    # TEI /rerank trả list [{index, score}] đã sắp giảm dần — adapter phải map NGƯỢC về thứ tự docs.
    captured = {}

    def fake_post_json(url, *, provider, json, timeout):
        captured["url"] = url
        captured["texts"] = json["texts"]
        return [{"index": 2, "score": 0.9}, {"index": 0, "score": 0.5}, {"index": 1, "score": 0.1}]

    monkeypatch.setattr(hr_mod, "post_json", fake_post_json)
    scores = HttpReranker("http://host:8080/").rerank("q", ["d0", "d1", "d2"])
    assert scores == [0.5, 0.1, 0.9]                 # theo thứ tự docs, KHÔNG theo thứ tự đã sắp
    assert captured["url"] == "http://host:8080/rerank"
    assert captured["texts"] == ["d0", "d1", "d2"]
