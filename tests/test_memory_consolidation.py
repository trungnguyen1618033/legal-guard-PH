"""Test consolidation bộ nhớ (nâng ①): pure consolidate + list_by_counterparty + service upsert hồ sơ. Offline."""
from __future__ import annotations

from legalguard.adapters.outbound.memory_store import InMemoryMemory
from legalguard.domain.analysis import AnalysisService
from legalguard.domain.memory_consolidation import consolidate_counterparty
from legalguard.domain.models import MemoryEpisode


def _ep(cp, clause, content, kind="outcome", when="2026-07-22", org="o"):
    return MemoryEpisode(id="", org_id=org, counterparty=cp, kind=kind, clause=clause,
                         content=content, created_at=when, case_id="c")


class _DummyLLM:
    available = False

    def embed(self, texts):  # noqa: ANN001
        return None


# ---- pure consolidate ----
def test_consolidate_empty():
    assert consolidate_counterparty("ACME", []) == ""


def test_consolidate_groups_and_counts():
    eps = [_ep("ACME", "Thanh toán", "giữ 8% → accepted"),
           _ep("ACME", "Thanh toán", "phạt chậm → accepted"),
           _ep("ACME", "Giao hàng", "45 ngày → partial", when="2026-07-23")]
    out = consolidate_counterparty("ACME", eps)
    assert "HỒ SƠ ĐỐI TÁC ACME" in out and "3 tình tiết" in out
    assert "Thanh toán (outcome×2)" in out          # gộp + đếm đúng, Thanh toán lên trước (nhiều hơn)
    assert out.index("Thanh toán") < out.index("Giao hàng")
    assert "Gần nhất: 45 ngày" in out               # latest theo created_at


def test_consolidate_excludes_existing_profile():
    eps = [_ep("ACME", "Thanh toán", "x"), _ep("ACME", "", "hồ sơ cũ", kind="profile")]
    out = consolidate_counterparty("ACME", eps)
    assert "1 tình tiết" in out                      # bỏ episode kind=profile


# ---- list_by_counterparty (cô lập org+cp) ----
def test_list_by_counterparty_isolation():
    m = InMemoryMemory()
    m.remember(_ep("ACME", "Thanh toán", "a", org="o1"))
    m.remember(_ep("acme", "Giao hàng", "b", org="o1"))    # cùng cp (khác hoa) → tính
    m.remember(_ep("ACME", "Thanh toán", "c", org="o2"))   # org khác → loại
    m.remember(_ep("GLOBEX", "X", "d", org="o1"))          # cp khác → loại
    got = m.list_by_counterparty("o1", "ACME")
    assert len(got) == 2 and {e.content for e in got} == {"a", "b"}


# ---- service consolidate_memory: tạo 1 hồ sơ, re-run UPSERT (không phình) ----
def _svc(flag=True):
    return AnalysisService(reasoner=_DummyLLM(), kb=object(), memory=InMemoryMemory(), agentic_memory=flag)


def test_consolidate_memory_creates_profile():
    svc = _svc()
    svc.memory.remember(_ep("ACME", "Thanh toán", "giữ 8%", org="org1"))
    svc.memory.remember(_ep("ACME", "Trọng tài", "VIAC", org="org1"))
    prof = svc.consolidate_memory("org1", "ACME")
    assert "HỒ SƠ ĐỐI TÁC ACME" in prof
    profiles = [e for e in svc.memory.list_by_counterparty("org1", "ACME") if e.kind == "profile"]
    assert len(profiles) == 1 and profiles[0].content == prof


def test_consolidate_memory_upsert_no_proliferation():
    svc = _svc()
    svc.memory.remember(_ep("ACME", "Thanh toán", "x", org="org1"))
    svc.consolidate_memory("org1", "ACME")
    svc.consolidate_memory("org1", "ACME")           # gọi lại → KHÔNG tạo hồ sơ thứ 2
    profiles = [e for e in svc.memory.list_by_counterparty("org1", "ACME") if e.kind == "profile"]
    assert len(profiles) == 1                        # id cố định → upsert


def test_consolidate_memory_flag_off():
    svc = _svc(flag=False)
    svc.memory.remember(_ep("ACME", "Thanh toán", "x", org="org1"))
    assert svc.consolidate_memory("org1", "ACME") == ""    # flag OFF → no-op
