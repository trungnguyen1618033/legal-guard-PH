# Triển khai & Scale — Legal Guard PH

Thiết kế đưa hệ thống lên production và scale. Cloud mục tiêu: **Alibaba Cloud** (bắt buộc cho
Qwen hackathon, cũng là nơi Qwen/DashScope chạy gần). Nguyên tắc: **12-factor + stateless app +
managed services + scale từng tầng độc lập**; mọi thay đổi scale chỉ là **đổi adapter** (hexagonal).

## 1. Topology production (Alibaba Cloud)

```
                 Internet
                    │  TLS
            ┌───────▼────────┐
            │  SLB / ALB     │  (load balancer + TLS termination)
            └───────┬────────┘
        ┌───────────┼───────────┐         stateless → autoscale
   ┌────▼───┐  ┌────▼───┐  ┌────▼───┐
   │ app #1 │  │ app #2 │  │ app #N │  (FastAPI container, ACK/SAE/ECS)
   └────┬───┘  └────┬───┘  └────┬───┘
        └─────┬─────┴─────┬─────┘
        ┌─────▼─────┐ ┌───▼──────────┐ ┌──────────────┐
        │ RDS       │ │ Redis        │ │ Async workers│  (parse/embed/batch)
        │ PostgreSQL│ │ cache+queue  │ │  từ queue    │
        │ +pgvector │ │ +rate-limit  │ └──────┬───────┘
        └───────────┘ └──────────────┘        │
        ┌──────────┐  ┌──────────────┐  ┌──────▼───────┐
        │ OSS files│  │ KMS secrets  │  │ DashScope    │ (Qwen, Singapore)
        └──────────┘  └──────────────┘  │ + Gemini     │
                                        └──────────────┘
   Observability: SLS (logs) · metrics · tracing
```

| Thành phần | Dịch vụ Alibaba | Vai trò |
|---|---|---|
| App tier | ACK (k8s) / SAE / ECS + container | FastAPI stateless, autoscale |
| Load balancer | SLB/ALB | TLS, phân tải, health check |
| DB | **ApsaraDB RDS PostgreSQL + pgvector** | cases/outcomes + vector RAG; mã hóa at-rest, backup, read replica |
| Cache/Queue/Rate-limit | **ApsaraDB Redis** | cache phân tích/retrieval/insights · job queue · rate-limit chia sẻ |
| File | **OSS** (nếu lưu file) | mã hóa + lifecycle (erasure) + signed URL |
| Secrets | **KMS / Secrets Manager** | thay `.env` |
| Registry | **ACR** | image từ CI |
| LLM | DashScope (Qwen) + Gemini | tự scale phía provider |
| Observability | **SLS** + metrics | log/metric/trace |

## 2. Scale từng tầng (và hexagonal giúp thế nào)

| Tầng | Cách scale | Đổi gì trong code |
|---|---|---|
| **App** | Stateless → tăng số replica + autoscale theo CPU/RPS | Không (đã stateless) |
| **Rate-limit** | ⚠️ hiện in-process → **chuyển Redis** để đúng khi nhiều instance | Adapter `RateLimiterPort` → Redis |
| **RAG** | ⚠️ hiện embed in-memory mỗi instance → **pgvector** (persist + ANN HNSW) | Adapter `KnowledgeBaseProvider` → pgvector |
| **Tác vụ nặng** (parse/embed) | Async qua **queue + worker** riêng | Thêm `QueuePort` + worker; API chỉ enqueue |
| **DB** | Connection pool (SQLAlchemy) + **read replica** cho đọc (cases/insights) | `DATABASE_URL` → RDS; replica URL cho read |
| **Cache** | Redis cache kết quả lặp + win-rates | Decorator quanh `LLMPort`/`KnowledgeBasePort` |
| **Chi phí token** | Adaptive routing (đã có) + cache + rate-limit (đã có) | — |

→ Tất cả là **thêm/đổi adapter ở composition root**, domain không đổi.

## 3. Bottlenecks hiện tại cần xử lý trước khi scale ngang

1. **Rate limiter in-process** (`http.py`) → nhiều instance đếm riêng → **chuyển Redis**.
2. **EmbeddingRetriever embed mỗi lần khởi động, in-memory** → tốn + không nhất quán → **pgvector**.
3. **LLM call đồng bộ** → tác vụ nặng nên đẩy **async/queue**; API tăng uvicorn workers.
4. **SQLite mặc định** → prod **bắt buộc Postgres** (chỉ đổi `DATABASE_URL`).

## 4. Tiers (theo quy mô)

| Tier | Hạ tầng | Phù hợp |
|---|---|---|
| **MVP / pilot** | 1 container + 1 RDS Postgres, sync | demo Qwen + vài khách đầu |
| **Growth** | LB + N app + RDS + Redis (cache/rate-limit) + pgvector + async worker | có khách trả phí |
| **Scale** | Autoscale (ACK/SAE) + read replica + multi-AZ + SLS + partition theo org | nhiều công ty |

## 5. CI/CD & rollout

```
push → CI (ruff + pytest) → build image → push ACR
     → deploy rolling (ACK/SAE) → init job: alembic upgrade head
     → readiness probe /ready (check DB) → LB chuyển traffic
```
- **Liveness** `GET /health` (process sống) · **Readiness** `GET /ready` (DB sẵn sàng) → LB/k8s dùng.
- Migration chạy 1 lần mỗi deploy (init container/job), KHÔNG để app tự `create_all` ở prod.
- 12-factor: config qua env (đã có), log ra stdout (SLS thu), không state cục bộ.

## 6. Bảo mật khi scale (xem [security.md](security.md))
RDS mã hóa at-rest (TDE) · TLS toàn tuyến · KMS secrets · Postgres RLS theo `org_id` ·
OSS lifecycle cho erasure · rate-limit Redis · WAF trước SLB.

## 7. DR & vận hành
Backup tự động RDS + point-in-time · multi-AZ · alerting (SLS) · retention/purge case theo chính sách.
