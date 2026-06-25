"""Vòng học: feedback ⚠️/➖ → ứng viên golden set + báo lỗ hổng KB (test thuần, offline)."""
from evaluation.feedback_to_golden import feedback_to_candidates, gap_report
from legalguard.domain.models import Feedback


def _fb(rating, ref, note="", kind="lookup", i=0):
    return Feedback(id=f"f{i}", org_id="acme", kind=kind, ref=ref, rating=rating,
                    note=note, created_at="2026-06-25T00:00:00Z")


def test_candidates_only_weak_ratings():
    fbs = [_fb("helpful", "câu A", i=1), _fb("wrong", "câu B", i=2),
           _fb("incomplete", "câu C", i=3)]
    cands = feedback_to_candidates(fbs)
    queries = {c["query"] for c in cands}
    assert queries == {"câu B", "câu C"}                  # helpful KHÔNG vào golden
    assert all(c["expected"] == [] for c in cands)         # expected rỗng cho luật sư điền
    assert all(c["type"] == "from_feedback" for c in cands)


def test_candidates_dedup_by_query():
    fbs = [_fb("wrong", "phạt vi phạm?", i=1), _fb("incomplete", " Phạt Vi Phạm? ", i=2)]
    cands = feedback_to_candidates(fbs)
    assert len(cands) == 1                                 # cùng câu (chuẩn hóa) → 1 ứng viên


def test_candidates_skip_empty_ref():
    fbs = [_fb("wrong", "", i=1), _fb("wrong", "   ", i=2), _fb("wrong", "thật", i=3)]
    cands = feedback_to_candidates(fbs)
    assert {c["query"] for c in cands} == {"thật"}         # ref rỗng/khoảng trắng bị bỏ


def test_candidate_note_carries_rating_and_text():
    cands = feedback_to_candidates([_fb("wrong", "q", note="sai căn cứ", i=1)])
    assert cands[0]["note"] == "wrong: sai căn cứ"


def test_gap_report_counts_and_weak_queries():
    fbs = [_fb("helpful", "A", i=1), _fb("wrong", "B", i=2),
           _fb("incomplete", "C", i=3), _fb("wrong", "B", i=4)]   # B lặp
    rep = gap_report(fbs)
    assert rep["total"] == 4
    assert rep["by_rating"] == {"helpful": 1, "wrong": 2, "incomplete": 1}
    assert rep["weak_queries"] == ["B", "C"]               # khử trùng, giữ thứ tự xuất hiện


def test_gap_report_empty():
    rep = gap_report([])
    assert rep == {"total": 0, "by_rating": {}, "weak_queries": []}
