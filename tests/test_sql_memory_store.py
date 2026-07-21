"""Test SqlMemory (MemoryPort bền) — bậc thang semantic/lexical, cô lập org, cascade, bền qua boot. Offline."""
from __future__ import annotations

from legalguard.adapters.outbound.sql_memory_store import SqlMemory
from legalguard.domain.models import MemoryEpisode
from legalguard.domain.ports import MemoryPort


def _ep(org, cp, clause, content, case_id="c1", when="2026-07-21", kind="risk", eid=""):
    return MemoryEpisode(id=eid, org_id=org, counterparty=cp, kind=kind, clause=clause,
                         content=content, created_at=when, case_id=case_id)


def _store(tmp_path, embed_fn=None):
    return SqlMemory(f"sqlite:///{tmp_path / 'mem.db'}", embed_fn=embed_fn)


def test_satisfies_port_protocol(tmp_path):
    assert isinstance(_store(tmp_path), MemoryPort)


def test_lexical_recall_and_org_isolation(tmp_path):
    m = _store(tmp_path)                                   # không embed_fn → lexical
    m.remember(_ep("org1", "ACME", "Thanh toán", "phạt chậm 15% trái Điều 301"))
    m.remember(_ep("org2", "ACME", "Thanh toán", "bí mật org2"))
    got = m.recall("org1", "phạt chậm thanh toán")
    assert got and all(e.org_id == "org1" for e in got)   # KHÔNG rò org2


def test_lexical_drops_irrelevant(tmp_path):
    m = _store(tmp_path)
    m.remember(_ep("o", "ACME", "Bảo mật", "NDA điều khoản bảo mật"))
    assert m.recall("o", "trần lãi suất vay dân sự") == []  # khác chủ đề + khác đối tác → không nhiễu


def test_counterparty_boost_ranks_first(tmp_path):
    m = _store(tmp_path)
    m.remember(_ep("o", "OTHER", "Thanh toán", "phạt chậm", eid="x"))
    m.remember(_ep("o", "ACME", "Thanh toán", "phạt chậm", eid="y"))
    got = m.recall("o", "phạt chậm", counterparty="acme", k=2)
    assert got[0].counterparty == "ACME"


def test_semantic_recall_with_embedder(tmp_path):
    # embed giả TẤT ĐỊNH: vector 2 chiều theo từ khóa → 'phạt' gần 'phạt' hơn 'giao hàng'
    def embed(texts):
        out = []
        for t in texts:
            t = t.lower()
            out.append([1.0 if "phạt" in t else 0.0, 1.0 if "giao" in t else 0.0])
        return out

    m = _store(tmp_path, embed_fn=embed)
    m.remember(_ep("o", "A", "Phạt vi phạm", "mức phạt 12%", eid="pen"))
    m.remember(_ep("o", "A", "Giao hàng", "giao hàng chậm", eid="del"))
    got = m.recall("o", "quy định phạt", k=2)
    assert got and got[0].id == "pen"                     # semantic đưa ca 'phạt' lên đầu


def test_delete_by_case_cascade(tmp_path):
    m = _store(tmp_path)
    m.remember(_ep("o", "ACME", "Thanh toán", "phạt", case_id="A"))
    m.remember(_ep("o", "ACME", "Giao hàng", "chậm", case_id="B"))
    assert m.delete_by_case("A") == 1
    assert all(e.case_id != "A" for e in m.recall("o", "phạt chậm", k=10))
    assert m.delete_by_case("") == 0                      # no-op an toàn


def test_persists_across_instances(tmp_path):
    _store(tmp_path).remember(_ep("o", "ACME", "Thanh toán", "phạt chậm", eid="z"))
    got = _store(tmp_path).recall("o", "phạt chậm")       # instance MỚI (mô phỏng restart) → còn dữ liệu
    assert any(e.id == "z" for e in got)
