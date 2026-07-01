from legalguard.adapters.outbound.knowledge_base import (
    CitationClosureRetriever,
    CrossEncoderRerankRetriever,
    FullContextRetriever,
    HybridRetriever,
    InForceRetriever,
    KeywordRetriever,
    RerankRetriever,
    TemporalTypedRerankRetriever,
    _extract_as_of,
    _valid_at,
    build_retriever,
)

KB = "knowledge_base"


class _StubLLM:
    name = "qwen"

    def __init__(self, available: bool):
        self._avail = available

    @property
    def available(self):
        return self._avail

    def complete(self, prompt, *, system=None):
        return "[STUB]"


def test_keyword_retriever_finds_arbitration():
    r = KeywordRetriever(KB, "VN")
    hits = r.retrieve("trọng tài Bắc Kinh", top_k=3)
    assert hits, "phải tìm được snippet liên quan trọng tài"
    assert any("trọng tài" in h.text.lower() for h in hits)


def test_keyword_retriever_empty_on_unknown_tenant():
    assert KeywordRetriever(KB, "ZZ").retrieve("bất kỳ") == []


def test_build_retriever_keyword_when_no_embed():
    assert isinstance(build_retriever(KB, "VN", embed_fn=None), KeywordRetriever)


def test_build_retriever_fallback_when_embed_raises():
    def broken(_texts):
        raise RuntimeError("embed down")

    assert isinstance(build_retriever(KB, "VN", embed_fn=broken), KeywordRetriever)


def _fake_embed(texts):
    keys = ("trọng tài", "thanh toán", "kiểm định")
    return [[float(k in t.lower()) for k in keys] for t in texts]


def test_hybrid_retriever_ranks_by_fusion():
    r = build_retriever(KB, "VN", embed_fn=_fake_embed)
    assert isinstance(r, HybridRetriever)            # keyword + embedding (RRF)
    hits = r.retrieve("trọng tài", top_k=1)
    assert hits and "trọng tài" in hits[0].text.lower()


def test_full_context_returns_entire_kb():
    r = build_retriever(KB, "VN", strategy="full")
    assert isinstance(r, FullContextRetriever)
    all_hits = r.retrieve("bất kỳ query nào", top_k=2)   # bỏ qua top_k → trả hết
    assert len(all_hits) >= 10                            # ma trận ~12 mục


def test_reranker_wraps_and_passthrough_when_llm_offline():
    r = build_retriever(KB, "VN", embed_fn=_fake_embed, reranker_llm=_StubLLM(available=False))
    assert isinstance(r, RerankRetriever)            # có wrap rerank
    hits = r.retrieve("trọng tài", top_k=2)          # llm offline → passthrough, vẫn trả kết quả
    assert hits and any("trọng tài" in h.text.lower() for h in hits)


def test_cross_encoder_rerank_reorders_by_score():
    # rerank_fn ưu tiên đoạn chứa "kiểm định" — đẩy nó lên đầu bất kể thứ tự base.
    def rerank_fn(_query, docs):
        return [1.0 if "kiểm định" in d.lower() else 0.0 for d in docs]

    r = build_retriever(KB, "VN", embed_fn=_fake_embed, rerank_fn=rerank_fn)
    assert isinstance(r, CrossEncoderRerankRetriever)
    # query khớp cả trọng tài lẫn kiểm định → cả hai vào fetch set; rerank_fn đẩy kiểm định lên đầu
    hits = r.retrieve("trọng tài kiểm định cảng đến", top_k=1)
    assert hits and "kiểm định" in hits[0].text.lower()


def test_cross_encoder_rerank_circuit_breaker_after_error():
    # rerank_fn lỗi (vd 403 chưa kích hoạt) → tắt hẳn sau lần đầu, không gọi lại; vẫn trả base.
    calls = {"n": 0}

    def failing(_q, _docs):
        calls["n"] += 1
        raise RuntimeError("HTTP 403")

    r = build_retriever(KB, "VN", embed_fn=_fake_embed, rerank_fn=failing)
    for _ in range(3):
        hits = r.retrieve("trọng tài", top_k=2)
    assert calls["n"] == 1                           # circuit-breaker: chỉ gọi 1 lần dù retrieve 3 lần
    assert hits and any("trọng tài" in h.text.lower() for h in hits)   # vẫn trả kết quả base


def test_cross_encoder_rerank_passthrough_when_fn_returns_none():
    r = build_retriever(KB, "VN", embed_fn=_fake_embed, rerank_fn=lambda q, d: None)
    hits = r.retrieve("trọng tài", top_k=2)          # None → giữ thứ tự base, vẫn trả kết quả
    assert hits and any("trọng tài" in h.text.lower() for h in hits)


def test_cross_encoder_rerank_takes_priority_over_llm():
    r = build_retriever(KB, "VN", embed_fn=_fake_embed,
                        reranker_llm=_StubLLM(available=True), rerank_fn=lambda q, d: None)
    assert isinstance(r, CrossEncoderRerankRetriever)  # cross-encoder ưu tiên hơn LLM rerank


def test_provider_path_specific_rerank():
    # Cách A: /lookup (rerank=True mặc định) GIỮ cross-encoder; /analyze (rerank=False) BỎ → nhanh hơn.
    from legalguard.adapters.outbound.knowledge_base import FileKnowledgeBaseProvider
    from legalguard.domain.tenants import Organization
    prov = FileKnowledgeBaseProvider(KB, embed_fn=_fake_embed, rerank_fn=lambda q, d: None)
    org = Organization(id="acme", country="VN")
    assert isinstance(prov.for_org(org, rerank=True), CrossEncoderRerankRetriever)    # lookup: có rerank
    assert not isinstance(prov.for_org(org, rerank=False), CrossEncoderRerankRetriever)  # analyze: không
    assert isinstance(prov.for_org(org), CrossEncoderRerankRetriever)                 # mặc định = lookup


def test_provider_path_rerank_cached_separately():
    # Hai path cache RIÊNG (không lẫn) — analyze không vô tình nhận retriever đã rerank của lookup.
    from legalguard.adapters.outbound.knowledge_base import FileKnowledgeBaseProvider
    from legalguard.domain.tenants import Organization
    prov = FileKnowledgeBaseProvider(KB, embed_fn=_fake_embed, rerank_fn=lambda q, d: None)
    org = Organization(id="acme", country="VN")
    assert prov.for_org(org, rerank=False) is prov.for_org(org, rerank=False)   # cache ổn định/path
    assert prov.for_org(org, rerank=False) is not prov.for_org(org, rerank=True)  # khác path = khác obj


def test_citation_closure_pulls_referenced_article():
    # base top_k=1 chỉ trả Điều 300; Đ.300 dẫn chiếu Đ.294 → closure phải kéo Đ.294 về.
    r = build_retriever(KB, "VN", strategy="keyword", closure=True)
    assert isinstance(r, CitationClosureRetriever)
    hits = r.retrieve("trả một khoản tiền phạt do vi phạm hợp đồng nếu có thoả thuận", top_k=1)
    srcs = [h.source for h in hits]
    assert any(s.endswith("#Điều 300") for s in srcs)        # hit gốc
    assert any(s.endswith("#Điều 294") for s in srcs)        # kéo về theo dẫn chiếu chéo


def _two_doc_kb(tmp_path):
    vn = tmp_path / "VN"
    vn.mkdir()
    (vn / "moi.md").write_text(
        "---\nstatus: in_force\n---\nĐiều 1. Quy định mới\nÁp dụng thuế suất mới.\n\n"
        "Điều 2. Hiệu lực\nCó hiệu lực thi hành.", encoding="utf-8")
    (vn / "cu.md").write_text(
        "---\nstatus: expired\n---\nĐiều 1. Quy định cũ\nÁp dụng thuế suất cũ.\n\n"
        "Điều 2. Hiệu lực\nĐã hết hiệu lực.", encoding="utf-8")
    return str(tmp_path)


def test_in_force_filter_hides_expired_by_default(tmp_path):
    r = build_retriever(_two_doc_kb(tmp_path), "VN", strategy="keyword", in_force=True)
    assert isinstance(r, InForceRetriever)
    srcs = [h.source for h in r.retrieve("thuế suất", top_k=5)]
    assert any(s.startswith("moi.md") for s in srcs)         # còn hiệu lực → có
    assert not any(s.startswith("cu.md") for s in srcs)      # hết hiệu lực → ẩn


def test_in_force_filter_surfaces_expired_on_historical_query(tmp_path):
    r = build_retriever(_two_doc_kb(tmp_path), "VN", strategy="keyword", in_force=True)
    srcs = [h.source for h in r.retrieve("thuế suất quy định cũ trước đây", top_k=5)]
    assert any(s.startswith("cu.md") for s in srcs)          # ý định lịch sử → hiện bản cũ


def _closure_kb(tmp_path):
    """Mini-KB 2 doc cho test closure — CÔ LẬP khỏi KB thật (KB lớn dần làm lệch ranking → test mong manh)."""
    vn = tmp_path / "VN"
    vn.mkdir()
    (vn / "nd_70_2025.md").write_text(
        "---\ndoc_id: 70/2025/NĐ-CP\nstatus: in_force\n---\n"
        "Điều 1. Sửa đổi\nSửa đổi, bổ sung khoản 4 Điều 9 của Nghị định số 123/2020/NĐ-CP về thời điểm "
        "lập hóa đơn xuất khẩu hàng hóa gia công.", encoding="utf-8")
    (vn / "nd_123_2020.md").write_text(
        "---\ndoc_id: 123/2020/NĐ-CP\nstatus: in_force\n---\n"
        "Điều 9. Thời điểm lập hóa đơn\nThời điểm lập hóa đơn khi bán hàng hóa là khi chuyển giao quyền sở hữu.",
        encoding="utf-8")
    return str(tmp_path)


def test_citation_closure_document_aware_cross_doc(tmp_path):
    # NĐ 70/2025 dẫn chiếu "Điều 9 của Nghị định 123/2020" → closure phải kéo Điều 9 từ ĐÚNG file NĐ 123.
    # Mini-KB cô lập → không vỡ khi corpus thật lớn dần (đã từng vỡ 2 lần vì lý do đó).
    r = build_retriever(_closure_kb(tmp_path), "VN", strategy="keyword", closure=True)
    srcs = [h.source for h in r.retrieve("thời điểm lập hóa đơn xuất khẩu hàng hóa gia công", top_k=1)]
    assert any(s.startswith("nd_70_2025") for s in srcs)             # hit gốc = NĐ sửa đổi
    assert any(s == "nd_123_2020.md#Điều 9" for s in srcs)           # closure kéo đúng văn bản đích


def test_extract_as_of_and_valid_at():
    assert _extract_as_of("hóa đơn năm 2020") == "2020-12-31"
    assert _extract_as_of("ngày 1/6/2022") == "2022-06-01"
    assert _extract_as_of("Nghị định 123/2020/NĐ-CP") is None     # số hiệu, KHÔNG phải mốc thời gian
    assert _valid_at("2014-06-01", "2022-07-01", "2020-12-31") is True    # còn hiệu lực 2020
    assert _valid_at("2014-06-01", "2022-07-01", "2024-01-01") is False   # đã hết 2024
    assert _valid_at("2022-07-01", "", "2020-12-31") is False             # chưa hiệu lực 2020


def test_point_in_time_returns_law_valid_at_date():
    r = build_retriever(KB, "VN", strategy="keyword", in_force=True)
    f2020 = {h.source.split("#")[0] for h in r.retrieve("thời điểm lập hóa đơn năm 2020", top_k=4)}
    assert any("tt_39_2014" in s for s in f2020)        # TT 39/2014 còn hiệu lực 2020
    assert not any("nd_123_2020" in s for s in f2020)   # NĐ 123 (2022) chưa hiệu lực
    f2024 = {h.source.split("#")[0] for h in r.retrieve("thời điểm lập hóa đơn năm 2024", top_k=4)}
    assert any("nd_123_2020" in s for s in f2024)        # NĐ 123 còn hiệu lực 2024
    assert not any("tt_39_2014" in s for s in f2024)     # TT 39 đã hết


def test_citation_closure_doc_level_pulls_amendment():
    # NĐ 123/2020 có front-matter amended_by 70/2025 → doc-level closure kéo NĐ 70 (văn bản sửa đổi).
    r = build_retriever(KB, "VN", strategy="keyword", in_force=True, closure=True)
    srcs = [h.source for h in r.retrieve("nội dung bắt buộc trên hóa đơn tên ký hiệu mẫu số", top_k=2)]
    assert any(s.startswith("nd_123_2020") for s in srcs)        # hit gốc
    assert any(s.startswith("nd_70_2025") for s in srcs)         # kéo theo quan hệ amended_by


def test_citation_closure_skips_self_and_absent_targets():
    r = build_retriever(KB, "VN", strategy="keyword", closure=True)
    # Đ.301 dẫn chiếu Đ.266 (chưa nạp vào KB) → không crash, không bịa; không tự kéo khoản anh em.
    hits = r.retrieve("mức phạt không quá 8% giá trị phần nghĩa vụ hợp đồng bị vi phạm", top_k=1)
    assert any(s.source.endswith("#Điều 301") for s in hits)
    assert not any(s.source.endswith("#Điều 266") for s in hits)   # đích vắng → bỏ qua êm


# ---- TT-SAR (Temporal Typed-edge Structure-Aware Reranking) ----

def _replaced_kb(tmp_path, *, eff_new: str = "2022-07-01"):
    """Mini-KB cô lập: VB cũ bị VB mới THAY THẾ (replaced_by), cùng chủ đề. Có doc_id + ngày hiệu lực."""
    vn = tmp_path / "VN"
    vn.mkdir()
    (vn / "cu.md").write_text(
        "---\ndoc_id: 39/2014/TT-BTC\nstatus: expired\nreplaced_by: 123/2020/NĐ-CP\n"
        "effective_date: 2014-06-01\nexpiry_date: 2022-07-01\n---\n"
        "Điều 1. Thời điểm lập hóa đơn\nQuy định cũ về thời điểm lập hóa đơn bán hàng hóa.",
        encoding="utf-8")
    (vn / "moi.md").write_text(
        f"---\ndoc_id: 123/2020/NĐ-CP\nstatus: in_force\nreplaces: 39/2014/TT-BTC\n"
        f"effective_date: {eff_new}\n---\n"
        "Điều 1. Thời điểm lập hóa đơn\nQuy định mới về thời điểm lập hóa đơn bán hàng hóa.",
        encoding="utf-8")
    return str(tmp_path)


def test_tt_sar_wires_and_passthrough_when_no_edges():
    # KB thật + không cạnh trúng → passthrough an toàn (vẫn trả kết quả liên quan).
    r = build_retriever(KB, "VN", strategy="keyword", tt_sar=True)
    assert isinstance(r, TemporalTypedRerankRetriever)
    hits = r.retrieve("trọng tài Bắc Kinh", top_k=3)
    assert hits and any("trọng tài" in h.text.lower() for h in hits)


def test_tt_sar_suppresses_replaced_doc_and_boosts_replacement(tmp_path):
    # Cả 2 VB cùng trúng query; TT-SAR phải đẩy bản THAY THẾ (moi) lên trên bản BỊ THAY (cu).
    kb = _replaced_kb(tmp_path)
    base = build_retriever(kb, "VN", strategy="keyword")
    tt = build_retriever(kb, "VN", strategy="keyword", tt_sar=True)
    q = "thời điểm lập hóa đơn bán hàng hóa"
    order = [h.source.split("#")[0] for h in tt.retrieve(q, top_k=2)]
    assert order and order[0] == "moi.md"          # bản thay thế lên đầu
    assert order.index("moi.md") < order.index("cu.md")  # bản bị thay bị đẩy xuống
    # base (không TT-SAR) không đảm bảo thứ tự này — chứng minh TT-SAR tạo ra khác biệt
    assert base.retrieve(q, top_k=2)               # base vẫn trả kết quả (không crash)


def test_tt_sar_temporal_gate_does_not_suppress_old_law_at_historical_date(tmp_path):
    # Point-in-time: hỏi "năm 2020" (TRƯỚC khi bản mới 2022 hiệu lực) → KHÔNG được suppress bản cũ.
    kb = _replaced_kb(tmp_path, eff_new="2022-07-01")
    tt = build_retriever(kb, "VN", strategy="keyword", tt_sar=True)
    scored = {h.source.split("#")[0]: h.score
              for h in tt.retrieve("thời điểm lập hóa đơn bán hàng hóa năm 2020", top_k=2)}
    # bản mới chưa hiệu lực 2020 → không đảo hướng; bản cũ không bị suppress (điểm không âm hóa)
    assert "cu.md" in scored
    base = build_retriever(kb, "VN", strategy="keyword")
    cu_base = {h.source.split("#")[0]: h.score for h in base.retrieve(
        "thời điểm lập hóa đơn bán hàng hóa năm 2020", top_k=2)}.get("cu.md", 0.0)
    assert scored["cu.md"] >= cu_base * 0.99       # cổng thời gian: bản cũ giữ điểm (không bị phạt)


def test_tt_sar_no_suppress_when_replacement_absent_from_kb(tmp_path):
    # #6: bản cũ replaced_by một doc_id KHÔNG có trong KB (luật 2024/2025 hay ingest rỗng) →
    # KHÔNG được suppress bản cũ (nó là đáp án đúng duy nhất còn truy được).
    vn = tmp_path / "VN"
    vn.mkdir()
    (vn / "cu.md").write_text(
        "---\ndoc_id: 39/2014/TT-BTC\nstatus: in_force\nreplaced_by: 999/9999/QH-ABSENT\n---\n"
        "Điều 1. Thời điểm lập hóa đơn\nQuy định về thời điểm lập hóa đơn bán hàng hóa.\n\n"
        "Điều 2. Nội dung hóa đơn\nNội dung bắt buộc trên hóa đơn bán hàng hóa.", encoding="utf-8")
    kb = str(tmp_path)
    q = "thời điểm lập hóa đơn bán hàng hóa"
    base = {h.source: h.score for h in build_retriever(kb, "VN", strategy="keyword").retrieve(q, 4)}
    tt = {h.source: h.score for h in build_retriever(kb, "VN", strategy="keyword", tt_sar=True).retrieve(q, 4)}
    assert tt == base                              # target vắng KB → không suppress → passthrough y hệt


def test_tt_sar_wrapped_after_reranker_not_before(tmp_path):
    # #7: bật cả tt_sar + rerank → TT-SAR là lớp NGOÀI (bọc reranker), rerank KHÔNG ghi đè tín hiệu đồ-thị.
    r = build_retriever(_replaced_kb(tmp_path), "VN", strategy="keyword",
                        rerank_fn=lambda q, d: [1.0] * len(d), tt_sar=True)
    assert isinstance(r, TemporalTypedRerankRetriever)          # TT-SAR ngoài cùng
    assert isinstance(r.base, CrossEncoderRerankRetriever)      # bọc reranker (rerank chạy TRƯỚC)


def test_tt_sar_scores_never_negative(tmp_path):
    # #8: suppression không đẩy điểm âm (âm sẽ đảo hạng + rò thang-điểm-âm sang elbow của caller).
    tt = build_retriever(_replaced_kb(tmp_path), "VN", strategy="keyword", tt_sar=True)
    assert all(h.score >= 0 for h in tt.retrieve("thời điểm lập hóa đơn bán hàng hóa", top_k=4))


def test_tt_sar_passthrough_when_base_scores_nonpositive(tmp_path):
    # #8: base trả điểm ≤0 (vd cosine âm) → không chuẩn hóa nổi → passthrough (không đảo hạng).
    from legalguard.domain.models import Snippet

    class _NegBase:
        def retrieve(self, query, top_k=4):
            return [Snippet("cu.md#Điều 1", "x", -0.1), Snippet("moi.md#Điều 1", "y", -0.5)]

    tt = TemporalTypedRerankRetriever(_NegBase(), _replaced_kb(tmp_path), "VN")
    out = tt.retrieve("bất kỳ", top_k=4)
    assert [h.source for h in out] == ["cu.md#Điều 1", "moi.md#Điều 1"]   # giữ nguyên thứ tự base
