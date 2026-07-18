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


def test_flagship_sem_shared_by_model_not_role():
    """Cap theo MODEL: reasoner + lookup_pit (flagship) chia sẻ CÙNG sem; judge (flash) None. Env đặt
    fast-review=flagship → fast_review_llm cũng dùng CHUNG sem (không bỏ sót). flash/plus → None."""
    from legalguard.config.container import build_service
    from legalguard.config.settings import Settings
    cfg = Settings(qwen_api_key="k", max_flagship_concurrency=6,
                   qwen_fast_review_model="qwen3.7-max")   # ép fast-review = flagship
    svc = build_service(cfg)
    assert svc.reasoner._sem is not None                       # flagship có sem
    assert svc.lookup_pit_llm._sem is svc.reasoner._sem        # CHUNG 1 sem (cap toàn tiến trình)
    assert svc.fast_review_llm._sem is svc.reasoner._sem       # fast-review flagship → cũng cap (gap đã vá)
    assert svc.judge._sem is None                              # flash KHÔNG bị cap oan


def test_no_sem_when_disabled():
    """max_flagship_concurrency=0 → tắt hẳn (flagship cũng không giới hạn)."""
    from legalguard.config.container import build_service
    from legalguard.config.settings import Settings
    svc = build_service(Settings(qwen_api_key="k", max_flagship_concurrency=0))
    assert svc.reasoner._sem is None


def test_sem_caps_end_to_end_through_analyze(monkeypatch):
    """E2E: analyze mode=fast (map-reduce nhiều cửa sổ SONG SONG) + flagship + sem=2 → peak call ≤2 (cap
    xuyên suốt luồng analyze→map-reduce→adapter→_post_chat, không chỉ unit adapter)."""
    import json as _json
    import legalguard.adapters.outbound.qwen as _q
    from legalguard.config.container import build_service
    from legalguard.config.settings import Settings
    from legalguard.domain.tenants import Organization

    peak = cur = 0
    lock = threading.Lock()
    FASTJSON = _json.dumps({"risks": [{"clause": "Điều 5", "risk": "phạt cao", "severity": "high"}],
                            "fallbacks": [], "strategy": "x"}, ensure_ascii=False)

    def fake_post(url, **k):
        nonlocal peak, cur
        with lock:
            cur += 1
            peak = max(peak, cur)
        time.sleep(0.1)
        with lock:
            cur -= 1
        return {"choices": [{"message": {"content": FASTJSON}}]}

    monkeypatch.setattr(_q, "post_json", fake_post)
    cfg = Settings(qwen_api_key="k", max_flagship_concurrency=2, qwen_fast_review_model="qwen3.7-max")
    svc = build_service(cfg)
    svc.legal_basis_grounding = svc.illegal_detection = svc.nli_verification = False
    svc.auto_counter_on_analyze = False
    long_c = "Điều 5. Phạt vi phạm hợp đồng 30 phần trăm giá trị. " * 8000   # ≥4 cửa sổ fast
    svc.analyze(long_c, Organization(id="default", country="VN"), lang="vi", mode="fast")
    assert 1 <= peak <= 2, f"cap sem=2 xuyên analyze SAI: peak={peak}"
