# Data model & Persistence

Persistence đi qua **`CaseRepositoryPort`** (domain định nghĩa). Adapter:
**`SqlAlchemyCaseRepository`** (SQLAlchemy 2.0) — **cùng code chạy SQLite và PostgreSQL**,
chỉ đổi `DATABASE_URL`. Domain không đổi (Ports & Adapters).

```
DATABASE_URL=sqlite:///data/cases.db                                  # local/dev/test (mặc định)
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/legalguard      # prod (ApsaraDB RDS + pgvector)
```

> `data/` đã gitignore (chứa dữ liệu khách). `__init__` gọi `create_all()` để dev/test có bảng ngay;
> prod dùng **Alembic** (`migrations/`) làm nguồn schema chính thức.

## Migrations (Alembic)

```bash
uv run alembic upgrade head            # áp schema mới nhất (prod)
uv run alembic revision -m "msg"       # tạo migration mới
uv run alembic current                 # xem revision hiện tại
```
URL lấy động từ `settings.database_url` trong `migrations/env.py`. Migration khởi tạo: `0001_initial`.

## Bảng `cases` (đang dùng)

Mỗi lần `/analyze` lưu 1 case — vừa là **lịch sử cho khách**, vừa là **AI execution evidence**
cho XPRIZE (AI-Native Operations).

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | TEXT (uuid) | khóa chính |
| `org_id` | TEXT | **CÔNG TY sở hữu** — cô lập dữ liệu theo trường này (index) |
| `tenant` | TEXT | quốc gia/jurisdiction (VN/ID/TH...) |
| `created_at` | TEXT | ISO UTC |
| `lang` | TEXT | `en` / `vi` |
| `contract_excerpt` | TEXT | **chỉ 280 ký tự đầu** — KHÔNG lưu toàn bộ nội dung nhạy cảm |
| `summary` | TEXT | tóm tắt |
| `needs_human_review` | INTEGER | 0/1 |
| `risks` · `fallbacks` · `trace` | TEXT (JSON) | mỗi risk có `source` (citation KB), `evidence` (quote hợp đồng), `verified` |

**Quyết định riêng tư:** không lưu toàn văn hợp đồng (chỉ excerpt) — phù hợp lưu ý bảo mật dữ liệu
khách thật (`internal/legal-guard.md` §5b.4).

## Bảng `outcomes` (flywheel — moat)

Kết quả đàm phán thực tế = **dữ liệu độc quyền** (xem [moat.md](moat.md)). Adapter:
`SqlAlchemyOutcomeRepository`; migration `0003`.

| Cột | Ghi chú |
|---|---|
| `id` · `org_id` · `case_id` | khóa + cô lập theo công ty |
| `clause` | điều khoản (index) |
| `tactic` · `result` | chiến thuật dùng · `accepted/partial/rejected/pending` |
| `created_at` | ISO |

`win_rates()` (accepted=1, partial=0.5, rejected=0; bỏ pending) → outcome-aware ranking gắn
`win_rate` vào fallback. API: `POST /cases/{id}/outcome`, `GET /insights/tactics`.

## Lộ trình mở rộng (vẫn trong khuôn Hexagonal)

| Bảng/Adapter | Khi nào | Cách thêm |
|---|---|---|
| Postgres prod | khi deploy Alibaba Cloud | đổi `DATABASE_URL` → `postgresql+psycopg://...` (ApsaraDB RDS); không sửa code |
| `pgvector` cho KB | thay keyword/embedding bằng vector thật | bảng `kb_chunks(embedding vector)` + adapter `KnowledgeBaseProvider` |
| `customers` | khi onboard khách trả phí | `CustomerRepositoryPort` + adapter |
| `revenue` (thay CSV) | khi cần truy vấn evidence phức tạp | đổi `RevenueLogPort` adapter từ CSV → SQL |
| audit/`api_usage` | evidence AI-Native chi tiết | bảng phụ + decorator quanh `LLMPort` |

## Endpoints liên quan

| Method | Path | |
|---|---|---|
| GET | `/cases?tenant=VN&limit=20` | Lịch sử rà soát theo tenant (mới nhất trước) |
| GET | `/cases/{id}` | Chi tiết 1 case (404 nếu không có) |

`POST /analyze` tự lưu case và trả `case_id` trong kết quả. Lỗi DB **không** làm hỏng phân tích
(persistence là phụ — chỉ thêm note).
