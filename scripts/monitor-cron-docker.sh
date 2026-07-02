#!/bin/sh
# AUTOPILOT (biến thể Docker — service autopilot-cron trong docker-compose.ecs.yml):
# quét luật MỚI hiệu lực từ HÔM QUA qua POST /monitor/run của service app.
# - Digest in ra stdout container → xem bằng: docker compose logs autopilot-cron
# - Có EXPERT_CHANNEL (Slack channel ID, truyền qua env) → gửi digest vào Slack.
set -u
KEY=$(printf %s "${API_KEYS:-}" | tr -d '"' | cut -d, -f1 | cut -d: -f1)
CHANNEL="${EXPERT_CHANNEL:-}"
# date -d @epoch chạy cả busybox (alpine) lẫn GNU → hôm qua = epoch - 86400
SINCE=$(date -d "@$(( $(date +%s) - 86400 ))" +%F)
if [ -n "$CHANNEL" ]; then
  BODY="{\"since\":\"$SINCE\",\"via\":\"slack\",\"channel\":\"$CHANNEL\"}"
else
  BODY="{\"since\":\"$SINCE\"}"
fi
echo "[$(date -Iseconds)] autopilot monitor/run since=$SINCE channel=${CHANNEL:-<log-only>}"
if [ -n "$KEY" ]; then
  curl -s -m 300 -XPOST http://app:8000/monitor/run \
    -H "Content-Type: application/json" -H "X-API-Key: $KEY" -d "$BODY"
else
  curl -s -m 300 -XPOST http://app:8000/monitor/run \
    -H "Content-Type: application/json" -d "$BODY"
fi
echo
