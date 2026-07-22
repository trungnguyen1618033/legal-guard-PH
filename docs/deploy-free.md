# Deploy Legal Guard với chi phí $0 (free tier)

> Cho demo/chấm điểm: 1 URL HTTPS live, **$0**. Chìa khóa: mọi state ở **CockroachDB Cloud Basic (miễn phí)**
> nên chỉ phải chạy **app (+ HTTPS)** — không self-host DB/Redis. Xem thêm `docs/deploy-aws.md` (AWS chi tiết).

## Vì sao KHÔNG cần deploy Postgres / Redis (bỏ hẳn, không "deploy nửa")
| Thành phần | Ở đâu | Phải tự deploy? |
|---|---|---|
| DB (cases · memory · KB vectors · conversation) | **CockroachDB Cloud Basic** (managed, free) | ❌ chỉ trỏ `DATABASE_URL` |
| Chat/session store | `conversation_backend=sql` (mặc định) → **trong CRDB** | ❌ |
| Rate-limit / dedup / lock hội thoại | **in-process** (1 instance) | ❌ |
| Redis | chỉ cần khi `conversation_backend=redis` **và** đa-instance | ❌ (demo 1 instance) |

→ Deploy = **chỉ `app` (+ `caddy` cho HTTPS trên VM)**. `docker-compose.prod.yml` VỐN đã đúng vậy (app+caddy,
DB ngoài). Bỏ Redis: để trống `REDIS_URL` + `conversation_backend=sql`. Mất gì? Chỉ **đa-instance scale** —
demo 1 instance không cần; bộ nhớ hội thoại vẫn đầy đủ (lưu CRDB).

## `.env` tối thiểu (free, 1 instance)
```
QWEN_API_KEY=sk-...
DATABASE_URL=postgresql://<user>:<pass>@<host>:26257/defaultdb?sslmode=verify-full   # CockroachDB (tự chuẩn hóa scheme)
AGENTIC_MEMORY=1
CONVERSATION_BACKEND=sql            # KHÔNG cần Redis
# REDIS_URL=                        # để trống
# DOMAIN=your.domain                # chỉ cần cho path VM + Caddy HTTPS
```

## Chọn 1 host free

### A. Google Cloud Run — *truly free, scale-to-zero (khuyến nghị nếu AWS không bắt buộc)*
Free tier 2M req/tháng, **tự scale 0→N**, HTTPS sẵn, không cần Caddy. Không tốn tiền lúc rảnh.
```bash
gcloud run deploy legalguard --source . --region asia-southeast1 \
  --allow-unauthenticated --port 8000 \
  --set-env-vars "AGENTIC_MEMORY=1,CONVERSATION_BACKEND=sql" \
  --set-secrets "QWEN_API_KEY=qwen:latest,DATABASE_URL=crdb:latest"   # dùng Secret Manager
```
→ nhận URL `https://legalguard-...run.app`. Migrate: app tự `alembic upgrade head` lúc boot (hoặc 1 job one-off).
Cold start ~vài giây (warm bằng `curl /health` trước khi demo).

### B. AWS EC2 free-tier `t3.micro` — *aligned hackathon "trên AWS", free 12 tháng*
750h/tháng × 12 tháng = $0 cho kỳ chấm. Dùng `docker-compose.prod.yml` (app+caddy).
```bash
# EC2 Ubuntu t3.micro (1GB đủ vì DB ngoài) + Elastic IP + SG mở 22/80/443 + DNS A → EIP
ssh ubuntu@<EIP>; curl -fsSL https://get.docker.com | sh
git clone <repo> lg && cd lg && git checkout feat/cockroachdb-agentic-memory
cp .env.example .env && nano .env      # điền như trên + DOMAIN
docker compose -f docker-compose.prod.yml up -d --build     # KHÔNG dùng ecs.yml (nó self-host pg/redis)
```
Chi tiết + Path B (ECS Fargate) ở `docs/deploy-aws.md`. Always-on (không cold start).

### C. Oracle Cloud Always Free (ARM Ampere, tới 24GB) — *$0 vĩnh viễn*
Giống B nhưng VM Oracle always-free (không giới hạn 12 tháng). Dư sức, always-on. Không phải "AWS".

### D. Hugging Face Spaces (Docker) — *nhanh nhất cho 1 URL demo*
Tạo Docker Space, expose 8000, đặt secrets (QWEN_API_KEY/DATABASE_URL) trong Settings. HTTPS sẵn. Có branding HF; ngủ sau 48h idle.

## Verify sau khi live
```bash
curl https://<URL>/health                       # {"status":"ok"}
curl -XPOST https://<URL>/monitor/run -d '{"since":"2026-07-01"}'
```
Mở `/app` (rà HĐ) · `/lookup` · `/trust`. Demo agentic-memory: script `docs/internal/agentic-memory-devpost-draft.md §7`.

---

## Scale khi cần — CÓ phải thiết kế lại không? **KHÔNG.**
Kiến trúc đã sẵn cho scale (phân tích đầy đủ: `docs/internal/scale-concurrency.md`). Lý do:

- **Hexagonal ports** → đổi hạ tầng = thêm adapter + 1 dòng `container.py`, `domain/` bất biến.
- **CockroachDB = chính là câu chuyện scale**: distributed SQL, thêm node → tăng tải, KHÔNG reshard. Mọi
  state (cases/memory/KB/conversation) đã ở CRDB → **app gần như stateless**.
- **Nghẽn thật KHÔNG phải server** mà là **quota LLM (TPM)** — 1 account ≈ ~8 `/analyze` đồng thời → 1
  instance dư cho demo (theo `scale-concurrency.md` + `capacity.md`).

**Đường scale (tăng dần, KHÔNG đại tu)** — chỉ khi thật sự đông:
1. **Lock hội thoại in-process → distributed** (Redis `SETNX`+TTL, hoặc CRDB `SELECT…FOR UPDATE`) — sau port sẵn có, chỉ thay adapter lock. Đây là thay đổi DUY NHẤT cần cho đa-instance đúng đắn.
2. **State ra shared** (rate-limit/dedup) → CRDB/Redis (app stateless hoàn toàn).
3. **Queue + Worker** (Arq/Redis): web ack+enqueue → worker pool; autoscale theo queue-depth; backpressure.
4. **Async httpx** LLM (1 process ôm nhiều call in-flight) + **semaphore** chống 429 + **semantic cache** (đã có) + **xoay multi-account** để nhân quota (trần thật).
5. **Autoscale + LB** (Cloud Run tự làm; ECS/K8s theo RPS/queue).

→ Demo: 1 instance như trên là đủ. "Dễ scale" đã nằm trong thiết kế — khi cần chỉ swap lock + thêm queue/worker sau các port hiện có, **không viết lại domain**.
