"""Test bi-temporal supersede memory: vị thế đối tác đổi → cũ superseded (không xóa), recall trả HIỆN TẠI.
Chạy trên CẢ InMemory lẫn SqlMemory (sqlite). Offline."""
from __future__ import annotations

import pytest

from legalguard.adapters.outbound.memory_store import InMemoryMemory
from legalguard.adapters.outbound.sql_memory_store import SqlMemory
from legalguard.domain.models import MemoryEpisode


def _ep(clause, content, cp="ACME", kind="outcome", when="2026-07-22", org="o"):
    return MemoryEpisode(id="", org_id=org, counterparty=cp, kind=kind, clause=clause,
                         content=content, created_at=when, case_id="c")


@pytest.fixture(params=["inmemory", "sql"])
def mem(request, tmp_path):
    if request.param == "inmemory":
        return InMemoryMemory()
    return SqlMemory(f"sqlite:///{tmp_path / 'bt.db'}")   # không embed_fn → lexical


def test_supersede_same_cp_clause(mem):
    id1 = mem.remember(_ep("Thanh toán", "đối tác đòi 30 ngày", when="2026-07-01"))
    id2 = mem.remember(_ep("Thanh toán", "đối tác chịu 45 ngày", when="2026-07-20"))
    cur = mem.recall("o", "thanh toán ngày", counterparty="ACME")
    assert [e.id for e in cur] == [id2]                         # chỉ HIỆN TẠI (ep2)
    hist = mem.recall("o", "thanh toán ngày", counterparty="ACME", include_history=True)
    assert {e.id for e in hist} == {id1, id2}                   # include_history → cả 2
    old = [e for e in hist if e.id == id1][0]
    assert old.valid_to and old.superseded_by == id2            # provenance: cũ trỏ tới mới


def test_different_clause_not_superseded(mem):
    mem.remember(_ep("Thanh toán", "x", when="2026-07-01"))
    mem.remember(_ep("Giao hàng", "y", when="2026-07-02"))      # điều khoản KHÁC → không supersede
    cur = mem.recall("o", "thanh toán giao hàng", counterparty="ACME", k=10)
    assert len(cur) == 2


def test_empty_clause_no_supersede(mem):
    mem.remember(_ep("", "vòng đàm phán 1", kind="negotiation", when="2026-07-01"))
    mem.remember(_ep("", "vòng đàm phán 2", kind="negotiation", when="2026-07-02"))
    cur = mem.recall("o", "vòng đàm phán", counterparty="ACME", k=10)
    assert len(cur) == 2                                        # clause rỗng → KHÔNG supersede nhau


def test_list_by_counterparty_current_only(mem):
    mem.remember(_ep("Thanh toán", "cũ", when="2026-07-01"))
    mem.remember(_ep("Thanh toán", "mới", when="2026-07-20"))
    assert len(mem.list_by_counterparty("o", "ACME")) == 1              # mặc định chỉ HIỆN TẠI
    assert len(mem.list_by_counterparty("o", "ACME", include_history=True)) == 2
