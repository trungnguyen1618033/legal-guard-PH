#!/bin/sh
# AUTOPILOT (biến thể Docker — service autopilot-cron trong docker-compose.ecs.yml):
# quét luật MỚI qua POST /monitor/run của service app.
# - Digest in ra stdout container → xem bằng: docker compose logs autopilot-cron
# - Có EXPERT_CHANNEL (Slack channel ID, truyền qua env) → gửi digest vào Slack.
# - BỀN: retry 3 lần (app có thể đang restart lúc 5AM) + state file /state/last_success
#   để lần chạy sau QUÉT BÙ từ ngày thành-công-cuối (server down 1 ngày → không sót luật;
#   đổi lại có thể báo trùng 1 ngày biên — chấp nhận: báo 2 lần tốt hơn sót vĩnh viễn).
set -u
KEY=$(printf %s "${API_KEYS:-}" | tr -d '"' | cut -d, -f1 | cut -d: -f1)
CHANNEL="${EXPERT_CHANNEL:-}"
STATE=/state/last_success
# date -d @epoch chạy cả busybox (alpine) lẫn GNU → hôm qua = epoch - 86400
YESTERDAY=$(date -d "@$(( $(date +%s) - 86400 ))" +%F)
SINCE=$YESTERDAY
if [ -f "$STATE" ]; then
  SAVED=$(cat "$STATE" 2>/dev/null)
  # chỉ nhận YYYY-MM-DD hợp lệ và KHÔNG mới hơn hôm qua (so sánh chuỗi ISO là đủ)
  if echo "$SAVED" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' && [ "$SAVED" \< "$YESTERDAY" ]; then
    SINCE=$SAVED
  fi
fi
if [ -n "$CHANNEL" ]; then
  BODY="{\"since\":\"$SINCE\",\"via\":\"slack\",\"channel\":\"$CHANNEL\"}"
else
  BODY="{\"since\":\"$SINCE\"}"
fi
echo "[$(date -Iseconds)] autopilot monitor/run since=$SINCE channel=${CHANNEL:-<log-only>}"
ATTEMPT=1
while [ $ATTEMPT -le 3 ]; do
  if [ -n "$KEY" ]; then
    CODE=$(curl -s -m 300 -o /tmp/monitor-resp.json -w "%{http_code}" -XPOST http://app:8000/monitor/run \
      -H "Content-Type: application/json" -H "X-API-Key: $KEY" -d "$BODY")
  else
    CODE=$(curl -s -m 300 -o /tmp/monitor-resp.json -w "%{http_code}" -XPOST http://app:8000/monitor/run \
      -H "Content-Type: application/json" -d "$BODY")
  fi
  if [ "$CODE" = "200" ]; then
    cat /tmp/monitor-resp.json; echo
    mkdir -p /state && echo "$YESTERDAY" > "$STATE"   # lần sau quét từ hôm-qua-của-lần-thành-công
    exit 0
  fi
  echo "[$(date -Iseconds)] attempt $ATTEMPT/3 failed (HTTP ${CODE:-timeout}) — retry in 120s"
  ATTEMPT=$((ATTEMPT + 1))
  [ $ATTEMPT -le 3 ] && sleep 120
done
echo "[$(date -Iseconds)] [ERROR] monitor/run FAILED after 3 attempts — since=$SINCE giữ nguyên, lần sau quét bù"
exit 1
