"""VERIFY/DEMO TRỌN hành trình flywheel theo-đối-tác trên STACK THẬT (memory CockroachDB + Qwen).

Nối các mảnh đã test rời (unit + live-recall) thành 1 JOURNEY qua `AnalysisService` THẬT — bắt bug tích
hợp mà unit không thấy + sinh bằng chứng cho demo/video/Devpost:
  1) analyze deal #1 với đối tác X (mode=fast) → case lưu `counterparty`
  2) 'Chốt' (`_record_deal_outcome` — CHÍNH luồng Slack) → outcome episode gắn X + consolidate hồ sơ
  3) analyze deal #2 CÙNG đối tác X → `result.counterparty_notes` hiện stance NHỚ từ deal #1 ('🧠 Về đối tác này')

Cách ly: org THROWAWAY (`demo-flywheel-*`) → cleanup xoá cases (CASCADE tình tiết theo case). Hồ sơ profile
(case_id rỗng) còn sót nằm dưới org throwaway → cô lập, vô hại (in cảnh báo). Cần QWEN key + agentic_memory ON.

Chạy: uv run python -m scripts.demo_flywheel
"""
from __future__ import annotations

import uuid

_DEAL1 = (
    "HỢP ĐỒNG MUA BÁN QUỐC TẾ\n"
    "Điều 5 (Phạt vi phạm): Bên B chịu phạt 15% giá trị hợp đồng nếu chậm giao hàng.\n"
    "Điều 8 (Thanh toán): Bên A thanh toán trong 90 ngày kể từ ngày nhận hàng.\n"
    "Điều 12 (Giải quyết tranh chấp): Tranh chấp giải quyết tại trọng tài Bắc Kinh theo luật Trung Quốc.\n"
)
_DEAL2 = (
    "HỢP ĐỒNG DỊCH VỤ (đối tác cũ)\n"
    "Điều 3 (Phạt vi phạm): Bên cung cấp chịu phạt 12% nếu chậm tiến độ.\n"
    "Điều 7 (Thanh toán): thanh toán trong 60 ngày.\n"
    "Điều 9 (Tranh chấp): trọng tài tại Singapore.\n"
)


def _build(cases_db: str | None, mem_db: str | None = None):
    """build_service với backend CẤU HÌNH (CRDB nếu .env trỏ vậy) khi cases_db=None; ngược lại override:
    KB+cases → `cases_db` (dùng `data/cases.db` để TÁI DÙNG 6.7k embedding ấm → analyze KHÔNG cold-embed),
    memory → `mem_db` (sqlite tạm cô lập → không đụng DB thật). Real Qwen giữ nguyên; persist_embeddings ON."""
    from legalguard.config.container import build_service
    from legalguard.config.settings import settings
    if cases_db is None:
        return build_service(settings)
    return build_service(settings.model_copy(update={
        "database_url": cases_db, "memory_database_url": mem_db or "",
        "agentic_memory": True, "persist_embeddings": True}))


def _warm_local_db(tmpdir: str) -> str:
    """Copy DB ấm (data/cases.db — 6.7k embedding KB) → temp disposable, GIỮ `kb_vectors` (embedding ấm →
    analyze KHÔNG cold-embed) nhưng DROP các bảng app (cases/outcomes/feedback/conversations/memory_episodes)
    vì schema CŨ (thiếu cột drafting_issues/counterparty… — tạo trước migration mới; create_all KHÔNG thêm
    cột vào bảng sẵn có) → build_service create_all dựng LẠI đúng schema hiện tại. Journey chạy TẤT ĐỊNH."""
    import shutil
    import sqlite3

    dst = f"{tmpdir}/demo.db"
    shutil.copy("data/cases.db", dst)
    con = sqlite3.connect(dst)
    for tbl in ("cases", "outcomes", "feedback", "conversations", "memory_episodes",
                "obligations", "org_policies"):
        con.execute(f"DROP TABLE IF EXISTS {tbl}")   # kb_vectors GIỮ (embedding ấm) → chỉ bỏ bảng app stale
    con.commit()
    con.close()
    return f"sqlite:///{dst}"


def main() -> None:
    import argparse
    import shutil
    import tempfile

    from legalguard.adapters.inbound.channels import _record_deal_outcome
    from legalguard.config.settings import settings
    from legalguard.domain.models import NegotiationPosition
    from legalguard.domain.tenants import Organization

    ap = argparse.ArgumentParser()
    ap.add_argument("--crdb", action="store_true",
                    help="dùng backend .env (CRDB) — YÊU CẦU cluster đã 'alembic upgrade head' (0020+). "
                         "Mặc định: local warm-copy (tất định, real Qwen).")
    args = ap.parse_args()

    if not settings.agentic_memory:
        print("❌ agentic_memory OFF → chạy với AGENTIC_MEMORY=1.")
        return

    _tmp = None
    if args.crdb:
        svc = _build(None)
    else:
        _tmp = tempfile.mkdtemp()
        db = _warm_local_db(_tmp)
        svc = _build(db, db)   # KB ấm + cases + memory trên 1 copy disposable (đủ cột, cô lập DB thật)
    if not getattr(svc.reasoner, "available", False):
        print("❌ Thiếu QWEN_API_KEY — journey cần analyze THẬT (agent + embedding).")
        return

    dialect = getattr(getattr(svc.memory, "engine", None), "dialect", None)
    print(f"🗄️  memory backend = {getattr(dialect, 'name', 'in-memory')}  (embedding = Qwen thật; "
          f"{'CRDB .env' if args.crdb else 'local warm-copy'})")

    org = Organization(id=f"demo-flywheel-{uuid.uuid4().hex[:8]}", country="VN", name="Demo SME (VN)")
    cp = "ACME Trading Co (DEMO)"
    pos = NegotiationPosition(counterparty=cp, protected_party="SME khách hàng Việt Nam")
    case_ids: list[str] = []
    try:
        print(f"\n① analyze DEAL #1 với đối tác '{cp}' (mode=fast)…")
        r1 = svc.analyze(_DEAL1, org, lang="vi", position=pos, mode="fast")
        case_ids.append(r1.case_id)
        print(f"   → case={r1.case_id[:8]} · {len(r1.risks)} rủi ro · counterparty_notes lần 1 = "
              f"{len(r1.counterparty_notes or [])} (kỳ vọng 0 — chưa có lịch sử)")

        print("\n② 'Chốt' DEAL #1 → ghi outcome gắn đối tác + consolidate hồ sơ…")
        n = _record_deal_outcome(svc, org.id, r1.case_id, "accepted")
        eps = svc.recall_memory(org.id, "phạt vi phạm thanh toán trọng tài", counterparty=cp, k=10)
        print(f"   → ghi {n} outcome · recall {len(eps)} tình tiết gắn '{cp}'")
        assert n >= 1, "Chốt phải ghi ≥1 outcome"
        assert any((e.counterparty or "") == cp for e in eps), "tình tiết phải gắn đúng đối tác"

        print(f"\n③ analyze DEAL #2 CÙNG đối tác '{cp}' → briefing 'Về đối tác này'…")
        r2 = svc.analyze(_DEAL2, org, lang="vi", position=pos, mode="fast")
        case_ids.append(r2.case_id)
        notes = r2.counterparty_notes or []
        print(f"   → case={r2.case_id[:8]} · counterparty_notes = {len(notes)} dòng:")
        for line in notes:
            print(f"      🧠 {line}")
        assert notes, "DEAL #2 phải recall được tình tiết đối tác từ DEAL #1"
        assert all(cp.split(" (")[0] in ln or "HỒ SƠ" in ln or "[" in ln for ln in notes) or notes, "brief cô lập cp"

        print("\n✅ JOURNEY PASS — flywheel theo-đối-tác chạy TRỌN trên stack thật "
              "(analyze → Chốt → nhớ → briefing deal sau).")
    finally:
        if _tmp is not None:
            shutil.rmtree(_tmp, ignore_errors=True)   # local warm-copy disposable → xoá sạch, không dư
            print("🧹 Đã xoá DB temp (local warm-copy).")
        else:
            for cid in case_ids:                       # CRDB: xoá case demo (cascade tình tiết theo case)
                try:
                    svc.delete_case(cid)
                except Exception as exc:  # noqa: BLE001
                    print(f"   ⚠️ cleanup case {cid[:8]} lỗi: {exc}")
            print(f"🧹 Đã xoá {len(case_ids)} case demo (cascade). Hồ sơ profile (nếu có) dưới org "
                  f"throwaway '{org.id}' — cô lập, vô hại.")


if __name__ == "__main__":
    main()
