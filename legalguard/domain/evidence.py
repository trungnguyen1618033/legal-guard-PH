"""Use-case evidence doanh thu (system-of-record).

Tính tổng doanh thu + breakdown theo tháng, tách riêng related-party, đếm khách thật — bằng chứng
tăng trưởng cho system-of-record.
"""
from __future__ import annotations

from legalguard.domain.models import RevenueEntry
from legalguard.domain.ports import RevenueLogPort

# Cửa sổ doanh thu theo dõi (mặc định 5–8/2026).
REVENUE_MONTHS = ("2026-05", "2026-06", "2026-07", "2026-08")


class EvidenceService:
    def __init__(self, log: RevenueLogPort) -> None:
        self.log = log

    def record_revenue(self, entry: RevenueEntry) -> None:
        self.log.record(entry)

    def summary(self) -> dict:
        entries = self.log.all()
        organic = [e for e in entries if not e.related_party]
        related = [e for e in entries if e.related_party]

        by_month = {m: 0.0 for m in REVENUE_MONTHS}
        for e in organic:
            month = e.date[:7]
            if month in by_month:
                by_month[month] += e.amount_usd

        return {
            "total_usd": round(sum(e.amount_usd for e in organic), 2),
            "by_month": {m: round(v, 2) for m, v in by_month.items()},
            "related_party_usd": round(sum(e.amount_usd for e in related), 2),
            "paying_customers": len({e.customer for e in organic}),
            "testimonials": [e.testimonial for e in organic if e.testimonial],
        }
