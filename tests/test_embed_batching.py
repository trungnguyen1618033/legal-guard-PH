"""QwenAdapter.embed phải chia batch ≤10 texts/request (giới hạn DashScope)."""
from legalguard.adapters.outbound import qwen as qwen_mod
from legalguard.adapters.outbound.qwen import QwenAdapter


def test_embed_batches_at_most_10_texts_per_request(monkeypatch):
    calls: list[int] = []

    def fake_post_json(url, *, provider, headers, json, timeout):
        batch = json["input"]
        calls.append(len(batch))
        return {"data": [{"embedding": [0.1, 0.2]} for _ in batch]}

    monkeypatch.setattr(qwen_mod, "post_json", fake_post_json)
    adapter = QwenAdapter(api_key="k", base_url="http://x", model="m")

    vectors = adapter.embed([f"chunk {i}" for i in range(14)])   # KB hiện 14 chunks

    assert len(vectors) == 14                  # đủ vector cho mọi chunk, đúng thứ tự gọi
    assert calls == [10, 4]                    # 2 request: 10 + 4
    assert all(n <= 10 for n in calls)


def test_embed_without_key_returns_none():
    assert QwenAdapter(api_key="", base_url="http://x", model="m").embed(["a"]) is None


def test_embed_truncates_long_and_replaces_empty(monkeypatch):
    # Bug scale: chunk quá dài (VB auto-ingest) → HTTP 400. Fix: cắt input + thay rỗng = ' '.
    seen: list[str] = []

    def fake_post_json(url, *, provider, headers, json, timeout):
        seen.extend(json["input"])
        return {"data": [{"embedding": [0.0]} for _ in json["input"]]}

    monkeypatch.setattr(qwen_mod, "post_json", fake_post_json)
    adapter = QwenAdapter(api_key="k", base_url="http://x", model="m")
    adapter.embed(["x" * 20000, "", "ngắn"])
    assert len(seen[0]) == adapter._EMBED_MAX_CHARS   # input dài bị cắt
    assert seen[1] == " "                              # rỗng → ' ' (API từ chối rỗng)
    assert seen[2] == "ngắn"                           # bình thường giữ nguyên
