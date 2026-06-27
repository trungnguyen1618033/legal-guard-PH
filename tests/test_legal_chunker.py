import unicodedata

from legalguard.adapters.outbound.knowledge_base import _load_chunks
from legalguard.adapters.outbound.legal_chunker import (
    article_key,
    chunk_legal,
    extract_article_changes,
    extract_article_refs,
    extract_citations,
    nfc,
)

_DOC = """LUẬT MẪU
Căn cứ Hiến pháp;

Điều 1. Phạm vi điều chỉnh
Luật này quy định về abc.

Điều 2. Giải thích từ ngữ
Trong Luật này, các từ ngữ được hiểu như sau.

Điều 3. Quyền và nghĩa vụ
1. Bên A có quyền theo khoản 2 Điều 1.
2. Bên B có nghĩa vụ theo quy định tại Nghị định 13/2023.
"""


def test_nfc_normalizes_decomposed_vietnamese():
    decomposed = unicodedata.normalize("NFD", "Điều")  # tách dấu
    assert decomposed != "Điều"           # khác byte trước khi chuẩn hóa
    assert nfc(decomposed) == "Điều"      # NFC gộp lại


def test_chunk_legal_splits_by_article_with_labels():
    chunks = chunk_legal(_DOC)
    labels = [lbl for lbl, _ in chunks]
    assert labels[0] is None                       # phần mở đầu (tên luật + căn cứ)
    assert "Điều 1" in labels and "Điều 2" in labels and "Điều 3" in labels
    dieu1 = next(text for lbl, text in chunks if lbl == "Điều 1")
    assert dieu1.startswith("Điều 1")              # thân giữ nguyên đầu điều


def test_chunk_legal_falls_back_to_paragraphs_without_articles():
    text = "Đoạn một.\n\nĐoạn hai.\n\nĐoạn ba."
    chunks = chunk_legal(text)
    assert [lbl for lbl, _ in chunks] == [None, None, None]
    assert len(chunks) == 3


def test_chunk_legal_subsplits_long_article_by_clause():
    long_art = "Điều 5. Điều dài\n" + "".join(
        f"{i}. " + "nội dung khoản rất dài " * 30 + "\n" for i in range(1, 4)
    )
    doc = "Điều 4. Điều ngắn\nNội dung ngắn.\n\n" + long_art   # ≥2 Điều → vào chế độ legal
    chunks = chunk_legal(doc)
    labels = [lbl for lbl, _ in chunks]
    assert "Điều 4" in labels                       # điều ngắn giữ nguyên 1 chunk
    assert "Điều 5 khoản 1" in labels               # điều dài tách theo khoản
    assert "Điều 5 khoản 3" in labels


def test_chunk_legal_handles_markdown_prefixed_articles():
    md = "## Điều 1. Phạm vi\nNội dung một.\n\n**Điều 2.** Giải thích\nNội dung hai."
    chunks = chunk_legal(md)
    labels = [lbl for lbl, _ in chunks]
    assert "Điều 1" in labels and "Điều 2" in labels          # vẫn nhận diện qua tiền tố markdown
    dieu1 = next(t for lbl, t in chunks if lbl == "Điều 1")
    assert dieu1.startswith("Điều 1")                         # tiền tố '## ' đã bị loại khỏi body


def test_subsplit_clause_chunks_keep_article_anchor():
    long_art = "Điều 7. Quyền của bên thuê\n" + "".join(
        f"{i}. " + "nội dung khoản rất dài " * 30 + "\n" for i in range(1, 4)
    )
    doc = "Điều 6. Mở đầu\nNgắn.\n\n" + long_art
    chunks = chunk_legal(doc)
    khoan2 = next(t for lbl, t in chunks if lbl == "Điều 7 khoản 2")
    assert khoan2.startswith("Điều 7. Quyền của bên thuê")    # neo tiêu đề điều luật cho khoản


def test_extract_citations_finds_articles_and_documents():
    cites = extract_citations(_DOC)
    joined = " | ".join(cites).lower()
    assert "điều 1" in joined           # dẫn chiếu điều
    assert "13/2023" in joined          # dẫn chiếu văn bản (Nghị định)


def test_article_key_normalizes_references():
    assert article_key("khoản 1 Điều 300") == "Điều 300"
    assert article_key("Điều 294 của Luật này") == "Điều 294"
    assert article_key("ĐIỀU 266") == "Điều 266"
    assert article_key("Điều này") is None            # không có số → không phân giải
    assert article_key("Nghị định 13/2023") is None    # dẫn chiếu văn bản, không phải Điều


def test_extract_article_refs_resolves_target_document():
    assert extract_article_refs("sửa đổi khoản 4 Điều 9 của Nghị định số 123/2020/NĐ-CP") == [
        ("Điều 9", "123/2020/NĐ-CP")]                         # trỏ văn bản khác
    assert extract_article_refs("miễn trách nhiệm quy định tại Điều 294 của Luật này") == [
        ("Điều 294", "self")]                                 # cùng văn bản
    assert extract_article_refs("theo quy định tại Điều 10 Nghị định này") == [
        ("Điều 10", "self")]
    assert extract_article_refs("xem Điều 5 để biết thêm") == [("Điều 5", None)]  # trống ngữ cảnh


def test_extract_article_changes_classifies_actions():
    # 'Sửa đổi, bổ sung' → amend (KHÔNG phải add dù có 'bổ sung'); bãi bỏ → repeal; bổ sung thuần → add.
    body = ("Sửa đổi, bổ sung khoản 2 Điều 9 như sau: ... "
            "Bãi bỏ điểm a khoản 3 Điều 10. "
            "Bổ sung Điều 9a vào sau Điều 9. "
            "Thay thế cụm từ tại Điều 11.")
    chs = extract_article_changes(body)
    by_art = {(c["article"], c["action"]) for c in chs}
    assert ("Điều 9", "amend") in by_art
    assert ("Điều 10", "repeal") in by_art
    assert ("Điều 9a", "add") in by_art
    assert ("Điều 11", "replace") in by_art
    # clause/point bắt được
    d9 = next(c for c in chs if c["article"] == "Điều 9" and c["action"] == "amend")
    assert d9["clause"] == "khoản 2"
    d10 = next(c for c in chs if c["article"] == "Điều 10")
    assert d10["clause"] == "khoản 3" and d10["point"] == "điểm a"


def test_extract_article_changes_ignores_plain_references():
    # Dẫn chiếu thường (không có động từ thay đổi) → KHÔNG coi là thay đổi.
    assert extract_article_changes("theo quy định tại Điều 5 và Điều 7 của Luật này") == []


def test_extract_article_changes_respects_sentence_boundary():
    # Bug A: động từ thay đổi của câu TRƯỚC không được lan sang điều ở câu sau (dẫn chiếu thường).
    chs = extract_article_changes("Bãi bỏ Điều 5. Theo quy định tại Điều 7 thì áp dụng.")
    arts = {(c["article"], c["action"]) for c in chs}
    assert ("Điều 5", "repeal") in arts
    assert not any(a == "Điều 7" for a, _ in arts)     # Điều 7 chỉ là dẫn chiếu


def test_extract_article_changes_skips_anchor_article():
    # Bug B: 'Bổ sung Điều 9a vào sau Điều 9' → chỉ Điều 9a được THÊM; Điều 9 là mốc neo, KHÔNG đổi.
    chs = extract_article_changes("Bổ sung Điều 9a vào sau Điều 9.")
    arts = {(c["article"], c["action"]) for c in chs}
    assert ("Điều 9a", "add") in arts
    assert not any(a == "Điều 9" for a, _ in arts)


def test_real_kb_law_chunks_to_article_units_with_crossrefs():
    # File luật thật trong KB → chunk theo Điều, source mang nhãn '#Điều N', dẫn chiếu chéo rút được.
    ltm = [(s, t) for s, t in _load_chunks("knowledge_base", "VN") if "luat_thuong_mai" in s]
    assert any(s.endswith("#Điều 300") for s, _ in ltm)      # cắt đúng cấp điều luật
    assert any("khoản" in s for s, _ in ltm)                  # Điều dài (297) tách theo khoản
    dieu300 = next(t for s, t in ltm if s.endswith("#Điều 300"))
    assert "Điều 294" in extract_citations(dieu300)           # Đ.300 dẫn chiếu Đ.294 — cạnh cho Phase 2
