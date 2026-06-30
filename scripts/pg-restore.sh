#!/usr/bin/env bash
# Khôi phục Postgres self-host (docker-compose.ecs.yml) từ file .sql.gz do pg-backup.sh tạo.
# Bổ trợ cho scripts/pg-backup.sh — đóng vòng "backup → kiểm tra khôi phục được".
#
# DÙNG:
#   ./scripts/pg-restore.sh <file.sql.gz>            # khôi phục vào DB hiện tại (HỎI xác nhận)
#   ./scripts/pg-restore.sh --latest                 # lấy bản mới nhất trong BACKUP_DIR
#   ./scripts/pg-restore.sh --from-oss oss://b/db/x.sql.gz   # tải từ OSS rồi khôi phục
#   ./scripts/pg-restore.sh --verify <file.sql.gz>   # KHÔNG đụng DB thật: dựng DB tạm, nạp, đếm bảng → PASS/FAIL
#   FORCE=1 ./scripts/pg-restore.sh <file>           # bỏ qua prompt xác nhận (dùng cho tự động)
#
# An toàn: mặc định HỎI trước khi ghi đè (drop + recreate schema public). --verify KHÔNG đụng DB thật.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$HOME/legalguard}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.ecs.yml}"
DB_SERVICE="${DB_SERVICE:-db}"
DB_USER="${DB_USER:-legalguard}"
DB_NAME="${DB_NAME:-legalguard}"
BACKUP_DIR="${BACKUP_DIR:-/backup/legalguard}"

cd "$PROJECT_DIR"

dc() { docker compose -f "$COMPOSE_FILE" "$@"; }

usage() { sed -n '2,18p' "$0"; exit "${1:-0}"; }

MODE="restore"
FILE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --latest)
            FILE="$(ls -1t "$BACKUP_DIR"/legalguard_*.sql.gz 2>/dev/null | head -1 || true)"
            [ -n "$FILE" ] || { echo "❌ Không tìm thấy backup trong $BACKUP_DIR" >&2; exit 1; }
            shift ;;
        --from-oss)
            shift
            SRC="${1:?cần URL oss://...}"
            command -v ossutil >/dev/null 2>&1 || { echo "❌ chưa cài ossutil" >&2; exit 1; }
            FILE="/tmp/$(basename "$SRC")"
            echo "tải $SRC → $FILE"
            ossutil cp -f "$SRC" "$FILE"
            shift ;;
        --verify) MODE="verify"; shift ;;
        -h|--help) usage 0 ;;
        *) FILE="$1"; shift ;;
    esac
done

[ -n "$FILE" ] || usage 1
[ -s "$FILE" ] || { echo "❌ File rỗng hoặc không tồn tại: $FILE" >&2; exit 1; }

# Kiểm gzip hợp lệ trước khi đụng DB
gunzip -t "$FILE" 2>/dev/null || { echo "❌ Không phải gzip hợp lệ: $FILE" >&2; exit 1; }
echo "Nguồn: $FILE ($(du -h "$FILE" | cut -f1))"

if [ "$MODE" = "verify" ]; then
    # Dựng DB tạm trong CÙNG container Postgres, nạp dump, đếm bảng — KHÔNG đụng DB thật.
    TMPDB="verify_$(date +%s)"
    echo "[verify] tạo DB tạm: $TMPDB"
    dc exec -T "$DB_SERVICE" psql -U "$DB_USER" -d postgres -c "CREATE DATABASE $TMPDB;" >/dev/null
    cleanup() { dc exec -T "$DB_SERVICE" psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS $TMPDB;" >/dev/null 2>&1 || true; }
    trap cleanup EXIT
    echo "[verify] nạp dump…"
    if ! gunzip -c "$FILE" | dc exec -T "$DB_SERVICE" psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$TMPDB" >/dev/null 2>&1; then
        echo "❌ [verify] FAIL — nạp dump lỗi" >&2
        exit 1
    fi
    N="$(dc exec -T "$DB_SERVICE" psql -tA -U "$DB_USER" -d "$TMPDB" \
        -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" | tr -d '[:space:]')"
    if [ "${N:-0}" -ge 1 ]; then
        echo "✅ [verify] PASS — khôi phục được, $N bảng trong schema public."
        exit 0
    fi
    echo "❌ [verify] FAIL — 0 bảng sau khi nạp" >&2
    exit 1
fi

# --- Khôi phục thật (ghi đè DB hiện tại) ---
echo "⚠️  Sắp GHI ĐÈ database '$DB_NAME' (drop + recreate schema public)."
if [ "${FORCE:-0}" != "1" ]; then
    printf "Gõ 'yes' để tiếp tục: "
    read -r ans
    [ "$ans" = "yes" ] || { echo "Huỷ."; exit 0; }
fi

echo "[restore] reset schema public…"
dc exec -T "$DB_SERVICE" psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" \
    -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;" >/dev/null

echo "[restore] nạp dump…"
gunzip -c "$FILE" | dc exec -T "$DB_SERVICE" psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" >/dev/null

N="$(dc exec -T "$DB_SERVICE" psql -tA -U "$DB_USER" -d "$DB_NAME" \
    -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" | tr -d '[:space:]')"
echo "✅ [restore] xong — $N bảng. Khuyến nghị chạy: alembic upgrade head (đồng bộ migration head)."
