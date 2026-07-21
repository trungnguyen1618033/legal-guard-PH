"""Test InMemoryMemory (MemoryPort) — cô lập org, recall theo đối tác/overlap, cascade erasure. Offline."""
from __future__ import annotations

from legalguard.adapters.outbound.memory_store import InMemoryMemory
from legalguard.domain.models import MemoryEpisode
from legalguard.domain.ports import MemoryPort


def _ep(org, cp, clause, content, case_id="c1", when="2026-07-21", kind="risk", eid=""):
    return MemoryEpisode(id=eid, org_id=org, counterparty=cp, kind=kind, clause=clause,
                         content=content, created_at=when, case_id=case_id)


def test_satisfies_port_protocol():
    assert isinstance(InMemoryMemory(), MemoryPort)


def test_remember_assigns_id_when_missing():
    m = InMemoryMemory()
    rid = m.remember(_ep("org1", "ACME", "Điều 5 Thanh toán", "phạt chậm 15%"))
    assert rid and len(rid) >= 8


def test_recall_org_isolation():
    m = InMemoryMemory()
    m.remember(_ep("org1", "ACME", "Thanh toán", "phạt chậm 15% trái Điều 301"))
    m.remember(_ep("org2", "ACME", "Thanh toán", "bí mật org2"))
    got = m.recall("org1", "phạt chậm thanh toán")
    assert got and all(e.org_id == "org1" for e in got)   # KHÔNG rò org2


def test_recall_ranks_same_counterparty_higher():
    m = InMemoryMemory()
    m.remember(_ep("o", "OTHER", "Thanh toán", "phạt chậm", eid="x"))
    m.remember(_ep("o", "ACME", "Thanh toán", "phạt chậm", eid="y"))
    got = m.recall("o", "phạt chậm thanh toán", counterparty="ACME", k=2)
    assert got[0].counterparty == "ACME"                  # cùng đối tác lên đầu


def test_recall_drops_irrelevant():
    m = InMemoryMemory()
    m.remember(_ep("o", "ACME", "Bảo mật", "NDA điều khoản bảo mật"))
    got = m.recall("o", "trần lãi suất vay dân sự")        # không overlap, khác đối tác
    assert got == []                                      # không inject nhiễu


def test_recall_counterparty_match_even_without_overlap():
    m = InMemoryMemory()
    m.remember(_ep("o", "ACME", "Bảo mật", "NDA"))
    got = m.recall("o", "chủ đề hoàn toàn khác", counterparty="acme")   # so lower
    assert len(got) == 1                                  # cùng đối tác vẫn recall


def test_delete_by_case_cascade():
    m = InMemoryMemory()
    m.remember(_ep("o", "ACME", "Thanh toán", "phạt", case_id="caseA"))
    m.remember(_ep("o", "ACME", "Giao hàng", "chậm giao", case_id="caseB"))
    assert m.delete_by_case("caseA") == 1
    assert all(e.case_id != "caseA" for e in m.recall("o", "phạt chậm giao", k=10))
    assert m.delete_by_case("") == 0                      # no-op an toàn
