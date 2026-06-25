# Deploy Legal Guard lên Alibaba Cloud ECS — bản SELF-CONTAINED (app + Caddy + Postgres + Redis)

Mọi thứ chạy trong Docker trên **một** ECS: không cần Neon/Upstash → **$0 dịch vụ ngoài** (chỉ trả tiền
máy ECS, vốn rất rẻ + thường nằm trong credit). HTTPS thật qua **Caddy + DuckDNS** (cho Slack webhook +
yêu cầu "backend trên Alibaba Cloud" của Qwen hackathon).

> Bản thay thế dùng Neon + Upstash: [`deploy-ecs.md`](deploy-ecs.md). Chọn 1 trong 2.
> Deploy từ branch **`dev`** (code đang ở đó; `main` để trống cũng được).

---

## 0. Cần chuẩn bị
- Tài khoản Alibaba Cloud (có credit).
- `QWEN_API_KEY`, `GEMINI_API_KEY` (key thật).
- **Repo public** để `git clone https://...` không cần đăng nhập (nếu private → xem mục cuối).

## 1. Tạo ECS (console Alibaba)
ECS → Create Instance:
- Region **Singapore** (gần Qwen/DashScope nhất).
- Type **2 vCPU / 2–4GB** (ecs.t6 / e-family) — đủ, app chủ yếu chờ LLM.
- OS **Ubuntu 24.04 LTS**. Public IP: **Assign**. Disk 40GB.
- Ghi lại **IP public**.

## 2. Mở port (Security Group)
Inbound `0.0.0.0/0`: **22** (SSH — nên giới hạn IP của bạn), **80** (HTTP/Let's Encrypt), **443** (HTTPS).
> KHÔNG mở 5432/6379/8000 ra ngoài — DB/Redis/API thô chỉ truy cập qua SSH tunnel (mục 8).

## 3. DuckDNS (domain free)
1. [duckdns.org](https://www.duckdns.org) → đăng nhập → tạo subdomain, vd `legalguard` → có `legalguard.duckdns.org`.
2. Ô **current ip** điền **IP public ECS** → Update.
3. Kiểm (máy bạn): `dig +short legalguard.duckdns.org` → đúng IP.

## 4. SSH + cài Docker
```bash
ssh root@<IP-ECS>
curl -fsSL https://get.docker.com | sh
docker --version
```

## 5. Clone code (branch dev) + tạo `.env`
ECS là **máy ảo Linux trần** — KHÔNG có "env panel". Env = **file `.env`** trong thư mục code (docker-compose tự đọc).
```bash
git clone -b dev https://github.com/trungnguyen1618033/legal-guard-PH.git legalguard
cd legalguard
cp .env.example .env
nano .env          # ← "nơi thiết kế env": sửa rồi Ctrl+O lưu, Ctrl+X thoát
```
Cách self-contained chỉ cần sửa **3 dòng** trong `.env`:
```ini
QWEN_API_KEY=sk-...
GEMINI_API_KEY=...
DOMAIN=legalguard.duckdns.org
```
Không cần đụng `DATABASE_URL`/`REDIS_URL` — `docker-compose.ecs.yml` đã trỏ sang Postgres/Redis nội bộ.
`QWEN_FAST_MODEL=qwen-flash` và `LOG_LEVEL=INFO` đã có default. Demo mở: giữ `REQUIRE_AUTH=false`;
khoá thật: `REQUIRE_AUTH=true` + `API_KEYS="key:org:VN"`.

## 6. Chạy
```bash
docker compose -f docker-compose.ecs.yml up -d --build
```
app tự `alembic upgrade head` → uvicorn; Caddy tự xin cert TLS cho DOMAIN.

## 7. Kiểm tra
```bash
docker compose -f docker-compose.ecs.yml ps                  # app/caddy/db/redis đều Up (healthy)
docker compose -f docker-compose.ecs.yml logs -f caddy        # thấy "certificate obtained"
curl https://legalguard.duckdns.org/health                    # {"status":"ok",...}
curl https://legalguard.duckdns.org/ready                     # {"ready":true} (DB nối được)
```
Trình duyệt: `/app` (rà soát HĐ) · `/lookup` (tra cứu + cảnh báo VB mới) · `/dashboard`.

Slack: Event Subscriptions → Request URL `https://legalguard.duckdns.org/channels/slack/events` → Verified.

---

## 8. Chọc vào DB / Redis / API từ MÁY LOCAL (an toàn, qua SSH tunnel)
DB/Redis chỉ bind `127.0.0.1` của ECS (không lộ internet). Mở tunnel từ máy bạn:
```bash
# Postgres → nối client local (psql/DBeaver/TablePlus) tới localhost:5432
ssh -L 5432:127.0.0.1:5432 root@<IP-ECS>
psql "postgresql://legalguard:legalguard@localhost:5432/legalguard"   # ở terminal khác

# Redis → redis-cli local tới localhost:6379
ssh -L 6379:127.0.0.1:6379 root@<IP-ECS>

# API thô (bỏ qua Caddy/HTTPS) để debug
ssh -L 8000:127.0.0.1:8000 root@<IP-ECS>   # rồi mở http://localhost:8000/docs
```
Hoặc chọc nhanh ngay trên ECS, không cần client local:
```bash
docker compose -f docker-compose.ecs.yml exec db psql -U legalguard
docker compose -f docker-compose.ecs.yml exec redis redis-cli
```

## 9. Backup DB
Dữ liệu nằm trong Docker volume `pgdata` (sống qua `down`, **mất khi `down -v` hoặc xoá ECS**).
> **Local dev DB (`data/cases.db`) KHÔNG cần backup** — chỉ là dữ liệu test, không lên prod (ECS khởi tạo Postgres rỗng).
```bash
# Backup ra file (chạy trên ECS, trong thư mục legalguard)
docker compose -f docker-compose.ecs.yml exec -T db pg_dump -U legalguard legalguard > backup_$(date +%F).sql

# Khôi phục
cat backup_2026-06-26.sql | docker compose -f docker-compose.ecs.yml exec -T db psql -U legalguard legalguard

# Tải backup về máy local
scp root@<IP-ECS>:/root/legalguard/backup_*.sql .
```
Bền hơn: bật **ECS Snapshot** (console Alibaba) lịch tự động cho ổ đĩa; hoặc khi cần bền cao → chuyển DB sang Neon (đổi `DATABASE_URL` trong `.env`, bỏ service `db`).

## 10. Log & debug
`LOG_LEVEL=INFO` (mặc định) → log `legalguard.*` hiện trong container (timing analyze, cảnh báo auth, lỗi degrade).
```bash
docker compose -f docker-compose.ecs.yml logs -f app          # log app (theo dõi realtime)
docker compose -f docker-compose.ecs.yml logs --tail=200 app  # 200 dòng gần nhất
docker compose -f docker-compose.ecs.yml logs -f caddy        # TLS/proxy
docker compose -f docker-compose.ecs.yml restart app          # restart sau khi đổi .env
```
Cần chi tiết hơn: đặt `LOG_LEVEL=DEBUG` trong `.env` → `restart app`. Log mẫu hữu ích:
`agent loop (1 window) …ms` · `post-agent (verify∥summary∥legal_basis) …ms` · `analyze tenant=VN risks=…`.

## 11. Vận hành / cập nhật code
```bash
git pull && docker compose -f docker-compose.ecs.yml up -d --build   # cập nhật
docker compose -f docker-compose.ecs.yml down                        # dừng (GIỮ dữ liệu)
docker compose -f docker-compose.ecs.yml down -v                     # dừng + XOÁ dữ liệu (cẩn thận)
```

## Sự cố thường gặp
| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| Caddy không lấy cert | DNS chưa trỏ / port 80 chưa mở | `dig +short <DOMAIN>`; kiểm Security Group |
| `502 Bad Gateway` | app đang migrate/khởi động | đợi ~40s; `logs app` |
| app `unhealthy` | DB chưa sẵn / .env sai | `logs app`; `ps` xem db healthy chưa |
| Slack không verify | domain chưa HTTPS xong | `curl https://<DOMAIN>/health` phải 200 |
| clone đòi mật khẩu | repo private | xem mục dưới |

## Repo private?
Dùng Personal Access Token (GitHub → Settings → Developer settings → Tokens, scope `repo`):
```bash
git clone -b dev https://<TOKEN>@github.com/trungnguyen1618033/legal-guard-PH.git legalguard
```
Hoặc tạo SSH deploy key trên ECS (`ssh-keygen` → thêm public key vào repo → Deploy keys).
