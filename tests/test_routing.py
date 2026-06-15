from legalguard.config.container import build_service
from legalguard.domain.tenants import default_org

ORG = default_org("VN")


def test_short_contract_uses_fast_route():
    res = build_service().analyze("Arbitration in Beijing.", ORG)
    assert any("Route: fast" in n for n in res.notes)


def test_long_contract_is_chunked():
    long = ("Arbitration in Beijing. T/T payment after 60 days. " * 200)  # > 6000 ký tự
    res = build_service().analyze(long, ORG)
    assert any("chia" in n for n in res.notes)          # đã chia nhiều đoạn
    # Dedupe theo clause → không nhân bản dù lặp nhiều cửa sổ.
    clauses = [r["clause"] for r in res.risks]
    assert len(clauses) == len(set(clauses))
