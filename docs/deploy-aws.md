# Deploy Legal Guard lên AWS (ECS/EC2 + S3) với CockroachDB

> **DRAFT (P5)** — soạn trước khi có tài khoản AWS; **chưa verify live**. Khác bản Alibaba
> ([`deploy-ecs.md`](deploy-ecs.md)): DB = **CockroachDB managed** (không self-host Postgres) + **S3** cho
> artifact/video. Mục tiêu: **demo URL live trên AWS** cho hackathon "Build with Agentic Memory".

## 0. Chuẩn bị
- [ ] Tài khoản **AWS** + region **ap-southeast-1 (Singapore)** — CÙNG vùng cluster CockroachDB (P0:
      CRDB Basic AWS ap-southeast-1, v26.2.1) → latency thấp nhất.
- [ ] **Cluster CockroachDB đã có** (P0 verified). Lấy **connection string** (Console → Connect →
      General connection string): `postgresql://<user>:<pass>@<host>:26257/<db>?sslmode=verify-full`.
- [ ] **Tên miền** cho HTTPS (mua hoặc DuckDNS) — Slack webhook + ổ khóa xanh.
- [ ] Sẵn `.env`: `QWEN_API_KEY`, `COCKROACHDB_URL` (= connection string trên; app tự chuẩn hóa scheme
      → `cockroachdb+psycopg://`), `REDIS_URL` (ElastiCache hoặc Upstash), `SLACK_*`, `DOMAIN`.
- [ ] **CockroachDB Cloud → Networking**: cho phép IP egress của AWS (EC2 EIP / NAT của ECS) trong
      **IP Allowlist**, HOẶC dùng **Private connectivity** (PrivateLink) nếu muốn không lộ public.

## Chọn 1 trong 2 đường

### Path A — EC2 + Docker Compose + Caddy *(khuyến nghị cho demo: nhanh, tái dùng stack sẵn có)*
Giống hệt bản Alibaba, chỉ đổi VM sang AWS EC2 và DB sang CockroachDB.

1. **EC2**: Ubuntu 24.04, `t3.small` (2 vCPU/2GB đủ — app chủ yếu chờ LLM), EBS 40GB, gán **Elastic IP**.
2. **Security Group** inbound: `22` (SSH, giới hạn IP bạn) · `80` (ACME challenge) · `443` (HTTPS).
3. **DNS**: bản ghi A `DOMAIN → <Elastic IP>`. Kiểm `dig +short <DOMAIN>`.
4. **Cài Docker + deploy**:
   ```bash
   ssh ubuntu@<EIP>
   curl -fsSL https://get.docker.com | sh
   git clone <repo-url> legalguard && cd legalguard
   git checkout feat/cockroachdb-agentic-memory        # nhánh bản CRDB
   cp .env.example .env && nano .env                    # QWEN_API_KEY, COCKROACHDB_URL, DOMAIN, SLACK_*, REDIS_URL
   ```
   > `.env`: đặt `DATABASE_URL` = **cùng** connection string CockroachDB (gộp 1 DB: app+memory+KB), hoặc
   > để `COCKROACHDB_URL` cho riêng memory. `AGENTIC_MEMORY=1` (mặc định ON). KHÔNG cần service Postgres.
5. **Chạy**: `docker compose -f docker-compose.prod.yml up -d --build`
   → app tự `alembic upgrade head` lên **CockroachDB** (tạo 9 bảng gồm `memory_episodes` 0017) → Caddy xin cert.
   > ✅ `docker-compose.prod.yml` = **app + caddy** (DB DÙNG NGOÀI qua `DATABASE_URL`) → hợp CRDB managed
   > NGAY, KHÔNG có service Postgres. (Tránh `docker-compose.ecs.yml` cho bản CRDB — nó self-host Postgres
   > `pgvector/pgvector:pg16` trong Docker; DB đã là CockroachDB managed nên không cần.)

### Path B — ECS Fargate + ALB + ACM *(AWS-native, nhiều bước hơn)*
1. **ECR**: `docker build` → push image (`Dockerfile` sẵn có, gồm antiword cho .doc).
2. **ECS Fargate service** (1 task, 0.5 vCPU/1GB): task def đặt env từ **AWS Secrets Manager**
   (`QWEN_API_KEY`, `COCKROACHDB_URL`, `SLACK_*`). Command mặc định của image (uvicorn) — KHÔNG cần Caddy.
3. **ALB** + **ACM cert** (DNS-validated cho `DOMAIN`) → HTTPS listener 443 → target group cổng 8000;
   health check `GET /health`.
4. **NAT Gateway** egress → thêm IP đó vào CockroachDB IP Allowlist (bước 0).
5. Migrate: chạy 1 lần `alembic upgrade head` (task one-off hoặc app tự chạy lúc boot).

## S3 (artifact + video demo)
- Bucket `legalguard-artifacts-<region>`; dùng cho: file HĐ upload lớn / .docx redline export / **host video demo**.
- App: nếu bật lưu artifact ra S3 → thêm `boto3` + env `S3_BUCKET`/`AWS_REGION` (IAM role của ECS task/EC2,
  **không** hardcode key). *(Hiện app lưu excerpt trong DB, không lưu toàn văn — S3 là tùy chọn mở rộng.)*

## Verify (sau khi live)
```bash
curl https://<DOMAIN>/health                    # {"status":"ok"}
# xác nhận app nối CRDB (không phải sqlite/pg-local):
#   trong container: python -c "from legalguard.config.settings import settings; print(settings.database_url[:20])"
curl -XPOST https://<DOMAIN>/monitor/run -d '{"since":"2026-07-01"}'   # autopilot chạy
```
Mở `https://<DOMAIN>/app` (rà soát HĐ) · `/lookup` · `/trust`. Slack Event URL → `https://<DOMAIN>/channels/slack/events` → **Verified**.

## Demo agentic-memory (điểm chấm #1) trên bản live
Theo script `docs/internal/agentic-memory-devpost-draft.md §7`: Deal 1 với "ACME" → chốt → memory ghi
vào CRDB VECTOR; Deal 2 cùng "ACME" → agent recall tiền lệ; xoá case → cascade erasure. Cho xem
`recall_memory` qua MCP client.

## TODO trước nộp (cần AWS acct — S1)
- [ ] Provision AWS + chốt Path A/B → điền IP/domain thật, **verify từng lệnh** ở trên.
- [ ] Cập nhật `docker-compose.ecs.yml` bỏ service Postgres (DB = CRDB managed).
- [ ] Đo latency app↔CRDB (cùng region ap-southeast-1) so pg-local.
- [ ] Chốt IP allowlist / PrivateLink cho CockroachDB Cloud.
