"""Playbook công ty (OrgPolicy) — domain thuần + repo + service + rendering (offline)."""
from legalguard.adapters.outbound.sql_org_policy_repository import InMemoryOrgPolicyRepository
from legalguard.domain.analysis import AnalysisService
from legalguard.domain.models import AnalysisCase, AnalysisResult, OrgPolicy
from legalguard.domain.policy import _parse, check_policy, suggest_policies


class _Judge:
    name = "qwen"

    def __init__(self, out, available=True):
        self._out, self._a = out, available

    @property
    def available(self):
        return self._a

    def complete(self, prompt, *, system=None):
        return self._out


# ---- parse ----
def test_parse_object():
    assert _parse('```json\n{"violated": true, "clause": "Điều 5"}\n```') == {"violated": True, "clause": "Điều 5"}
    assert _parse("rác") == {}
    assert _parse("") == {}


# ---- check_policy ----
_RISKS = [{"clause": "Điều 5", "risk": "phạt 15%", "evidence": "Bên B chịu phạt 15% giá trị hợp đồng."}]
_POL = [OrgPolicy(id="p1", org_id="A", rule_text="Phạt vi phạm không quá 8%", severity="must_fix")]


def test_check_policy_offline_or_empty():
    assert check_policy(_RISKS, _POL, _Judge("", available=False)) == []   # judge offline
    assert check_policy(_RISKS, [], _Judge('{"violated":true}')) == []       # không có policy
    assert check_policy([], _POL, _Judge('{"violated":true}')) == []         # không có rủi ro


def test_check_policy_flags_violation():
    out = check_policy(_RISKS, _POL, _Judge('{"violated": true, "clause": "Điều 5"}'))
    assert len(out) == 1
    assert out[0]["policy_id"] == "p1" and out[0]["clause"] == "Điều 5"
    assert out[0]["rule_text"] == "Phạt vi phạm không quá 8%"


def test_check_policy_no_violation():
    assert check_policy(_RISKS, _POL, _Judge('{"violated": false, "clause": ""}')) == []


def test_check_policy_skips_inactive():
    pol = [OrgPolicy(id="p1", org_id="A", rule_text="X", active=False)]
    assert check_policy(_RISKS, pol, _Judge('{"violated": true, "clause": "Điều 5"}')) == []


# ---- repo (in-memory) ----
def test_repo_org_scope():
    repo = InMemoryOrgPolicyRepository()
    repo.upsert(OrgPolicy(id="p1", org_id="A", rule_text="a"))
    repo.upsert(OrgPolicy(id="p2", org_id="A", rule_text="b", active=False))
    repo.upsert(OrgPolicy(id="p3", org_id="B", rule_text="c"))
    assert len(repo.list_by_org("A")) == 1                       # active_only mặc định
    assert len(repo.list_by_org("A", active_only=False)) == 2
    assert len(repo.list_by_org("B")) == 1
    assert repo.delete("p3", "A") is False                       # sai org → không xóa
    assert repo.delete("p3", "B") is True
    # upsert KHÔNG cho org khác ghi đè theo id (cô lập org)
    repo.upsert(OrgPolicy(id="p1", org_id="B", rule_text="HIJACK"))
    assert repo.list_by_org("A")[0].rule_text == "a"             # policy của A giữ nguyên
    assert repo.list_by_org("B", active_only=False) == []        # B không tạo được id của A


# ---- service CRUD ----
def _svc(repo):
    return AnalysisService(reasoner=object(), kb=object(), org_policies=repo, org_playbook=True)


def test_suggest_policies_from_history():
    def case(cid, clauses):
        risks = [{"clause": c, "priority": "must_fix"} for c in clauses]
        return AnalysisCase(id=cid, org_id="A", tenant="VN", created_at="t", lang="vi",
                            contract_excerpt="", summary="", needs_human_review=False,
                            risks=risks, fallbacks=[], trace=[])
    cases = [case("1", ["Phạt vi phạm", "Thanh toán"]), case("2", ["Phạt vi phạm"]), case("3", ["Bảo hành"])]
    s = suggest_policies(cases, min_count=2)
    assert len(s) == 1 and s[0]["clause"] == "Phạt vi phạm" and s[0]["count"] == 2
    assert "Rà soát" in s[0]["rule_text"]
    # cùng clause trong 1 case đếm 1 lần (không thổi count)
    dup = [AnalysisCase(id="x", org_id="A", tenant="VN", created_at="t", lang="vi", contract_excerpt="",
                        summary="", needs_human_review=False,
                        risks=[{"clause": "A", "priority": "must_fix"}, {"clause": "A", "legal_status": "illegal"}],
                        fallbacks=[], trace=[])]
    assert suggest_policies(dup, min_count=2) == []          # 1 case → count=1 < 2


def test_service_policy_crud():
    repo = InMemoryOrgPolicyRepository()
    svc = _svc(repo)
    pid = svc.upsert_policy(OrgPolicy(id="p1", org_id="A", rule_text="Phạt ≤ 8%"))
    assert pid == "p1" and len(svc.list_policies("A")) == 1
    assert svc.delete_policy("p1", "A") is True and svc.list_policies("A") == []


# ---- rendering (reply có mục "Vi phạm chính sách công ty") ----
def test_reply_shows_policy_violations():
    from legalguard.adapters.inbound.channels import _analysis_blocks, format_chat_reply
    res = AnalysisResult(tenant="VN", risks=[{"clause": "Điều 5", "risk": "phạt 15%"}], fallbacks=[],
                         needs_human_review=False, review_reasons=[], summary="", trace=[], strategy="Giữ",
                         policy_violations=[{"policy_id": "p1", "rule_text": "Phạt ≤ 8%",
                                            "clause": "Điều 5", "severity": "must_fix", "kind": "threshold"}])
    txt = format_chat_reply(res)
    assert "Vi phạm chính sách công ty" in txt and "Phạt ≤ 8%" in txt and "Điều 5" in txt
    dump = __import__("json").dumps(_analysis_blocks(res, "c1"), ensure_ascii=False)
    assert "Vi phạm chính sách công ty" in dump
    # không có vi phạm → không hiện mục
    res2 = AnalysisResult(tenant="VN", risks=[{"clause": "Đ1", "risk": "x"}], fallbacks=[],
                          needs_human_review=False, review_reasons=[], summary="", trace=[], strategy="")
    assert "Vi phạm chính sách" not in format_chat_reply(res2)


# ---- endpoints ----
def test_policy_endpoints(tmp_path):
    from fastapi.testclient import TestClient

    from legalguard.adapters.inbound.http import build_api
    from legalguard.adapters.outbound.document_parser import PdfDocxParser
    from legalguard.adapters.outbound.revenue_log import CsvRevenueLog
    from legalguard.config.container import build_service
    from legalguard.domain.evidence import EvidenceService

    evidence = EvidenceService(CsvRevenueLog(str(tmp_path / "r.csv")))
    c = TestClient(build_api(build_service(), PdfDocxParser(), evidence, api_orgs={}))
    assert c.get("/org/policy").json() == {"policies": [], "count": 0}
    r = c.post("/org/policy", json={"rule_text": "Phạt vi phạm không quá 8%"})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["id"]
    pid = r.json()["id"]
    assert c.get("/org/policy").json()["count"] == 1
    assert c.post("/org/policy", json={"rule_text": ""}).status_code == 400   # rỗng → 400
    assert c.request("DELETE", f"/org/policy/{pid}").json() == {"ok": True}
    assert c.get("/org/policy").json()["count"] == 0