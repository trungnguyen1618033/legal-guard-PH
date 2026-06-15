from legalguard.adapters.outbound.sql_outcome_repository import SqlAlchemyOutcomeRepository
from legalguard.config.container import build_service
from legalguard.domain.models import Outcome
from legalguard.domain.tenants import default_org


def _outcome(clause, result, oid):
    return Outcome(id=oid, org_id="acme", case_id="c1", clause=clause, tactic="SIAC",
                   result=result, created_at="2026-06-10T00:00:00+00:00")


def test_win_rates_weighted(tmp_path):
    repo = SqlAlchemyOutcomeRepository(f"sqlite:///{tmp_path / 'o.db'}")
    repo.record(_outcome("Trọng tài", "accepted", "1"))
    repo.record(_outcome("Trọng tài", "partial", "2"))
    repo.record(_outcome("Trọng tài", "rejected", "3"))
    repo.record(_outcome("Trọng tài", "pending", "4"))     # pending bị loại
    stats = repo.win_rates()
    assert stats["Trọng tài"]["total"] == 3                # pending không tính
    assert stats["Trọng tài"]["rate"] == 0.5               # (1+0.5+0)/3


def test_win_rates_scoped_by_org(tmp_path):
    repo = SqlAlchemyOutcomeRepository(f"sqlite:///{tmp_path / 'o.db'}")
    repo.record(_outcome("Trọng tài", "accepted", "1"))
    assert repo.win_rates(org_id="globex") == {}           # org khác → rỗng


def test_analyze_annotates_fallback_win_rate():
    svc = build_service()
    org = default_org("VN")
    svc.record_outcome(Outcome(id="x1", org_id=org.id, case_id="c", clause="Điều khoản trọng tài",
                               tactic="SIAC", result="accepted",
                               created_at="2026-06-10T00:00:00+00:00"))
    res = svc.analyze("Tranh chấp bằng trọng tài tại Bắc Kinh.", org, lang="vi")
    fb = next(f for f in res.fallbacks if f["clause"] == "Điều khoản trọng tài")
    assert fb["win_rate"] is not None      # outcome-aware ranking đã gắn win-rate
