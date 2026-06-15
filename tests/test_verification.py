from legalguard.adapters.outbound.knowledge_base import KeywordRetriever
from legalguard.domain.models import Risk
from legalguard.domain.verification import verify_risks

KB = KeywordRetriever("knowledge_base", "VN")
CONTRACT = "Arbitration in Beijing. T/T payment after 60 days."


class _Judge:
    """Judge giả trả verdict cố định."""
    name = "qwen"

    def __init__(self, available: bool, verdict: str = "YES"):
        self._avail = available
        self._verdict = verdict

    @property
    def available(self):
        return self._avail

    def complete(self, prompt, *, system=None):
        return self._verdict


def _risk(evidence="Arbitration in Beijing"):
    return Risk(clause="Arbitration clause", risk="Unfavorable venue", severity="high",
                evidence=evidence)


def test_clause_existence_passes_when_evidence_in_contract():
    risks = [_risk()]
    verify_risks(risks, CONTRACT, KB, _Judge(available=False))
    assert risks[0].verified is True            # evidence có trong hợp đồng → ok (offline)


def test_clause_existence_fails_for_hallucinated_evidence():
    risks = [_risk(evidence="Liquidated damages of $1,000,000")]  # KHÔNG có trong hợp đồng
    notes = verify_risks(risks, CONTRACT, KB, _Judge(available=False))
    assert risks[0].verified is False           # chống bịa điều khoản
    assert any("chưa được xác minh" in n for n in notes)


def test_judge_marks_unsupported_risk():
    risks = [_risk()]                            # evidence hợp lệ
    verify_risks(risks, CONTRACT, KB, _Judge(available=True, verdict="1: NO"))
    assert risks[0].verified is False            # judge bác → unverified


def test_judge_keeps_supported_risk():
    risks = [_risk()]
    verify_risks(risks, CONTRACT, KB, _Judge(available=True, verdict="1: YES"))
    assert risks[0].verified is True


def test_batched_judge_handles_multiple_risks():
    # 1 call chấm nhiều rủi ro: mục 2 bị NO, còn lại YES.
    risks = [_risk(), _risk(), _risk()]
    verify_risks(risks, CONTRACT, KB, _Judge(available=True, verdict="1: YES\n2: NO\n3: YES"))
    assert [r.verified for r in risks] == [True, False, True]
