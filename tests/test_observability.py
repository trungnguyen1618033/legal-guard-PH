from legalguard.adapters.outbound.observability import NoOpObserver
from legalguard.config.container import build_service
from legalguard.domain.tenants import default_org


class _FakeObserver:
    def __init__(self):
        self.events = []

    def event(self, name, data):
        self.events.append((name, data))


def test_noop_observer_safe():
    NoOpObserver().event("x", {"a": 1})       # không lỗi


def test_analyze_emits_observability_event():
    svc = build_service()
    obs = _FakeObserver()
    svc.observer = obs
    svc.analyze("Trọng tài tại Bắc Kinh.", default_org("VN"), lang="vi")
    names = [n for n, _ in obs.events]
    assert "analysis" in names                # có telemetry cho mỗi lần rà soát
    data = next(d for n, d in obs.events if n == "analysis")
    assert data["tenant"] == "VN" and "risks" in data
