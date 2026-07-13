"""Độ tin cậy câu trả lời — thuần, offline (không LLM)."""
from legalguard.domain.confidence import answer_confidence, append_confidence, confidence_line


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


def test_append_confidence_idempotent():
    # Chỉ đúng MỘT dòng độ tin cậy dù text đã có sẵn (mọi mức/ngôn ngữ) → chống lặp 2 lần.
    def _count(s):
        return sum(ln.strip().startswith(("Độ tin cậy:", "Confidence:")) for ln in s.splitlines())

    assert _count(append_confidence("Trả lời: X", "high", "vi")) == 1        # chưa có → thêm 1
    once = append_confidence("Trả lời: X", "medium", "vi")
    assert _count(append_confidence(once, "high", "vi")) == 1                 # đã có 1 → vẫn 1
    assert "Cao" in append_confidence(once, "high", "vi")                     # và là mức MỚI (high)
    # đã có sẵn dòng tiếng Anh + tiếng Việt lẫn lộn → gộp còn 1
    mixed = "Trả lời: X\n\nConfidence: Low — ...\n\nĐộ tin cậy: Thấp — ..."
    assert _count(append_confidence(mixed, "high", "vi")) == 1
    assert "Trả lời: X" in append_confidence(mixed, "high", "vi")            # giữ nội dung gốc
