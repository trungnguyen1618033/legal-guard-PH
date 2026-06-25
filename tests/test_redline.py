from fastapi.testclient import TestClient

from legalguard.adapters.inbound.http import build_api
from legalguard.adapters.outbound.document_parser import PdfDocxParser
from legalguard.adapters.outbound.knowledge_base import legal_changelog
from legalguard.adapters.outbound.revenue_log import CsvRevenueLog
from legalguard.config.container import build_service
from legalguard.domain.evidence import EvidenceService
from legalguard.domain.redline import change_ratio, redline


# ---- redline (text-level diff) ----
def test_redline_marks_added_and_removed():
    out = redline("Mức phạt không quá 8%", "Mức phạt tối đa không quá 10%")
    assert "[+" in out and "tối" in out                    # có phần thêm ("tối đa")
    assert "[-8%-]" in out and "[+10%+]" in out             # phần đổi (bỏ 8% thêm 10%)
    assert out.startswith("Mức phạt")                       # phần giữ nguyên để trần


def test_redline_identical_no_markers():
    assert "[+" not in redline("y hệt nhau", "y hệt nhau")


def test_change_ratio_bounds():
    assert change_ratio("a b c", "a b c") == 1.0
    assert 0.0 <= change_ratio("a b c d", "x y z") < 1.0


# ---- changelog (doc-level "what changed") ----
def test_changelog_shows_amendment_bidirectional():
    cl = legal_changelog("knowledge_base", "VN", "123/2020/NĐ-CP")
    assert cl is not None and cl["doc_id"] == "123/2020/NĐ-CP"
    rels = {(r["relation"], r["doc_id"]) for r in cl["related"]}
    assert ("amended_by", "70/2025/NĐ-CP") in rels          # NĐ 123 bị sửa bởi NĐ 70


def test_changelog_absent_doc_none():
    assert legal_changelog("knowledge_base", "VN", "000/0000/XX") is None


# ---- endpoints ----
def _client(tmp_path):
    evidence = EvidenceService(CsvRevenueLog(str(tmp_path / "r.csv")))
    return TestClient(build_api(build_service(), PdfDocxParser(), evidence, api_orgs={}))


def test_changes_endpoint(tmp_path):
    c = _client(tmp_path)
    r = c.get("/changes/123/2020/NĐ-CP")
    assert r.status_code == 200
    assert any(x["doc_id"] == "70/2025/NĐ-CP" for x in r.json()["related"])
    assert c.get("/changes/000/0000/XX").status_code == 404


def test_redline_endpoint(tmp_path):
    c = _client(tmp_path)
    d = c.post("/redline", json={"old": "phạt 8%", "new": "phạt tối đa 8%"}).json()
    assert "[+" in d["redline"] and 0.0 < d["similarity"] <= 1.0
