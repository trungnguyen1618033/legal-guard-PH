"""Phase A+B — rà soát cho luật sư: phân loại illegal/unfavorable + 'bên mình bảo vệ'
+ lớp NLI-mâu-thuẫn nâng illegal có grounding."""
from legalguard.adapters.outbound.knowledge_base import KeywordRetriever
from legalguard.config.container import build_service
from legalguard.domain.agent import run_agent
from legalguard.domain.analysis import _detect_illegal
from legalguard.domain.models import AgentContext, ChatTurn, NegotiationPosition, Risk
from legalguard.domain.tenants import default_org

ORG = default_org("VN")
SAMPLE = "Hợp đồng: phạt vi phạm 15% giá trị, trọng tài tại Bắc Kinh, thanh toán T/T 60 ngày."


class _Judge:
    """Judge giả: verdict cố định cho nli_contradicts."""
    name = "qwen"

    def __init__(self, available=True, verdict="YES"):
        self._avail, self._v = available, verdict

    @property
    def available(self):
        return self._avail

    def complete(self, prompt, *, system=None):
        return self._v


def _unfav(legal_basis="blds_2015_hop_dong.md#Điều 357: lãi chậm trả không vượt quá..."):
    return Risk(clause="Lãi quá hạn", risk="vượt trần", severity="high",
                evidence="lãi quá hạn 200%/năm", legal_status="unfavorable", legal_basis=legal_basis)


# ---- Phase B: _detect_illegal ----
def test_detect_illegal_upgrades_when_judge_confirms_contradiction():
    r = _unfav()
    n = _detect_illegal([r], _Judge(verdict="YES"))
    assert n == 1 and r.legal_status == "illegal" and r.violated_law == "Điều 357"


def test_detect_illegal_keeps_unfavorable_when_judge_says_no():
    r = _unfav()
    assert _detect_illegal([r], _Judge(verdict="NO")) == 0
    assert r.legal_status == "unfavorable" and r.violated_law == ""


def test_detect_illegal_skips_risk_without_legal_basis():
    # Không có legal_basis (không đối chiếu được điều luật) → KHÔNG gắn illegal (bảo thủ).
    r = _unfav(legal_basis="")
    assert _detect_illegal([r], _Judge(verdict="YES")) == 0 and r.legal_status == "unfavorable"


def test_detect_illegal_noop_when_judge_offline():
    r = _unfav()
    assert _detect_illegal([r], _Judge(available=False)) == 0 and r.legal_status == "unfavorable"


def test_detect_illegal_does_not_touch_agent_illegal():
    # Risk đã illegal sẵn (agent gắn) → lớp này CHỈ nâng unfavorable, không đụng tới.
    r = Risk(clause="Phạt 15%", risk="vượt trần", severity="high", legal_status="illegal",
             violated_law="Điều 301 LTM", legal_basis="luat_thuong_mai_2005_che_tai.md#Điều 301: ...")
    _detect_illegal([r], _Judge(verdict="NO"))
    assert r.legal_status == "illegal" and r.violated_law == "Điều 301 LTM"


def test_analyze_classifies_illegal_vs_unfavorable():
    res = build_service().analyze(SAMPLE, ORG, lang="vi")
    statuses = {r["legal_status"] for r in res.risks}
    assert "illegal" in statuses and "unfavorable" in statuses     # tách 2 nhóm
    illegal = [r for r in res.risks if r["legal_status"] == "illegal"]
    assert illegal and illegal[0]["violated_law"]                  # illegal kèm điều luật bị vi phạm


def test_every_risk_has_valid_legal_status():
    res = build_service().analyze(SAMPLE, ORG, lang="vi")
    assert all(r["legal_status"] in ("illegal", "unfavorable") for r in res.risks)


class _Spy:
    name = "qwen"

    def __init__(self):
        self.system = ""

    @property
    def available(self):
        return True

    def chat(self, messages, *, tools=None):
        self.system = messages[0]["content"]
        return ChatTurn(content="done")


def test_protected_party_in_agent_prompt():
    spy = _Spy()
    ctx = AgentContext(retriever=KeywordRetriever("knowledge_base", "VN"))
    run_agent("Hợp đồng vay", "Việt Nam", spy, ctx, lang="vi",
              position=NegotiationPosition(protected_party="Bên Vay"))
    assert "Bên Vay" in spy.system                                 # bên bảo vệ vào prompt


def test_default_protected_party_falls_back_to_sme():
    spy = _Spy()
    ctx = AgentContext(retriever=KeywordRetriever("knowledge_base", "VN"))
    run_agent("x", "Việt Nam", spy, ctx, lang="vi")                # không khai → mặc định
    assert "SME client in Việt Nam" in spy.system


def test_prompt_differs_by_protected_party():
    # CÙNG hợp đồng, đổi bên bảo vệ → prompt agent KHÁC nhau (gốc của kết quả khác theo phía).
    a, b = _Spy(), _Spy()
    ctx = AgentContext(retriever=KeywordRetriever("knowledge_base", "VN"))
    run_agent("HĐ vay", "Việt Nam", a, ctx, lang="vi",
              position=NegotiationPosition(protected_party="Bên Vay"))
    run_agent("HĐ vay", "Việt Nam", b, ctx, lang="vi",
              position=NegotiationPosition(protected_party="Bên Cho Vay"))
    assert a.system != b.system
    assert "Bên Vay" in a.system and "Bên Cho Vay" in b.system
    assert "Bên Cho Vay" not in a.system   # phía bên kia KHÔNG lẫn vào prompt phía mình
