"""Chấm độ chính xác câu trả lời — judge_case thuần + golden set hợp lệ."""
import json
from pathlib import Path

from evaluation.accuracy_eval import judge_case


def test_judge_correct_when_cite_and_fact_present():
    case = {"must_cite": ["301"], "must_say": ["8%"], "abstain": False}
    ok, _ = judge_case(case, "Mức phạt tối đa là 8% giá trị.", ["luat_thuong_mai_2005_che_tai.md#Điều 301"])
    assert ok


def test_judge_fails_on_wrong_citation_or_fact():
    case = {"must_cite": ["301"], "must_say": ["8%"], "abstain": False}
    assert not judge_case(case, "8%", ["blds_2015_hop_dong.md#Điều 418"])[0]   # sai điều luật
    assert not judge_case(case, "tối đa 10%", ["...#Điều 301"])[0]              # sai dữ kiện


def test_judge_matches_by_content_not_filename_slash():
    # Sửa bug cũ: doc_id '39/2014' vs tên file 't_39_2014_' — chấm theo NỘI DUNG nguồn.
    case = {"must_cite": ["39_2014"], "must_say": ["39/2014"], "abstain": False}
    ok, _ = judge_case(case, "Năm 2020 là Thông tư 39/2014/TT-BTC.",
                       ["tt_39_2014_hoa_don_HET_HIEU_LUC.md#Điều 16"])
    assert ok


def test_judge_abstain_correct_and_wrong():
    case = {"abstain": True}
    assert judge_case(case, "Chưa đủ căn cứ trong cơ sở tri thức.", [])[0]      # từ chối đúng
    assert not judge_case(case, "Nhãn hiệu đăng ký theo Luật SHTT...",
                          ["luat_shtt.md#Điều 1"])[0]                            # BỊA → sai


def test_golden_set_valid():
    cases = json.loads(Path("evaluation/accuracy_golden.json").read_text(encoding="utf-8"))["cases"]
    assert len(cases) >= 5
    assert all("question" in c and "abstain" in c for c in cases)
    assert any(c["abstain"] for c in cases)        # có ca kiểm TỪ CHỐI (chống bịa)
