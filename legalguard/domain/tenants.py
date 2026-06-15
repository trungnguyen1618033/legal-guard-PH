"""Multi-tenancy 2 trục (domain):

- Tenant (Jurisdiction) = QUỐC GIA → chọn KB luật (VN, ID, TH...).
- Organization = CÔNG TY (khách hàng) → cô lập dữ liệu + tùy biến (KB overlay riêng).
  Mỗi công ty thuộc 1 quốc gia. Cô lập dữ liệu theo org_id, KHÔNG theo quốc gia.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tenant:
    """Jurisdiction = quốc gia."""
    id: str
    country: str
    currency: str
    arbitration_body: str
    language: str


@dataclass(frozen=True)
class Organization:
    """Công ty khách hàng. `country` chọn jurisdiction; overlay KB riêng (nếu có)."""
    id: str
    country: str = "VN"
    name: str = ""


def default_org(country: str = "VN") -> Organization:
    """Org mặc định khi auth tắt (dev/test)."""
    return Organization(id="default", country=country.upper())


TENANTS: dict[str, Tenant] = {
    "VN": Tenant(id="VN", country="Việt Nam", currency="VND", arbitration_body="VIAC", language="vi"),
    # "ID": Tenant(id="ID", country="Indonesia", currency="IDR", arbitration_body="BANI", language="id"),
    # "TH": Tenant(id="TH", country="Thái Lan", currency="THB", arbitration_body="THAC", language="th"),
}


def get_tenant(tenant_id: str) -> Tenant:
    try:
        return TENANTS[tenant_id.upper()]
    except KeyError:
        raise ValueError(f"Tenant chưa hỗ trợ: {tenant_id}. Có: {list(TENANTS)}") from None
