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
