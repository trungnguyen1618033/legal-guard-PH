"""Độ tin cậy câu trả lời — thuần, offline (không LLM)."""
from legalguard.domain.confidence import answer_confidence, confidence_line


def test_answer_confidence_levels():
    assert answer_confidence(False, 5) == "low"          # NLI phủ định → low bất kể evidence
    assert answer_confidence(True, 3) == "high"          # hậu thuẫn + tập trung ≥3
    assert answer_confidence(True, 2) == "medium"        # hậu thuẫn nhưng thưa
    assert answer_confidence(None, 4) == "high"          # PIT (không NLI) + tập trung → high
    assert answer_confidence(None, 1) == "medium"


def test_confidence_line_localized():
    assert "Cao" in confidence_line("high", "vi")
    assert "High" in confidence_line("high", "en")
    assert "luật sư" in confidence_line("low", "vi")     # thấp → nhắc luật sư
    assert "lawyer" in confidence_line("low", "en")
    assert "Trung bình" in confidence_line("bogus", "vi")  # level lạ → fallback medium
    assert "Trung bình" in confidence_line("medium", "xx") # lang lạ → vi
