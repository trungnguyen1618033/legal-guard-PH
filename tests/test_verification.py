from legalguard.adapters.outbound.knowledge_base import KeywordRetriever
from legalguard.domain.models import Risk
from legalguard.domain.verification import (
    elbow_cutoff, nli_contradicts, sources_answer_question, verify_risks,
)


def test_elbow_cutoff_denoises_after_clear_gap():
    # PIT hóa-đơn: 2 chunk luật đúng (điểm cao) rồi tụt sang nhiễu → giữ đúng cụm 2.
    assert elbow_cutoff([28.7, 26.2, 19.7, 19.3, 19.1]) == 2


def test_elbow_cutoff_keeps_all_when_scores_decline_smoothly():
    # Giảm đều → không có khuỷu rõ → giữ hết (không over-cut evidence hợp lệ).
    assert elbow_cutoff([20.0, 19.0, 18.0, 17.0]) == 4


def test_elbow_cutoff_edge_cases():
    assert elbow_cutoff([]) == 0
    assert elbow_cutoff([5.0]) == 1
    assert elbow_cutoff([50.0, 10.0, 9.0, 8.0]) == 1        # khuỷu rất sớm → giữ 1
    assert elbow_cutoff([20.0, 19.0], min_keep=2) == 2      # tôn trọng min_keep


def test_expand_abbrev_adds_full_form_for_retrieval():
    from legalguard.domain.analysis import _expand_abbrev
    out = _expand_abbrev("thành lập công ty TNHH một thành viên")
    assert "trách nhiệm hữu hạn" in out and out.startswith("thành lập")   # cộng thêm, giữ câu gốc
    assert _expand_abbrev("mức phạt hợp đồng") == "mức phạt hợp đồng"      # không viết tắt → không đổi

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


# ---- Cổng RELEVANCE tra cứu: sources_answer_question ----
def test_relevance_false_when_judge_says_no():
    # Nguồn KHÁC chủ đề (judge NO) → False → lookup sẽ TỪ CHỐI (chống over-reach KB lớn).
    assert sources_answer_question("ưu đãi đầu tư FDISmc", "điều về xã hội hóa nhà trẻ",
                                   _Judge(True, "NO")) is False


def test_relevance_true_when_judge_says_yes():
    assert sources_answer_question("phạt vi phạm", "Điều 301 — phạt tối đa 8%",
                                   _Judge(True, "YES")) is True


def test_relevance_none_when_offline_or_ambiguous():
    # BẢO THỦ ngược: mơ hồ/offline → None → KHÔNG abstain (giữ câu hỏi grounded hợp lệ).
    assert sources_answer_question("q", "src", _Judge(False)) is None
    assert sources_answer_question("q", "src", _Judge(True, "tùy trường hợp")) is None


def test_relevance_none_on_empty_inputs():
    assert sources_answer_question("", "src", _Judge(True, "NO")) is None
    assert sources_answer_question("q", "", _Judge(True, "NO")) is None
