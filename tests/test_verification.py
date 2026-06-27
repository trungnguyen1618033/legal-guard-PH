from legalguard.adapters.outbound.knowledge_base import KeywordRetriever
from legalguard.domain.models import Risk
from legalguard.domain.verification import nli_contradicts, verify_risks

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


def test_clause_existence_tolerates_quotes_and_whitespace():
    # Bug thật: agent bọc evidence trong ngoặc + xuống dòng khác → VẪN phải khớp (sửa false-negative).
    r = _risk(evidence='  "Arbitration   in\nBeijing."  ')
    verify_risks([r], CONTRACT, KB, _Judge(available=False))
    assert r.verified is True


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


# ---- Phase B: nli_contradicts (phát hiện TRÁI LUẬT có grounding) ----
def test_contradicts_true_when_judge_says_yes():
    assert nli_contradicts("Phạt 15%", "Phạt không quá 8%", _Judge(True, "YES")) is True


def test_contradicts_false_when_judge_says_no():
    assert nli_contradicts("Phạt 5%", "Phạt không quá 8%", _Judge(True, "NO")) is False


def test_contradicts_none_when_judge_offline():
    # Judge offline → None (không kết luận) → KHÔNG gắn illegal (bảo thủ).
    assert nli_contradicts("Phạt 15%", "Phạt không quá 8%", _Judge(False)) is None


def test_contradicts_none_on_ambiguous_answer():
    # Đáp mơ hồ (không YES/NO) → None, không suy diễn trái luật.
    assert nli_contradicts("x", "y", _Judge(True, "có thể tùy trường hợp")) is None


def test_contradicts_prefers_no_when_both_words_present():
    # Vừa có NO vừa có YES → ưu tiên NO (thận trọng, tránh gắn illegal sai).
    assert nli_contradicts("x", "y", _Judge(True, "NO, không phải YES")) is False


def test_contradicts_none_on_empty_inputs():
    assert nli_contradicts("", "điều luật", _Judge(True, "YES")) is None
    assert nli_contradicts("clause", "", _Judge(True, "YES")) is None
