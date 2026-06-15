from legalguard.adapters.outbound.sql_case_repository import SqlAlchemyCaseRepository
from legalguard.domain.models import AnalysisCase


def _repo(tmp_path):
    return SqlAlchemyCaseRepository(f"sqlite:///{tmp_path / 'cases.db'}")


def _case(cid: str, org_id: str = "acme", tenant: str = "VN",
          created: str = "2026-06-10T00:00:00+00:00") -> AnalysisCase:
    return AnalysisCase(
        id=cid, org_id=org_id, tenant=tenant, created_at=created, lang="en",
        contract_excerpt="Arbitration in Beijing...", summary="1 risk",
        needs_human_review=True,
        risks=[{"clause": "Arbitration clause", "risk": "x", "severity": "high"}],
        fallbacks=[{"clause": "Arbitration clause", "suggestion": "SIAC", "english_reply": "We propose..."}],
        trace=[{"step": 1, "tool": "flag_risk", "arguments": {}, "observation": "ok"}],
    )


def test_save_and_get_roundtrip(tmp_path):
    repo = _repo(tmp_path)
    repo.save(_case("abc"))
    got = repo.get("abc")
    assert got is not None
    assert got.org_id == "acme" and got.tenant == "VN"
    assert got.needs_human_review is True
    assert got.risks[0]["severity"] == "high"      # JSON round-trip giữ cấu trúc


def test_get_missing_returns_none(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get("nope") is None


def test_list_by_org_orders_newest_first(tmp_path):
    repo = _repo(tmp_path)
    repo.save(_case("old", created="2026-06-01T00:00:00+00:00"))
    repo.save(_case("new", created="2026-06-09T00:00:00+00:00"))
    repo.save(_case("other", org_id="globex", created="2026-06-10T00:00:00+00:00"))
    rows = repo.list_by_org("acme")
    assert [r.id for r in rows] == ["new", "old"]   # cô lập theo công ty + sort desc
