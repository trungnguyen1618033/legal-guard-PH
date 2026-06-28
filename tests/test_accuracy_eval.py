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
    # PHÂN LOẠI để luật sư duyệt theo chuyên môn: mỗi ca có lĩnh vực + loại hợp lệ.
    assert all(c.get("category") for c in cases)
    valid_types = {"tra_cuu", "diem_thoi_gian", "phan_biet", "tu_choi"}
    assert all(c.get("type") in valid_types for c in cases)
    assert len({c["category"] for c in cases}) >= 4   # phủ nhiều lĩnh vực


def test_golden_review_sheet_generates(tmp_path, monkeypatch):
    # golden_to_review sinh phiếu nhóm theo lĩnh vực (CSV + Markdown).
    import evaluation.golden_to_review as g
    monkeypatch.setattr(g, "_OUT_DIR", tmp_path)
    csv_p, md_p = g.write_review()
    assert csv_p.exists() and md_p.exists()
    md = md_p.read_text(encoding="utf-8")
    assert "## Chế tài thương mại" in md and "## Ngoài phạm vi KB" in md   # nhóm theo lĩnh vực
