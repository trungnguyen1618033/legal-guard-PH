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


def test_fast_review_offline_returns_empty():
    class _Off(_FakeReasoner):
        @property
        def available(self):
            return False

    ctx = AgentContext(retriever=None)
    assert fast_review(_Off(), "HĐ", "VN", "vi", None, ctx) == "" and ctx.risks == []


def test_analyze_mode_fast_end_to_end():
    from legalguard.config.container import build_service
    svc = build_service()
    svc.reasoner = svc.fast_review_llm = _FakeReasoner()   # fast dùng fast_review_llm (right-sized qua env)
    svc.auto_counter_on_analyze = False           # cô lập: chỉ đo trích nhanh
    svc.legal_basis_grounding = False
    svc.illegal_detection = False
    svc.nli_verification = False
    res = svc.analyze("Bên B phạt 15%; thanh toán 90 ngày.", Organization(id="default", country="VN"),
                      lang="vi", mode="fast")
    assert len(res.risks) == 2                     # từ 1 call fast
    assert res.needs_human_review is True          # fast = màn sàng lọc → luôn cần duyệt
    assert any("nhanh" in n.lower() for n in res.notes)   # route note
    assert res.strategy == "Giữ trần phạt 8%, nhượng thời hạn."
