from ingestion.hf_to_kb import (
    doc_type_from,
    group_relationships,
    html_to_text,
    iso_date,
    map_status,
    rel_pairs_by_source,
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


def test_group_relationships_groups_dedups_and_skips_unknown():
    pairs = [("Văn bản bị thay thế", "39/2014/TT-BTC"),
             ("Văn bản được sửa đổi", "123/2020/NĐ-CP"),
             ("Văn bản được sửa đổi", "123/2020/NĐ-CP"),   # trùng → khử
             ("Văn bản được sửa đổi", "45/2019/QH14"),
             ("loại lạ", "999/2000")]                      # không map → bỏ
    rel = group_relationships(pairs)
    assert rel == {"replaced_by": ["39/2014/TT-BTC"], "amends": ["123/2020/NĐ-CP", "45/2019/QH14"]}


def test_to_kb_markdown_writes_relationships_to_frontmatter():
    rel = group_relationships([("Văn bản bị thay thế", "39/2014/TT-BTC"),
                               ("Văn bản được sửa đổi", "100/2015/QH13"),
                               ("Văn bản được sửa đổi", "45/2019/QH14")])
    _, content = to_kb_markdown(_META, "<p>Điều 1. Phạm vi</p>", relations=rel)
    assert "replaced_by: 39/2014/TT-BTC" in content
    assert "amends: 100/2015/QH13; 45/2019/QH14" in content     # nhiều VB → nối bằng ';' (parser đọc được)


def test_to_kb_markdown_no_relations_unchanged():
    # Không truyền relations → front-matter như cũ (tương thích ngược).
    _, content = to_kb_markdown(_META, "<p>Điều 1.</p>")
    assert "amends:" not in content and "replaced_by:" not in content


def test_to_kb_markdown_autofills_amends_articles_from_body():
    # VB sửa đổi → tự rút điều bị sửa từ thân (article-level, cho bôi vàng) — không khai tay.
    rel = group_relationships([("Văn bản được sửa đổi", "123/2020/NĐ-CP")])
    body = "<p>Sửa đổi, bổ sung khoản 2 Điều 9 của Nghị định 123/2020.</p><p>Bãi bỏ Điều 11.</p>"
    _, content = to_kb_markdown(_META, body, relations=rel)
    assert "amends: 123/2020/NĐ-CP" in content
    assert "amends_articles: Điều 9; Điều 11" in content


def test_rel_pairs_by_source_real_schema():
    # Schema THẬT th1nhng0: doc_id (nguồn) + other_doc_id (đích=id) + relationship (loại).
    rows = [
        {"doc_id": 177581, "other_doc_id": 146457, "relationship": "Văn bản được sửa đổi"},
        {"doc_id": 177581, "other_doc_id": 12806, "relationship": "Văn bản căn cứ"},
    ]
    pairs = rel_pairs_by_source(rows, id_to_ref={"146457": "123/2020/NĐ-CP", "12806": "91/2015/QH13"})
    assert pairs["177581"] == [("Văn bản được sửa đổi", "123/2020/NĐ-CP"),
                               ("Văn bản căn cứ", "91/2015/QH13")]
    # 70/2025 SỬA 123/2020 (đã verify hướng) → front-matter 'amends'
    assert group_relationships(pairs["177581"])["amends"] == ["123/2020/NĐ-CP"]


def test_rel_pairs_by_source_skips_incomplete_rows():
    rows = [{"doc_id": "1"}, {"relationship": "x", "other_doc_id": "9"},
            {"doc_id": "2", "relationship": "z"}]      # thiếu other_doc_id resolve được
    assert rel_pairs_by_source(rows, {}) == {}         # thiếu trường → bỏ, không vỡ


def test_relationship_field_real_vocabulary_directions():
    # Hướng đã verify bằng cặp thật: "được/bị X" = source làm X; "X" chủ động = other làm X.
    assert relationship_field("Văn bản được sửa đổi") == "amends"        # source sửa other
    assert relationship_field("Văn bản sửa đổi") == "amended_by"         # other sửa source
    assert relationship_field("Văn bản bổ sung") == "amended_by"
    assert relationship_field("Văn bản hết hiệu lực") == "replaces"      # source thay thế other
    assert relationship_field("Văn bản quy định hết hiệu lực") == "replaced_by"
    assert relationship_field("Văn bản HD, QĐ chi tiết") == "guided_by"  # other hướng dẫn source
    assert relationship_field("Văn bản căn cứ") == "based_on"
