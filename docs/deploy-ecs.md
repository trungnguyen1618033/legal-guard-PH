# Deploy Legal Guard lên Alibaba Cloud ECS + HTTPS

Hướng dẫn từng bước. Kết quả: app chạy production trên ECS, có HTTPS thật (cho Slack webhook +
yêu cầu "backend chạy trên Alibaba Cloud" của Qwen hackathon). DB dùng Neon, chat store dùng Upstash
(đã cấu hình), nên ECS chỉ chạy `app` + `caddy`.

## 0. Chuẩn bị (làm trước)
- [ ] **Tên miền** trỏ về IP ECS (HTTPS bắt buộc cần domain, không xin được cert cho IP trần):
  - Mua domain rẻ (Namecheap/Porkbun ~$1-10), HOẶC
  - Free: tạo subdomain tại [duckdns.org](https://www.duckdns.org) (vd `legalguard.duckdns.org`) — đủ cho test/demo.
- [ ] Tài khoản Alibaba Cloud (đã có credit ✓).
- [ ] Sẵn các giá trị `.env`: `QWEN_API_KEY`, `GEMINI_API_KEY`, `DATABASE_URL` (Neon, `postgresql+psycopg://...?sslmode=require`), `REDIS_URL` (Upstash `rediss://...`), `SLACK_SIGNING_SECRET`, `SLACK_BOT_TOKEN`, và `DOMAIN`.

## 1. Tạo ECS instance
1. Console Alibaba Cloud → **ECS → Create Instance**.
2. Region: **Singapore** (cùng vùng Qwen/DashScope + Neon + Upstash → nhanh nhất).
3. Instance type: nhỏ là đủ (app CPU ~0%, chủ yếu chờ LLM) — vd **2 vCPU / 2-4GB** (ecs.t6 / e-family).
4. OS: **Ubuntu 24.04 LTS**.
5. Public IP: **gán** (Assign Public IPv4) hoặc EIP.
6. Storage: 40GB là dư.

## 2. Mở port (Security Group)
Thêm inbound rules cho IP `0.0.0.0/0`:
- [ ] **22** (SSH — nên giới hạn IP của bạn)
- [ ] **80** (HTTP — Let's Encrypt challenge + redirect)
- [ ] **443** (HTTPS)

## 3. Trỏ DNS
Tại nhà cung cấp domain (hoặc DuckDNS): tạo bản ghi **A** `DOMAIN → <IP public của ECS>`.
Kiểm tra: `dig +short <DOMAIN>` trả đúng IP (đợi vài phút cho DNS lan).

## 4. Cài Docker trên ECS
```bash
ssh root@<IP-ECS>
curl -fsSL https://get.docker.com | sh
docker --version          # xác nhận
```

## 5. Đưa code lên + cấu hình
```bash
git clone <repo-url> legalguard && cd legalguard
cp .env.example .env
nano .env                 # điền key thật + DATABASE_URL/REDIS_URL + DOMAIN=<domain của bạn>
```
> ⚠️ `DOMAIN` phải khớp domain đã trỏ DNS ở bước 3. `DATABASE_URL` dùng scheme `postgresql+psycopg://`.

**Bảo mật (QUYẾT ĐỊNH TRƯỚC KHI MỞ RA INTERNET):**
- **Demo mở** (hackathon, ai có link cũng dùng được): để `REQUIRE_AUTH=false`, `API_KEYS=` rỗng — mọi
  caller chung org `default`. Vẫn có `RATE_LIMIT_PER_MIN` chặn abuse + `MAX_INPUT_CHARS` chặn chi phí.
  App log cảnh báo "API đang MỞ" mỗi lần khởi động (bình thường, nhắc bạn đây là chế độ mở).
- **Khóa thật** (có khách/đa công ty): đặt `REQUIRE_AUTH=true` + `API_KEYS="key1:acme:VN,key2:globex:VN"`
  → app TỪ CHỐI khởi động nếu API_KEYS rỗng (fail-closed); mỗi công ty cô lập dữ liệu theo `org_id`.
  Khi đó UI `/app` `/lookup` phải dán API key vào ô X-API-Key (đã có sẵn trong form).

**Cờ chất lượng tra cứu (đều có default hợp lý — chỉ chỉnh nếu cần):**
- `IN_FORCE_FILTER=true` (mặc định) — chỉ trả văn bản còn hiệu lực. Nên giữ true.
- `LEGAL_BASIS_GROUNDING=true` (mặc định) — gắn căn cứ điều luật cho risk/fallback.
- `CROSS_ENCODER_RERANK=true` + `QWEN_RERANK_MODEL=qwen3-rerank` — rerank qua Qwen-Rerank (cần key có quyền
  model này trong Model Studio; lỗi → tự tắt, chạy tiếp bằng BM25+embedding).
- `CITATION_CLOSURE=false` (mặc định) — bật `=true` để tự kéo điều luật dẫn chiếu.

## 6. Chạy
```bash
docker compose -f docker-compose.prod.yml up -d --build
```
Lệnh này: build image (gồm antiword cho file .doc) → app tự `alembic upgrade head` (áp mọi migration còn thiếu lên Neon, đã áp rồi thì no-op) → Caddy tự xin cert TLS cho DOMAIN.

## 7. Kiểm tra
```bash
docker compose -f docker-compose.prod.yml ps        # app + caddy đều "Up"
docker compose -f docker-compose.prod.yml logs -f caddy   # thấy "certificate obtained"
curl https://<DOMAIN>/health                        # {"status":"ok",...}
curl https://<DOMAIN>/changes/123/2020/NĐ-CP        # changelog VB (KB tải được chưa)
```
Mở trình duyệt: `https://<DOMAIN>/app` → UI demo (rà soát HĐ + nút 📝 soạn điều khoản phản-đề),
`https://<DOMAIN>/lookup` → tra cứu luật + "VB mới ảnh hưởng HĐ nào?". Ổ khóa HTTPS xanh.

## 8. Nối Slack (thay ngrok bằng domain thật)
Slack app → **Event Subscriptions** → Request URL:
```
https://<DOMAIN>/channels/slack/events
```
→ hiện **Verified** → Save. (Scope/event đã cấu hình trước đó không đổi.)

## 9. Cho bài nộp Qwen
- [ ] **Proof deploy trên Alibaba Cloud**: quay màn hình `https://<DOMAIN>/app` chạy + console ECS.
- [ ] **File code dùng Alibaba service**: chỉ tới `legalguard/adapters/outbound/qwen.py` (gọi DashScope/Qwen Cloud) + `config/container.py`.
- [ ] LICENSE đã có trong repo (hiển thị ở GitHub About).

## Vận hành nhanh
```bash
docker compose -f docker-compose.prod.yml logs -f app     # log app
docker compose -f docker-compose.prod.yml restart app     # restart sau khi đổi .env
docker compose -f docker-compose.prod.yml down            # dừng
git pull && docker compose -f docker-compose.prod.yml up -d --build   # cập nhật code
```

## Sự cố thường gặp
| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| Caddy không lấy được cert | DNS chưa trỏ đúng / port 80 chưa mở | `dig +short <DOMAIN>`; kiểm tra Security Group |
| `502 Bad Gateway` | app chưa sẵn sàng (đang migrate) | đợi ~30s; xem `logs app` |
| app crash khi khởi động | `.env` sai (DATABASE_URL scheme, REDIS_URL) | xem `logs app`; sửa `.env` → restart |
| Slack không verify | domain chưa HTTPS / app chưa chạy | `curl https://<DOMAIN>/health` phải 200 |
