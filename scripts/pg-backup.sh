#!/usr/bin/env bash
# Backup Postgres self-host (docker-compose.ecs.yml) → file .sql.gz + đẩy lên Alibaba OSS.
# Thay cho "restore window" của Neon khi tự-host. Chạy bằng cron hằng ngày TRÊN ECS.
#
# TIỀN ĐỀ trên ECS:
#   - Đã chạy: docker compose -f docker-compose.ecs.yml up -d  (db container Up)
#   - ossutil đã cài + cấu hình (~/.ossutilconfig có AccessKey) — nếu chưa, xem cuối file.
#
# CÀI cron (mỗi ngày 03:00, log ra /var/log):
#   chmod +x scripts/pg-backup.sh
#   ( crontab -l 2>/dev/null; echo "0 3 * * * cd $HOME/legalguard && OSS_BUCKET=oss://<bucket>/db ./scripts/pg-backup.sh >> /var/log/pg-backup.log 2>&1" ) | crontab -
set -euo pipefail

# --- Cấu hình (override qua biến môi trường) ---
PROJECT_DIR="${PROJECT_DIR:-$HOME/legalguard}"     # nơi có docker-compose.ecs.yml
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.ecs.yml}"
DB_SERVICE="${DB_SERVICE:-db}"
DB_USER="${DB_USER:-legalguard}"
DB_NAME="${DB_NAME:-legalguard}"
BACKUP_DIR="${BACKUP_DIR:-/backup/legalguard}"      # thư mục local trên ECS
KEEP_DAYS="${KEEP_DAYS:-7}"                          # giữ bao nhiêu ngày local
OSS_BUCKET="${OSS_BUCKET:-}"                         # vd oss://my-bucket/db  (rỗng = bỏ qua upload)

cd "$PROJECT_DIR"
mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/legalguard_${STAMP}.sql.gz"

echo "[$(date)] pg_dump → $OUT"
# -T: không cấp TTY (chạy trong cron). pg_dump trong container qua socket nội bộ.
docker compose -f "$COMPOSE_FILE" exec -T "$DB_SERVICE" \
    pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$OUT"

# Kiểm file không rỗng (pg_dump lỗi → file 0 byte → coi như fail)
if [ ! -s "$OUT" ]; then
    echo "[$(date)] ❌ Backup RỖNG — pg_dump thất bại" >&2
    rm -f "$OUT"
    exit 1
fi
echo "[$(date)] ✅ $(du -h "$OUT" | cut -f1)"

# Đẩy lên OSS (nếu cấu hình)
if [ -n "$OSS_BUCKET" ]; then
    if command -v ossutil >/dev/null 2>&1; then
        echo "[$(date)] upload → $OSS_BUCKET/"
        ossutil cp -f "$OUT" "$OSS_BUCKET/"
    else
        echo "[$(date)] ⚠️ chưa cài ossutil — bỏ qua upload (file vẫn ở $OUT)" >&2
    fi
fi

# Xoá bản local cũ hơn KEEP_DAYS ngày
find "$BACKUP_DIR" -name 'legalguard_*.sql.gz' -mtime "+$KEEP_DAYS" -delete
echo "[$(date)] xong (giữ local $KEEP_DAYS ngày)."

# --- KHÔI PHỤC (khi cần) ---
#   gunzip -c legalguard_<stamp>.sql.gz | \
#     docker compose -f docker-compose.ecs.yml exec -T db psql -U legalguard -d legalguard
#
# --- Cài ossutil + cấu hình (1 lần, nếu muốn đẩy OSS) ---
#   curl -o /usr/local/bin/ossutil https://gosspublic.alicdn.com/ossutil/<ver>/ossutil64 && chmod +x ...
#   ossutil config   # nhập AccessKeyId/Secret + endpoint (vd oss-ap-southeast-1.aliyuncs.com)
#   (Khuyến nghị: đặt OSS lifecycle rule xoá object >30 ngày thay vì xoá tay.)
