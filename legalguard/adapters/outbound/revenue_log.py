"""Adapter sổ doanh thu lưu CSV → implement RevenueLogPort.

CSV đủ cho giai đoạn này (dễ mở bằng Excel, dễ làm evidence). Sau có thể đổi sang
Postgres bằng một adapter khác, domain không đổi.
"""
from __future__ import annotations

import csv
from pathlib import Path

from legalguard.domain.models import RevenueEntry

_FIELDS = ["customer", "date", "amount_usd", "contract_ref", "testimonial", "related_party"]


class CsvRevenueLog:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def record(self, entry: RevenueEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not self.path.exists()
        with self.path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=_FIELDS)
            if new_file:
                w.writeheader()
            w.writerow({
                "customer": entry.customer,
                "date": entry.date,
                "amount_usd": entry.amount_usd,
                "contract_ref": entry.contract_ref,
                "testimonial": entry.testimonial,
                "related_party": entry.related_party,
            })

    def all(self) -> list[RevenueEntry]:
        if not self.path.exists():
            return []
        with self.path.open(newline="", encoding="utf-8") as f:
            return [
                RevenueEntry(
                    customer=row["customer"],
                    date=row["date"],
                    amount_usd=float(row["amount_usd"] or 0),
                    contract_ref=row.get("contract_ref", ""),
                    testimonial=row.get("testimonial", ""),
                    related_party=str(row.get("related_party", "")).strip().lower() == "true",
                )
                for row in csv.DictReader(f)
            ]
