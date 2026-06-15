"""Audit trail: mỗi case lưu vân tay văn bản (SHA-256 + metadata) — KHÔNG lưu nội dung file."""
import hashlib

from legalguard.domain.models import SourceMeta

FILE_BYTES = ("Tranh chấp giải quyết bằng trọng tài tại Bắc Kinh. "
              "Thanh toán T/T sau 60 ngày.").encode("utf-8")


def test_source_meta_of_bytes():
    meta = SourceMeta.of(FILE_BYTES, "hd.txt")
    assert meta.sha256 == hashlib.sha256(FILE_BYTES).hexdigest()
    assert meta.filename == "hd.txt"
    assert meta.size_bytes == len(FILE_BYTES)


def test_analyze_text_persists_fingerprint(client, sample_contract):
    d = client.post("/analyze", data={"text": sample_contract},
                    headers={"x-tenant-id": "VN"}).json()
    case = client.get(f"/cases/{d['case_id']}").json()
    # Text dán trực tiếp: hash chính văn bản gốc (trước redact), không có tên file.
    assert case["source_sha256"] == hashlib.sha256(sample_contract.encode()).hexdigest()
    assert case["source_name"] == ""
    assert case["text_chars"] == len(sample_contract)
    assert any("SHA-256" in n for n in d["notes"])        # vân tay hiện trong notes/report


def test_analyze_file_persists_original_file_hash(client):
    d = client.post("/analyze", files={"file": ("hd.txt", FILE_BYTES)},
                    headers={"x-tenant-id": "VN"}).json()
    case = client.get(f"/cases/{d['case_id']}").json()
    # File upload: hash đúng BYTES GỐC của file (khách đưa lại file → đối chiếu được).
    assert case["source_sha256"] == hashlib.sha256(FILE_BYTES).hexdigest()
    assert case["source_name"] == "hd.txt"
    assert case["source_bytes"] == len(FILE_BYTES)


def test_same_contract_same_fingerprint(client, sample_contract):
    ids = [client.post("/analyze", data={"text": sample_contract},
                       headers={"x-tenant-id": "VN"}).json()["case_id"] for _ in range(2)]
    hashes = [client.get(f"/cases/{i}").json()["source_sha256"] for i in ids]
    assert hashes[0] == hashes[1]            # cùng văn bản → cùng vân tay (đối chiếu audit)
