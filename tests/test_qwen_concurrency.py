"""Bounded concurrency flagship (threading.Semaphore) — chống burst 429 khi tải nhiều user/cửa sổ."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import legalguard.adapters.outbound.qwen as q
from legalguard.adapters.outbound.qwen import QwenAdapter


def test_flagship_semaphore_caps_concurrency(monkeypatch):
    """sem=N → tối đa N call flagship SONG SONG dù nhiều thread gọi cùng lúc."""
    peak = cur = 0
    lock = threading.Lock()

    def fake_post(url, **k):
        nonlocal peak, cur
        with lock:
            cur += 1
            peak = max(peak, cur)
        time.sleep(0.15)
        with lock:
            cur -= 1
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(q, "post_json", fake_post)
    ad = QwenAdapter("key", "http://x", "qwen3.7-max", sem=threading.Semaphore(2))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: ad.complete("hi"), range(8)))
    assert peak <= 2, f"vượt trần concurrency: peak={peak}"


def test_no_semaphore_unbounded(monkeypatch):
    """sem=None (flash/plus) → KHÔNG giới hạn (nhiều thread chạy song song thật)."""
    peak = cur = 0
    lock = threading.Lock()

    def fake_post(url, **k):
        nonlocal peak, cur
        with lock:
            cur += 1
            peak = max(peak, cur)
        time.sleep(0.15)
        with lock:
            cur -= 1
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(q, "post_json", fake_post)
    ad = QwenAdapter("key", "http://x", "qwen-flash")   # sem=None
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda _: ad.complete("hi"), range(5)))
    assert peak >= 2, f"không giới hạn nhưng peak chỉ {peak} (mong ≥2 song song)"
