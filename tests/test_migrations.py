"""Gate migration idempotency — chống lớp bug ĐÃ CẮN (23/7): SqlMemory self-heal (ALTER ADD COLUMN IF NOT
EXISTS valid_to/superseded_by) thêm cột lúc app boot khi cluster còn ở 0017 → migration 0018 (op.add_column
TRẦN) 'DuplicateColumn' → alembic chain KẸT ở 0017 → 0019/0020 (cases/conversations.counterparty) không
chạy → flywheel Option B CÂM trên deploy. Test giả lập self-heal rồi `upgrade head` PHẢI chạy sạch. Offline."""
from __future__ import annotations

from sqlalchemy import create_engine, inspect, text


def test_upgrade_head_idempotent_after_memory_selfheal(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    from legalguard.config import settings as settings_mod

    url = f"sqlite:///{tmp_path / 'mig.db'}"
    # env.py đọc settings.database_url LIVE mỗi lần chạy → monkeypatch để alembic trỏ sqlite tạm này.
    monkeypatch.setattr(settings_mod.settings, "database_url", url)
    cfg = Config("alembic.ini")

    command.upgrade(cfg, "0017")   # tạo memory_episodes (CHƯA có valid_to — 0018 mới thêm)

    eng = create_engine(url)
    # GIẢ LẬP SqlMemory self-heal: thêm 2 cột bi-temporal TRƯỚC khi migration 0018 chạy.
    with eng.begin() as c:
        c.execute(text("ALTER TABLE memory_episodes ADD COLUMN valid_to VARCHAR NOT NULL DEFAULT ''"))
        c.execute(text("ALTER TABLE memory_episodes ADD COLUMN superseded_by VARCHAR NOT NULL DEFAULT ''"))

    command.upgrade(cfg, "head")   # 0018 idempotent → KHÔNG DuplicateColumn → 0019/0020 chạy tiếp

    cols = {col["name"] for col in inspect(eng).get_columns("cases")}
    assert "counterparty" in cols, "chain phải lên tới 0020 (cases.counterparty) — không kẹt ở 0018"
    conv_cols = {col["name"] for col in inspect(eng).get_columns("conversations")}
    assert "counterparty" in conv_cols, "0019 (conversations.counterparty) cũng phải chạy"
    eng.dispose()
