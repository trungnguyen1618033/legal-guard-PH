"""Chấm độ chính xác câu trả lời — judge_case thuần + golden set hợp lệ."""
import json
from pathlib import Path

from evaluation.accuracy_eval import _vn_num_to_digits, judge_case


def test_vn_number_words_normalize_to_digits():
    assert _vn_num_to_digits("hết hai mươi năm kể từ ngày nộp đơn") == "hết 20 năm kể từ ngày nộp đơn"
    assert _vn_num_to_digits("chín mươi ngày") == "90 ngày"
    assert "20 năm" not in _vn_num_to_digits("hai mươi lăm năm")   # 25 KHÔNG false-match '20 năm'
    # số ghép 11-99 (review #5): trước đây 'hai mươi lăm' ra '20 lăm', giờ đúng '25'
    assert _vn_num_to_digits("hai mươi lăm năm") == "25 năm"
    assert _vn_num_to_digits("hai mươi mốt") == "21"
    assert _vn_num_to_digits("chín mươi chín") == "99"
    assert _vn_num_to_digits("mười lăm ngày") == "15 ngày"
    assert _vn_num_to_digits("năm mươi năm") == "50 năm"          # 50 (năm=hàng chục) + năm (year)


def test_judge_accepts_spelled_number_matching_digit_must_say():
    # Luật viết CHỮ ("hai mươi năm") nhưng golden ghi SỐ ("20 năm") → vẫn phải PASS (không brittle).
    case = {"must_cite": ["93"], "must_say": ["20 năm"], "abstain": False}
    ans = "Thời hạn bảo hộ sáng chế là hai mươi năm kể từ ngày nộp đơn."
    ok, _ = judge_case(case, ans, ["luat_shtt_2005.md#Điều 93"])
    assert ok


def test_judge_correct_when_cite_and_fact_present():
    case = {"must_cite": ["301"], "must_say": ["8%"], "abstain": False}
    ok, _ = judge_case(case, "Mức phạt tối đa là 8% giá trị.", ["luat_thuong_mai_2005_che_tai.md#Điều 301"])
    assert ok


def test_judge_fails_on_wrong_citation_or_fact():
    case = {"must_cite": ["301"], "must_say": ["8%"], "abstain": False}
    assert not judge_case(case, "8%", ["blds_2015_hop_dong.md#Điều 418"])[0]   # sai điều luật
    assert not judge_case(case, "tối đa 10%", ["...#Điều 301"])[0]              # sai dữ kiện


def test_judge_must_say_pipe_is_synonym_or():
    # '|' trong 1 must_say = CHẤP mọi cách diễn đạt đồng nghĩa đúng-luật (khử nhiễu wording), KHÔNG hạ chuẩn.
    case = {"must_cite": ["trong_tai"], "must_say": ["từ chối|trả lại đơn|không thụ lý"], "abstain": False}
    assert judge_case(case, "Tòa TRẢ LẠI ĐƠN khởi kiện.", ["x#trong_tai"])[0]      # synonym → pass
    assert judge_case(case, "Tòa TỪ CHỐI thụ lý.", ["x#trong_tai"])[0]             # gốc → pass
    assert not judge_case(case, "Tòa vẫn thụ lý bình thường.", ["x#trong_tai"])[0] # sai ý → vẫn FAIL
    # AND giữa nhiều item vẫn giữ (mỗi item là 1 dữ-kiện bắt buộc)
    c2 = {"must_cite": [], "must_say": ["8%", "thương mại|LTM"], "abstain": False}
    assert judge_case(c2, "trần 8% theo LTM 2005", [])[0]
    assert not judge_case(c2, "trần 8%", [])[0]                                    # thiếu item 2 → FAIL


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
    valid_types = {"tra_cuu", "diem_thoi_gian", "phan_biet", "tu_choi",
                   "ap_dung", "bay_tien_de", "closure", "cap_nhat"}
    assert all(c.get("type") in valid_types for c in cases)
    assert len({c["category"] for c in cases}) >= 5   # phủ nhiều lĩnh vực
    assert len({c["type"] for c in cases}) >= 6        # phủ nhiều LOẠI test


def test_golden_review_sheet_generates(tmp_path, monkeypatch):
    # golden_to_review sinh phiếu nhóm theo lĩnh vực (CSV + Markdown).
    import evaluation.golden_to_review as g
    monkeypatch.setattr(g, "_OUT_DIR", tmp_path)
    csv_p, md_p = g.write_review()
    assert csv_p.exists() and md_p.exists()
    md = md_p.read_text(encoding="utf-8")
    assert "## Chế tài thương mại" in md and "## Lao động" in md           # nhóm theo lĩnh vực
