#!/bin/sh
# AUTOPILOT hằng ngày: quét luật MỚI hiệu lực từ hôm qua → digest.
# - Luôn ghi kết quả vào log (bằng chứng agent chạy khi bạn ngủ).
# - Nếu EXPERT_CHANNEL có trong .env → gửi digest vào Slack channel đó.
set -u
ENVF=/root/legalguard/.env
KEY=$(grep -E "^API_KEYS=" "$ENVF" | cut -d= -f2- | tr -d '"' | cut -d: -f1)
CHANNEL=$(grep -E "^EXPERT_CHANNEL=" "$ENVF" | cut -d= -f2- | tr -d '"')
SINCE=$(date -d yesterday +%F)
if [ -n "$CHANNEL" ]; then
  BODY="{\"since\":\"$SINCE\",\"via\":\"slack\",\"channel\":\"$CHANNEL\"}"
else
  BODY="{\"since\":\"$SINCE\"}"
fi
echo "[$(date -Is)] monitor/run since=$SINCE channel=${CHANNEL:-<log-only>}"
curl -s -m 300 -XPOST http://127.0.0.1:8000/monitor/run \
  -H "Content-Type: application/json" -H "X-API-Key: $KEY" -d "$BODY"
echo
# NHẮC HẠN sau-ký (autopilot A) — nghĩa vụ đến hạn trong 14 ngày (best-effort).
if [ -n "$CHANNEL" ]; then OBODY="{\"within_days\":14,\"via\":\"slack\",\"channel\":\"$CHANNEL\"}"; else OBODY="{\"within_days\":14}"; fi
echo "[$(date -Is)] obligations/run within=14 channel=${CHANNEL:-<log-only>}"
curl -s -m 120 -XPOST http://127.0.0.1:8000/obligations/run \
  -H "Content-Type: application/json" -H "X-API-Key: $KEY" -d "$OBODY"
echo
