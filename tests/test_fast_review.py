"""Fast-path (rà soát nhanh 1-call) — thuần + qua analyze(mode='fast')."""
from legalguard.domain.fast_review import _parse, fast_review
from legalguard.domain.models import AgentContext, NegotiationPosition
from legalguard.domain.tenants import Organization

_JSON = ('{"risks":[{"clause":"Điều 5","risk":"phạt 15% vượt trần","severity":"high","priority":"must_fix",'
         '"legal_status":"illegal","violated_law":"Điều 301","evidence":"Bên B phạt 15%."},'
         '{"clause":"Điều 8","risk":"thanh toán 90 ngày","severity":"medium"}],'
         '"fallbacks":[{"clause":"Điều 8","suggestion":"rút 30 ngày","english_reply":"Please shorten."}],'
         '"strategy":"Giữ trần phạt 8%, nhượng thời hạn."}')


class _FakeReasoner:
    name = "qwen"

    def __init__(self, out=_JSON):
        self.out = out

    @property
    def available(self):
        return True

    def complete(self, prompt, *, system=None):
        return self.out


def test_parse_json_fenced_and_garbage():
    assert _parse('```json\n{"strategy":"x"}\n```')["strategy"] == "x"
    assert _parse('rác {"strategy":"y"} thừa')["strategy"] == "y"
    assert _parse("không json") == {}


def test_fast_review_populates_ctx_via_execute_tool():
    ctx = AgentContext(retriever=None)
    strategy = fast_review(_FakeReasoner(), "HĐ...", "VN", "vi",
                           NegotiationPosition(protected_party="Bên B"), ctx)
    assert strategy == "Giữ trần phạt 8%, nhượng thời hạn."
    assert len(ctx.risks) == 2 and ctx.risks[0].clause == "Điều 5"
    assert ctx.risks[0].legal_status == "illegal" and ctx.risks[0].violated_law == "Điều 301"
    assert ctx.risks[1].legal_status == "unfavorable"           # QA ép enum (thiếu → unfavorable)
    assert len(ctx.fallbacks) == 1 and ctx.fallbacks[0].suggestion == "rút 30 ngày"


def test_fast_review_garbage_returns_empty():
    """complete trả RÁC (không JSON) → fast an toàn rỗng, KHÔNG bịa. (Offline giờ chạy qua complete-stub như
    deep dùng chat-stub — không còn bail sớm ở !available.)"""
    class _Garbage(_FakeReasoner):
        def complete(self, prompt, *, system=None):
            return "xin lỗi tôi không thể phân tích"    # không phải JSON

    ctx = AgentContext(retriever=None)
    assert fast_review(_Garbage(), "HĐ", "VN", "vi", None, ctx) == "" and ctx.risks == []


def test_analyze_mode_fast_end_to_end():
    from legalguard.config.container import build_service
    svc = build_service()
    svc.reasoner = svc.fast_review_llm = _FakeReasoner()   # fast dùng fast_review_llm (right-sized qua env)
    svc.auto_counter_on_analyze = True            # bật để CHỨNG fast vẫn BỎ counter (fast_auto_counter=False)
    assert svc.fast_auto_counter is False         # mặc định TẮT → fast nhanh (~15-18s), không counter flagship
    svc.legal_basis_grounding = False
    svc.illegal_detection = False
    svc.nli_verification = False
    res = svc.analyze("Bên B phạt 15%; thanh toán 90 ngày.", Organization(id="default", country="VN"),
                      lang="vi", mode="fast")
    assert len(res.risks) == 2                     # từ 1 call fast
    assert res.needs_human_review is True          # fast = màn sàng lọc → luôn cần duyệt
    assert any("nhanh" in n.lower() for n in res.notes)   # route note
    assert res.strategy == "Giữ trần phạt 8%, nhượng thời hạn."
    # Cảnh báo RÀ NHANH hiện RÕ: trong notes (web/Next) VÀ trong reply chat (Slack/text). KHÔNG icon (tin chat sạch icon).
    assert any(n.startswith("Bản RÀ NHANH") and "BỎ SÓT" in n for n in res.notes)
    assert any("nhanh" in r.lower() for r in res.review_reasons)   # human-checkpoint box
    from legalguard.adapters.inbound.channels import format_chat_reply
    assert "RÀ NHANH" in format_chat_reply(res, lang="vi")
    # fast BỎ auto-counter (fast_auto_counter=False) → không risk nào có counter_clause inline (soạn on-demand)
    assert all(not r.get("counter_clause") for r in res.risks)


def test_analyze_mode_fast_long_map_reduce():
    """HĐ DÀI (>_FAST_MAX) + mode=fast → MAP-REDUCE nhiều cửa sổ (chống 15' deep), KHÔNG rơi về deep."""
    from legalguard.config.container import build_service
    from legalguard.domain import analysis as A
    svc = build_service()
    svc.reasoner = svc.fast_review_llm = _FakeReasoner()
    svc.auto_counter_on_analyze = False
    svc.legal_basis_grounding = svc.illegal_detection = svc.nli_verification = False
    long_contract = "Điều 5. Phạt vi phạm 30%. " + ("x" * 30000)   # > _FAST_MAX (12000) → nhiều cửa sổ
    assert len(A._fast_windows(long_contract)) >= 3                 # thực sự chia map
    res = svc.analyze(long_contract, Organization(id="default", country="VN"), lang="vi", mode="fast")
    assert res.needs_human_review is True
    assert any("map" in n.lower() for n in res.notes)              # route note = 'nhanh (map N cửa sổ)'
    assert len(res.risks) >= 1                                     # gộp + dedupe từ các cửa sổ
    clauses = [r["clause"] for r in res.risks]                     # FIX A: dedup theo clause → KHÔNG lặp
    assert len(clauses) == len(set(clauses)), f"clause trùng: {clauses}"


def test_fast_llm_error_surfaces_failed_window():
    """FIX B: LLM lỗi ở fast → KHÔNG nuốt âm thầm; post-agent gắn note 'phân đoạn lỗi — chưa rà hết' + human-review."""
    from legalguard.config.container import build_service
    from legalguard.domain.ports import LLMError

    class _Boom(_FakeReasoner):
        def complete(self, prompt, *, system=None):
            raise LLMError("qwen", "rate limit")       # mô phỏng 429 hết retry

    svc = build_service()
    svc.reasoner = svc.fast_review_llm = _Boom()
    svc.legal_basis_grounding = svc.illegal_detection = svc.nli_verification = False
    svc.auto_counter_on_analyze = False
    res = svc.analyze("Bên B phạt 30%.", Organization(id="default", country="VN"), lang="vi", mode="fast")
    assert res.needs_human_review is True
    assert any("phân đoạn lỗi" in n.lower() or "chưa rà" in n.lower() for n in res.notes), res.notes
    # FIX E: cảnh báo lỗi PHẢI hiện trên reply chat (không giấu → user không tưởng HĐ sạch)
    from legalguard.adapters.inbound.channels import format_chat_reply
    assert "chưa rà" in format_chat_reply(res, lang="vi").lower()


def test_analyze_mode_deep_only_from_short_instruction():
    """FIX F: 'chi tiết/sâu' trong CHỈ-DẪN ngắn → deep; nhưng trong THÂN HĐ DÁN dài → KHÔNG deep oan (15')."""
    from legalguard.adapters.inbound.channels import _analyze_mode
    assert _analyze_mode("rà kỹ giúp tôi", has_attachment=False) == "deep"
    assert _analyze_mode("rà giúp", has_attachment=False) == "fast"
    long_paste = "HỢP ĐỒNG. Điều 1. Bên A kiểm tra chi tiết, phân tích sâu hàng hóa. " + ("x" * 400)
    assert _analyze_mode(long_paste, has_attachment=False) == "fast"     # thân HĐ chứa 'chi tiết/sâu' KHÔNG deep
    assert _analyze_mode("rà kỹ", has_attachment=True) == "deep"         # caption file ngắn → deep OK


def test_deep_multiwindow_strategy_single_block():
    """Fix (3): deep HĐ nhiều cửa sổ → 1 KHỐI chiến lược (không nối trùng mọi cửa sổ). Dùng stub agent."""
    from legalguard.config.container import build_service
    from legalguard.domain import analysis as A
    svc = build_service()   # stub LLM (no key) → _stub_chat trả strategy/cửa sổ
    svc.legal_basis_grounding = svc.illegal_detection = svc.nli_verification = False
    svc.auto_counter_on_analyze = False
    # >_CHUNK → ≥2 cửa sổ; 'trọng tài' rải để mỗi cửa sổ sinh strategy giống nhau
    contract = ("Điều khoản trọng tài tại Bắc Kinh. " * 40 + "x" * (A._CHUNK)) + " trọng tài Bắc Kinh."
    assert len(A._windows(contract)) >= 2
    res = svc.analyze(contract, Organization(id="default", country="VN"), lang="vi", mode="deep")
    # chiến lược stub xuất hiện ĐÚNG 1 lần (trước fix: nối 2 cửa sổ → 2 lần)
    assert res.strategy.count("GIỮ CỨNG điều khoản trọng tài") <= 1, res.strategy


def test_deep_route_iters_reduced_and_no_auto_counter():
    """Tối ưu deep (giữ chất lượng): max_iters 'full'=4 (từ 6) + auto-counter on-demand (deep_auto_counter=False)."""
    from legalguard.domain.analysis import _route
    from legalguard.config.container import build_service
    assert _route("x" * 5000)["max_iters"] == 4          # HĐ dài → 4 vòng (giảm từ 6, tested no-quality-loss)
    svc = build_service()
    assert svc.deep_auto_counter is False                # deep bỏ auto-counter inline (counter on-demand qua nút)


def test_fast_huge_contract_caps_windows():
    """Round 3: HĐ khổng lồ → CẮT ở _FAST_MAX_WINDOWS + truncated (chống phình chi phí/latency)."""
    from legalguard.config.container import build_service
    from legalguard.domain import analysis as A
    svc = build_service()
    svc.reasoner = svc.fast_review_llm = _FakeReasoner()
    svc.legal_basis_grounding = svc.illegal_detection = svc.nli_verification = False
    svc.auto_counter_on_analyze = False
    # Text ĐA DẠNG (không 'x'*n — chuỗi lặp 1 ký tự gây ReDoS ở redact, artifact test). > trần cửa sổ.
    huge = "Điều 5. Phạt vi phạm 30 phần trăm giá trị hợp đồng nếu chậm giao. " * 8000
    res = svc.analyze(huge, Organization(id="default", country="VN"), lang="vi", mode="fast")
    assert any(f"map {A._FAST_MAX_WINDOWS}" in n for n in res.notes)          # cắt đúng trần
    assert any("vượt giới hạn" in n.lower() or "chưa được rà" in n.lower() for n in res.notes)  # truncated note


def test_fast_single_window_keeps_distinct_same_clause_risks():
    """FIX G: single-window fast giữ 2 rủi ro KHÁC NHAU cùng điều khoản (dùng _dedupe, KHÔNG _dedupe_clause)."""
    from legalguard.config.container import build_service
    two_same_clause = ('{"risks":[{"clause":"Điều 8","risk":"thanh toán trả sau 90 ngày","severity":"medium"},'
                       '{"clause":"Điều 8","risk":"phạt chậm trả 20%","severity":"high"}],"fallbacks":[],'
                       '"strategy":"x"}')
    svc = build_service()
    svc.reasoner = svc.fast_review_llm = _FakeReasoner(two_same_clause)
    svc.legal_basis_grounding = svc.illegal_detection = svc.nli_verification = False
    svc.auto_counter_on_analyze = False
    res = svc.analyze("Điều 8 thanh toán trả sau và phạt chậm.", Organization(id="default", country="VN"),
                      lang="vi", mode="fast")
    d8 = [r for r in res.risks if r["clause"] == "Điều 8"]
    assert len(d8) == 2, f"single-window fast phải giữ CẢ 2 rủi ro Điều 8, got {len(d8)}"


def test_dedupe_clause_keeps_most_severe():
    """FIX A: _dedupe_clause gộp cùng clause, giữ mục nặng nhất (severity→priority), giữ thứ tự."""
    from legalguard.domain.analysis import _dedupe_clause
    from legalguard.domain.models import Risk
    items = [
        Risk(clause="Điều 5", risk="phạt nhẹ", severity="low", priority="acceptable"),
        Risk(clause="Điều 8", risk="thanh toán", severity="medium", priority="negotiate"),
        Risk(clause="Điều 5", risk="phạt vượt trần", severity="high", priority="must_fix"),
    ]
    out = _dedupe_clause(items)
    assert [r.clause for r in out] == ["Điều 5", "Điều 8"]         # 1 mục/clause, giữ thứ tự
    d5 = next(r for r in out if r.clause == "Điều 5")
    assert d5.severity == "high" and d5.priority == "must_fix"     # giữ mục NẶNG nhất
