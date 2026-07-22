"""Cấu hình test dùng chung.

Ép API key về rỗng TRƯỚC khi import app/config → mọi test chạy ở chế độ
STUB, hoàn toàn offline (không gọi LLM thật).
"""
import os
import tempfile
from pathlib import Path

os.environ["QWEN_API_KEY"] = ""
# Auth: test chạy chế độ MỞ — KHÔNG phụ thuộc `.env` (vd .env prod bật REQUIRE_AUTH + API_KEYS
# sẽ khiến test app đòi key → 401 hàng loạt / fail-closed). Cô lập để test luôn ổn định.
os.environ["API_KEYS"] = ""
os.environ["REQUIRE_AUTH"] = "false"
# DB cases ghi vào thư mục tạm → test không đụng data/ thật.
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.mkdtemp()) / 'cases.db'}"
# agentic_memory BẬT mặc định → memory adapter đọc COCKROADDB_URL/MEMORY_DATABASE_URL từ .env.
# Ép memory dùng CHUNG sqlite test (offline, KHÔNG nối CRDB thật) → test nhanh + tất định.
os.environ["MEMORY_DATABASE_URL"] = os.environ["DATABASE_URL"]
os.environ["COCKROADDB_URL"] = os.environ["DATABASE_URL"]
os.environ["COCKROACHDB_URL"] = os.environ["DATABASE_URL"]
os.environ["CRDB_URL"] = os.environ["DATABASE_URL"]

import pytest
from fastapi.testclient import TestClient

SAMPLE_CONTRACT = (
    "Tranh chấp giải quyết bằng trọng tài tại Bắc Kinh. "
    "Thanh toán T/T sau 60 ngày. "
    "Kiểm định chất lượng tại cảng đến."
)


@pytest.fixture
def sample_contract() -> str:
    return SAMPLE_CONTRACT


@pytest.fixture
def client() -> TestClient:
    from app import app

    return TestClient(app)
