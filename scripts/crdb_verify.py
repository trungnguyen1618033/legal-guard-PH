"""P0 — Verify môi trường CockroachDB (Phase 0 của kế hoạch CRDB hackathon).

Chạy khi ĐÃ có connection string CockroachDB Cloud:
    CRDB_URL="postgresql://user:pass@host:26257/defaultdb?sslmode=verify-full" \
        uv run python -m scripts.crdb_verify

Kiểm 4 thứ P0 cần chốt (research nói vector GA ở v25.4):
  1) Kết nối được (psycopg, tiếng Postgres wire).
  2) Version ≥ v25.4 (VECTOR + CREATE VECTOR INDEX GA, bật mặc định).
  3) Cột VECTOR + CREATE VECTOR INDEX tạo được (feature #1/4: Distributed Vector Indexing).
  4) ANN search `<=>` chạy → sẵn sàng thay SqlEmbeddingStore (Phase 2).

KHÔNG ghi gì vĩnh viễn: tạo bảng tạm `_crdb_verify_tmp` rồi DROP.
"""
from __future__ import annotations

import os
import sys


def _load_dotenv() -> None:
    """Nạp .env (thuần, không cần python-dotenv) → cho phép để CRDB_URL trong .env (gitignored),
    khỏi lộ secret trên dòng lệnh. Chỉ set biến CHƯA có trong môi trường."""
    from pathlib import Path
    p = Path(".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _conn_str() -> str:
    _load_dotenv()
    url = os.environ.get("CRDB_URL") or os.environ.get("DATABASE_URL") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not url:
        sys.exit("Thiếu connection string. Đặt CRDB_URL=\"postgresql://…\" trong .env "
                 "(hoặc export CRDB_URL, hoặc truyền làm tham số).")
    # psycopg cần scheme postgresql:// (không phải cockroachdb://)
    return url.replace("cockroachdb://", "postgresql://", 1)


def main() -> None:
    try:
        import psycopg
    except ImportError:
        sys.exit("Thiếu psycopg. Chạy: uv add psycopg")

    url = _conn_str()
    print("→ Đang kết nối CockroachDB…")
    try:
        conn = psycopg.connect(url, connect_timeout=15)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"❌ [1] Kết nối THẤT BẠI: {exc}")
    print("✅ [1] Kết nối OK")

    ok_vector = ok_index = ok_ann = False
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            ver = cur.fetchone()[0]
            print(f"✅ [2] Version: {ver}")
            if "v25.4" not in ver and "v25.5" not in ver and "v26" not in ver:
                print("   ⚠️  Chưa chắc ≥ v25.4 — vector index GA ở v25.4. Kiểm lại nếu bước dưới lỗi.")

            try:
                cur.execute("DROP TABLE IF EXISTS _crdb_verify_tmp;")
                cur.execute("CREATE TABLE _crdb_verify_tmp (id INT PRIMARY KEY, v VECTOR(3));")
                ok_vector = True
                print("✅ [3a] Tạo cột VECTOR(3) OK")
            except Exception as exc:  # noqa: BLE001
                print(f"❌ [3a] Cột VECTOR lỗi: {exc}")

            if ok_vector:
                try:
                    cur.execute("CREATE VECTOR INDEX ON _crdb_verify_tmp (v);")
                    ok_index = True
                    print("✅ [3b] CREATE VECTOR INDEX OK (C-SPANN, feature #1/4 CockroachDB)")
                except Exception as exc:  # noqa: BLE001
                    print(f"❌ [3b] CREATE VECTOR INDEX lỗi: {exc}")
                    print("   → thử: SET CLUSTER SETTING feature.vector_index.enabled = true; (nếu <v25.4)")

                try:
                    cur.execute("INSERT INTO _crdb_verify_tmp VALUES (1, '[1,2,3]'), (2, '[4,5,6]');")
                    cur.execute("SELECT id FROM _crdb_verify_tmp ORDER BY v <=> '[1,2,3]' LIMIT 1;")
                    nearest = cur.fetchone()[0]
                    ok_ann = nearest == 1
                    print(f"✅ [4] ANN search `<=>` OK (gần [1,2,3] nhất = id {nearest})")
                except Exception as exc:  # noqa: BLE001
                    print(f"❌ [4] ANN search lỗi: {exc}")

            cur.execute("DROP TABLE IF EXISTS _crdb_verify_tmp;")

    print("\n=== KẾT LUẬN P0 ===")
    print(f"  Kết nối        : {'✅' if True else '❌'}")
    print(f"  VECTOR column  : {'✅' if ok_vector else '❌'}")
    print(f"  VECTOR INDEX   : {'✅' if ok_index else '❌'}  (feature #1/4)")
    print(f"  ANN <=> search : {'✅' if ok_ann else '❌'}")
    if ok_vector and ok_index and ok_ann:
        print("→ SẴN SÀNG Phase 1/2. Còn chốt feature #2/4 (MCP/ccloud) + neo ECS/S3.")
    else:
        print("→ CHƯA đạt — xem lỗi trên (version <v25.4? quyền? cluster setting?).")


if __name__ == "__main__":
    main()
