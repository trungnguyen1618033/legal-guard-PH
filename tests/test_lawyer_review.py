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


# ---- Phase 3: chỉ thị NGÔN NGỮ pháp lý VN (cấm cụm bịa ngoài luật) trong prompt agent ----
def test_agent_prompt_forbids_invented_terms():
    spy = _Spy()
    ctx = AgentContext(retriever=KeywordRetriever("knowledge_base", "VN"))
    run_agent("HĐ", "Việt Nam", spy, ctx, lang="vi")
    assert "thuật ngữ pháp lý Việt Nam" in spy.system.lower() or "NGÔN NGỮ PHÁP LÝ" in spy.system
    assert "chế tài chồng lấn" in spy.system and "hợp đồng bất đối xứng" in spy.system  # cấm rõ


# ---- Phase 2: phân loại loại HĐ + TÊN ĐẦY ĐỦ bên bảo vệ (dòng đầu reply luật sư) ----
class _JsonJudge:
    name = "qwen"

    def __init__(self, payload="", available=True):
        self._p, self._avail = payload, available

    @property
    def available(self):
        return self._avail

    def complete(self, prompt, *, system=None):
        return self._p


def test_extract_json_obj_tolerates_fence_and_prose():
    from legalguard.domain.analysis import _extract_json_obj
    assert _extract_json_obj('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json_obj('Kết quả: {"contract_type":"x"} xong.') == {"contract_type": "x"}
    assert _extract_json_obj("không có json ở đây") == {}
    assert _extract_json_obj('[1,2,3]') == {}                   # không phải object → {}


def test_classify_contract_extracts_type_and_full_party_name():
    svc = build_service()
    svc.judge = _JsonJudge('{"contract_type":"hợp đồng mua bán hàng hóa",'
                           '"protected_party":"Công ty CP Du lịch Phú Quốc"}')
    ctype, party, notes = svc._classify_contract("… các bên …", hint="Phu Quoc side", lang="vi")
    assert ctype == "hợp đồng mua bán hàng hóa" and party == "Công ty CP Du lịch Phú Quốc"
    assert notes == []


def test_classify_contract_offline_returns_hint():
    svc = build_service()
    svc.judge = _JsonJudge(available=False)                     # judge chưa cấu hình → không bịa
    assert svc._classify_contract("hđ", hint="Bên B", lang="vi") == ("", "Bên B", [])


def test_classify_contract_empty_party_falls_back_to_hint():
    svc = build_service()
    svc.judge = _JsonJudge('{"contract_type":"hợp đồng vay","protected_party":""}')
    ctype, party, _ = svc._classify_contract("hđ", hint="Bên Vay", lang="vi")
    assert ctype == "hợp đồng vay" and party == "Bên Vay"       # LLM để rỗng → dùng gợi ý


def test_classify_contract_returns_drafting_issues():
    # Req #8: rà lỗi soạn thảo/chính tả trong HĐ → chuỗi "«lỗi» → sửa: «đúng»".
    svc = build_service()
    svc.judge = _JsonJudge('{"contract_type":"hợp đồng mua bán","protected_party":"Cty Phú Quốc",'
                           '"drafting_issues":[{"quote":"PHÁT TRIỂỂN","fix":"PHÁT TRIỂN"},'
                           '{"quote":"Điều __ chế tài","fix":"điền số điều"}]}')
    _, _, notes = svc._classify_contract("hđ", hint="", lang="vi")
    assert len(notes) == 2
    assert "PHÁT TRIỂỂN" in notes[0] and "sửa:" in notes[0] and "PHÁT TRIỂN" in notes[0]


def test_analyze_populates_contract_type_party_and_drafting():
    svc = build_service()
    svc.judge = _JsonJudge('{"contract_type":"hợp đồng thương mại","protected_party":"Công ty X",'
                           '"drafting_issues":[{"quote":"thanht toán","fix":"thanh toán"}]}')
    res = svc.analyze(SAMPLE, ORG, lang="vi",
                      position=NegotiationPosition(protected_party="X"))
    assert res.contract_type == "hợp đồng thương mại" and res.protected_party == "Công ty X"
    assert res.drafting_notes and "thanh toán" in res.drafting_notes[0]
