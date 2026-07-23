"""SMOKE ON-DEMAND: verify đường CRDB ANN recall của bộ nhớ agent trên CRDB THẬT.

Vì sao KHÔNG phải pytest: đường `_candidates_ann` (VECTOR/C-SPANN + toán tử `<=>`) chỉ chạy trên CockroachDB;
sqlite KHÔNG có → CI (conftest ép sqlite + blank key) luôn đi nhánh scan, KHÔNG phủ được nhánh ANN. Đây là
smoke chạy tay (như `scripts/crdb_verify.py`, `smoke_live.py`) — đọc `.env` thật.

Phủ 3 điểm ANN-only (review #4/#5 + privacy):
  #5  same-cp XA ngữ nghĩa vẫn nổi (không rớt top-40 nhờ truy vấn bổ sung same-cp).
  #4  NULL-vec same-cp vẫn recall được (không bị lọc `vec IS NOT NULL`).
  ISO cô-lập org tuyệt đối (recall org khác → không thấy tình tiết org này).

Chạy: uv run python -m scripts.crdb_recall_check   (cần MEMORY_DATABASE_URL=cockroach* + QWEN_API_KEY)
Không cấu hình / cluster không reachable → SKIP (exit 0). Org THROWAWAY + cleanup `delete_by_counterparty`.
"""
from __future__ import annotations

import sys
import uuid


def main() -> int:
    from legalguard.config.settings import settings

    mem_url = settings.memory_database_url or settings.database_url
    if "cockroach" not in (mem_url or "").lower():
        print("SKIP — MEMORY_DATABASE_URL không trỏ CockroachDB (đây là smoke đường ANN CRDB).")
        return 0
    if not settings.qwen_api_key:
        print("SKIP — thiếu QWEN_API_KEY (cần embedding thật để kích hoạt nhánh ANN `<=>`).")
        return 0

    from sqlalchemy.exc import OperationalError

    from legalguard.adapters.outbound.qwen import QwenAdapter
    from legalguard.adapters.outbound.sql_memory_store import SqlMemory
    from legalguard.domain.models import MemoryEpisode

    llm = QwenAdapter(settings.qwen_api_key, settings.qwen_base_url, settings.qwen_model,
                      embed_model=settings.qwen_embed_model)
    org = f"crdbcheck-{uuid.uuid4().hex[:8]}"
    cp = "Đối Tác Kiểm Thử (unicode)"     # cp UNICODE → kiểm lower(counterparty) trên CRDB

    def ep(eid, clause, content, c=cp, case="cK"):
        return MemoryEpisode(id=eid, org_id=org, counterparty=c, kind="outcome", clause=clause,
                             content=content, created_at="2026-07-01", case_id=case)

    try:
        m = SqlMemory(mem_url, embed_fn=llm.embed)      # có vec thật
        m_null = SqlMemory(mem_url, embed_fn=None)       # vec NULL (embed tắt)
        m.recall(org, "probe", k=1)                      # ép kết nối sớm → bắt DNS/không-reachable
    except OperationalError as exc:
        print(f"SKIP — CRDB không reachable từ máy này: {str(exc)[:70]}")
        return 0

    if not getattr(m, "_crdb", False):
        print(f"SKIP — dialect không phải cockroachdb (được: {m.engine.dialect.name}).")
        return 0

    try:
        m.remember(ep("v1", "Điều khoản Bảo hành", "cam kết bảo hành thiết bị 24 tháng"))  # tạo cột vec
        m_null.remember(ep("v2", "Điều khoản Giao nhận", "giao hàng tận kho trong 5 ngày"))  # NULL-vec
        for i in range(3):   # noise cp KHÁC, trùng ngữ nghĩa truy vấn → chiếm ANN top (kịch bản #5)
            m.remember(ep(f"n{i}", "Phạt", "mức phạt vi phạm và cơ quan trọng tài lãi suất",
                          c="Đối Tác Khác", case="cN"))

        q = "mức phạt vi phạm và cơ quan trọng tài"      # khớp noise, KHÔNG khớp v1/v2
        ids = [e.id for e in m.recall(org, q, counterparty=cp, k=10)]
        iso = m.recall("crdbcheck-other-org", q, counterparty=cp, k=10)
        print(f"recall(cp) → {ids}")

        checks = {
            "#5 same-cp xa-ngữ-nghĩa nổi (v1)": "v1" in ids,
            "#4 NULL-vec same-cp xuất hiện (v2)": "v2" in ids,
            "ISO cô-lập org (org khác → rỗng)": iso == [],
        }
        for name, ok in checks.items():
            print(f"  [{'✅' if ok else '❌'}] {name}")
        passed = all(checks.values())
        print("✅ CRDB ANN recall PASS (dialect=cockroachdb, cp unicode OK)" if passed
              else "❌ CRDB ANN recall FAIL")
        return 0 if passed else 1
    finally:
        d1 = m.delete_by_counterparty(org, cp)
        d2 = m.delete_by_counterparty(org, "Đối Tác Khác")
        left = len(m.list_by_counterparty(org, cp, include_history=True))
        print(f"🧹 cleanup: xoá {d1}+{d2} tình tiết · còn lại = {left}")


if __name__ == "__main__":
    sys.exit(main())
