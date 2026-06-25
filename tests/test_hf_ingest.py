from ingestion.hf_to_kb import (
    doc_type_from,
    html_to_text,
    iso_date,
    map_status,
    relationship_field,
    safe_filename,
    to_kb_markdown,
)

# Record mẫu mô phỏng schema THẬT của dataset (metadata config).
_META = {
    "id": 201365,
    "title": "Nghị định quy định về hóa đơn, chứng từ",
    "so_ky_hieu": "123/2020/NĐ-CP",
    "ngay_ban_hanh": "19/10/2020",
    "loai_van_ban": "Nghị định",
    "ngay_co_hieu_luc": "01/07/2022",
    "ngay_het_hieu_luc": None,
    "co_quan_ban_hanh": "Chính phủ",
    "tinh_trang_hieu_luc": "Còn hiệu lực",
}


def test_map_status_normalizes_real_values():
    assert map_status("Còn hiệu lực") == "in_force"
    assert map_status("Hết hiệu lực toàn bộ") == "expired"
    assert map_status("Hết hiệu lực một phần") == "in_force"   # phần lớn còn áp dụng
    assert map_status(None) == "in_force"


def test_doc_type_and_iso_date():
    assert doc_type_from("Nghị định") == "nghi_dinh"
    assert doc_type_from("Thông tư") == "thong_tu"
    assert doc_type_from("Luật") == "luat"
    assert iso_date("19/10/2020") == "2020-10-19"
    assert iso_date(None) == ""


def test_html_to_text_preserves_article_boundaries():
    html = "<p>Điều 1. Phạm vi</p><p>Nội dung.</p><div>Điều 2. Giải thích</div>"
    text = html_to_text(html)
    assert "Điều 1. Phạm vi" in text
    assert "Điều 2. Giải thích" in text
    assert "\n" in text                       # block tag → xuống dòng (chunker bắt được)


def test_safe_filename_ascii():
    assert safe_filename("70/2025/NĐ-CP", 1) == "70-2025-nd-cp.md"
    assert safe_filename(None, 42) == "doc-42.md"


def test_to_kb_markdown_builds_frontmatter_and_body():
    res = to_kb_markdown(_META, "<p>Điều 1. Phạm vi điều chỉnh</p><p>Quy định về hóa đơn.</p>")
    assert res is not None
    fname, content = res
    assert fname == "123-2020-nd-cp.md"
    assert "status: in_force" in content
    assert "effective_date: 2022-07-01" in content
    assert "doc_type: nghi_dinh" in content
    assert "doc_id: 123/2020/NĐ-CP" in content
    assert "Điều 1. Phạm vi điều chỉnh" in content


def test_to_kb_markdown_skips_empty_text():
    assert to_kb_markdown(_META, "   ") is None


def test_relationship_field_maps_graph_edges():
    assert relationship_field("Văn bản bị thay thế") == "replaced_by"
    assert relationship_field("Văn bản được sửa đổi") == "amends"
    assert relationship_field("không rõ") is None
