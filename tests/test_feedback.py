import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from legalguard.adapters.inbound.http import build_api
from legalguard.adapters.outbound.document_parser import PdfDocxParser
from legalguard.adapters.outbound.revenue_log import CsvRevenueLog
from legalguard.adapters.outbound.sql_feedback_repository import SqlAlchemyFeedbackRepository
from legalguard.config.container import build_service
from legalguard.domain.evidence import EvidenceService
from legalguard.domain.models import Feedback


def _db():
    return f"sqlite:///{Path(tempfile.mkdtemp()) / 'fb.db'}"


def test_feedback_repo_record_and_list():
    repo = SqlAlchemyFeedbackRepository(_db())
    repo.record(Feedback(id="f1", org_id="acme", kind="lookup", ref="phạt vi phạm?",
                         rating="wrong", note="thiếu căn cứ", created_at="2026-06-25T00:00:00Z"))
    repo.record(Feedback(id="f2", org_id="acme", kind="analysis", ref="case9",
                         rating="helpful", note="", created_at="2026-06-25T01:00:00Z"))
    repo.record(Feedback(id="f3", org_id="other", kind="lookup", ref="x",
                         rating="helpful", note="", created_at="2026-06-25T02:00:00Z"))
    acme = repo.list_by_org("acme")
    assert {f.id for f in acme} == {"f1", "f2"}           # cô lập theo org (không thấy 'other')
    assert acme[0].id == "f2"                              # mới nhất trước (order desc created_at)


def _client(tmp_path):
    evidence = EvidenceService(CsvRevenueLog(str(tmp_path / "r.csv")))
    return TestClient(build_api(build_service(), PdfDocxParser(), evidence, api_orgs={}))


def test_feedback_endpoint_records_and_lists(tmp_path):
    c = _client(tmp_path)
    r = c.post("/feedback", json={"kind": "lookup", "ref": "thời điểm lập hóa đơn?",
                                  "rating": "incomplete", "note": "cần thêm ví dụ"})
    assert r.status_code == 200 and r.json()["recorded"] is True
    lst = c.get("/feedback").json()
    assert any(f["rating"] == "incomplete" and "hóa đơn" in f["ref"] for f in lst)


def test_feedback_rejects_bad_rating(tmp_path):
    assert _client(tmp_path).post("/feedback", json={"rating": "spam"}).status_code == 400
