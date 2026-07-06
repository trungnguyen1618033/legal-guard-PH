#!/usr/bin/env bash
# Live smoke test — gọi endpoint THẬT của deploy, xác nhận từng chức năng chạy (không phải unit test stub).
#
# Dùng (chạy từ gốc repo):
#   bash scripts/live_smoke.sh                       # test production (mặc định)
#   BASE=http://localhost:8000 bash scripts/live_smoke.sh   # test local (uv run uvicorn app:app)
#   SKIP_LLM=1 bash scripts/live_smoke.sh            # bỏ endpoint LLM chậm (analyze/negotiate/ask/counter)
#   API_KEY=xxx bash scripts/live_smoke.sh           # key tường minh (mặc định đọc từ .env API_KEYS)
#
# Key KHÔNG in ra. Exit 0 nếu tất cả pass, 1 nếu có fail.
set -uo pipefail

BASE="${BASE:-https://legalguard.duckdns.org}"
KEY="${API_KEY:-$(grep -E '^API_KEYS=' .env 2>/dev/null | sed -E 's/^API_KEYS=//; s/^"//; s/"$//' | cut -d, -f1 | cut -d: -f1)}"
[ -z "${KEY:-}" ] && { echo "❌ Không tìm thấy API key (đặt API_KEY=... hoặc API_KEYS trong .env)"; exit 1; }
H=(-H "x-tenant-id: VN" -H "x-api-key: $KEY")

now() { python3 -c 'import time;print(int(time.time()*1000))'; }
pass=0; fail=0

# check <tên> <METHOD> <path> <chuỗi-mong-đợi-trong-body> [curl args thêm...]
check() {
  local name="$1" method="$2" path="$3" expect="$4"; shift 4
  local t0 code ms body
  t0=$(now)
  code=$(curl -s -m 300 -o /tmp/lsmoke.$$ -w "%{http_code}" -X "$method" "${H[@]}" "$@" "$BASE$path")
  ms=$(( $(now) - t0 ))
  if [ "$code" = "200" ] && grep -q "$expect" "/tmp/lsmoke.$$" 2>/dev/null; then
    printf "✅ %-24s %s %6dms\n" "$name" "$code" "$ms"; pass=$((pass+1))
  else
    body=$(head -c 160 "/tmp/lsmoke.$$" 2>/dev/null | tr '\n' ' ')
    printf "❌ %-24s %s %6dms | %s\n" "$name" "$code" "$ms" "$body"; fail=$((fail+1))
  fi
}

echo "== Live smoke: $BASE =="

# --- Tất định / nhanh (không LLM) ---
check "health"             GET  /health "qwen_ready"
check "trust.json"         GET  /trust.json "54/54"
check "runs (AI evidence)" GET  /runs "totals"
check "dashboard"          GET  /insights/dashboard "cases"
check "tactics (flywheel)" GET  /insights/tactics "{"
check "graph"              GET  "/graph/123/2020/N%C4%90-CP" "nodes"
check "latest"             GET  "/latest/123/2020/N%C4%90-CP" "latest"
check "impact (autopilot)" GET  "/impact/70/2025/N%C4%90-CP" "impacted_cases"
check "redline"            POST /redline "redline" -H "Content-Type: application/json" \
  -d '{"old":"phạt 8%","new":"phạt 15% mỗi ngày"}'
check "amendments/compile" POST /amendments/compile "rows" -H "Content-Type: application/json" \
  -d '{"items":[{"clause":"Điều 5","issue":"phạt 15%","legal_status":"illegal","legal_basis":"Đ.301","suggestion":"về 8%","priority":"must_fix"}]}'

# --- LLM (chậm — bỏ bằng SKIP_LLM=1) ---
if [ "${SKIP_LLM:-0}" != "1" ]; then
  check "ask (lookup)"     POST /ask "Trả lời" -H "Content-Type: application/json" \
    -d '{"question":"Phạt vi phạm hợp đồng thương mại tối đa bao nhiêu phần trăm?"}'
  check "negotiate (moat)" POST /negotiate "status" -H "Content-Type: application/json" \
    -d '{"deal_context":"HĐ: must_fix trọng tài tại Việt Nam. Còn mở: đặt cọc.","partner_message":"Chúng tôi đồng ý đặt cọc 10% nhưng bắt buộc trọng tài Bắc Kinh, không đổi.","alternatives":true,"state":{"red_lines":["Trọng tài tại Việt Nam"],"open_items":["đặt cọc"]}}'
  check "counter-clause"   POST /counter "vi" -H "Content-Type: application/json" \
    -d '{"clause":"Phạt 15%","risk":"vượt trần 8%","suggestion":"đưa về 8%","legal_basis":"Điều 301 Luật Thương mại 2005","leverage":"balanced"}'
  check "analyze (chậm)"   POST /analyze "risks" \
    --data-urlencode "text=Điều 5: Bên B chậm giao hàng chịu phạt 15% giá trị hợp đồng thương mại cho mỗi ngày chậm." \
    -d "lang=vi" -d "leverage=weak"
fi

rm -f "/tmp/lsmoke.$$"
echo "== $pass pass · $fail fail =="
[ "$fail" -eq 0 ]
