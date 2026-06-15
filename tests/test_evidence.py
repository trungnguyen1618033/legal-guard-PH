from legalguard.adapters.outbound.revenue_log import CsvRevenueLog
from legalguard.domain.evidence import EvidenceService
from legalguard.domain.models import RevenueEntry


class InMemoryLog:
    def __init__(self):
        self._items = []

    def record(self, entry):
        self._items.append(entry)

    def all(self):
        return list(self._items)


def test_summary_excludes_related_party_and_buckets_by_month():
    log = InMemoryLog()
    svc = EvidenceService(log)
    svc.record_revenue(RevenueEntry("SME A", "2026-06-10", 50, testimonial="Rất hữu ích"))
    svc.record_revenue(RevenueEntry("SME B", "2026-07-01", 100))
    svc.record_revenue(RevenueEntry("SME A", "2026-07-15", 50))            # khách cũ
    svc.record_revenue(RevenueEntry("Bạn thân", "2026-06-20", 999, related_party=True))

    s = svc.summary()
    assert s["total_usd"] == 200.0                  # loại related-party
    assert s["related_party_usd"] == 999.0
    assert s["by_month"]["2026-06"] == 50.0
    assert s["by_month"]["2026-07"] == 150.0
    assert s["paying_customers"] == 2               # A, B (đếm distinct, bỏ related)
    assert "Rất hữu ích" in s["testimonials"]


def test_revenue_outside_window_not_in_month_buckets():
    log = InMemoryLog()
    svc = EvidenceService(log)
    svc.record_revenue(RevenueEntry("SME C", "2026-12-01", 70))
    s = svc.summary()
    assert s["total_usd"] == 70.0                   # vẫn tính tổng
    assert sum(s["by_month"].values()) == 0.0       # nhưng ngoài cửa sổ 5–8


def test_csv_revenue_log_roundtrip(tmp_path):
    path = tmp_path / "rev.csv"
    log = CsvRevenueLog(str(path))
    log.record(RevenueEntry("SME A", "2026-06-10", 50, related_party=False))
    log.record(RevenueEntry("Bạn thân", "2026-06-11", 30, related_party=True))
    rows = log.all()
    assert len(rows) == 2
    assert rows[0].amount_usd == 50.0 and rows[0].related_party is False
    assert rows[1].related_party is True
