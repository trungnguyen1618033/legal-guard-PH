# Legal Guard PH

AI "phòng pháp chế thuê ngoài" cho SME Việt Nam: phân tích hợp đồng thương mại quốc tế,
cảnh báo điều khoản rủi ro, và đề xuất chiến thuật thỏa hiệp (fallback) theo luật thương mại VN.

> Track **Autopilot Agent** (Qwen Cloud Hackathon) · Category **Professional Services** (Gemini XPRIZE).
> 📚 **Toàn bộ tài liệu:** [`docs/README.md`](docs/README.md) (chiến lược · kỹ thuật · thị trường · bảo mật).

## Kiến trúc — Hexagonal (Ports & Adapters)

```
app.py                         ASGI entrypoint → build_app()
legalguard/
  domain/                      lõi nghiệp vụ (không phụ thuộc hạ tầng)
    models · ports · agent (ReAct loop) · tools · analysis (use-case) · tenants
  adapters/
    inbound/http.py            FastAPI (driving adapter)
    outbound/                  qwen · gemini · knowledge_base · document_parser · revenue_log · case_repository
  config/                      settings · container (composition root)
knowledge_base/VN/             ma trận fallback (12 nhóm điều khoản) — xem knowledge_base/_README.md
```

**Song ngữ:** output `lang=en` (mặc định) / `vi`; câu gửi đối tác luôn tiếng Anh. KB là nguồn
tiếng Việt (ngôn ngữ KB ≠ ngôn ngữ output). Thiết kế & độ phủ KB: [`knowledge_base/_README.md`](knowledge_base/_README.md).

**Domain định nghĩa port, adapter implement, `config/container.py` ráp lại.**
Lõi là **agentic ReAct loop**: LLM tự quyết định gọi tool — `search_legal_knowledge` (RAG) ·
`flag_risk` · `propose_fallback` · `request_human_review` — lặp tới khi ra kết luận, ghi `trace`.

Kỹ thuật chất lượng: **grounding + citation** (mỗi rủi ro gắn `source` KB) · **verification pass**
(LLM-as-judge chống hallucination) · **hybrid retrieval RRF** (keyword + embedding) + **reranker**
LLM opt-in (`RERANK_ENABLED=true`) · **eval harness + A/B retrieval** (`uv run python -m evaluation.run_eval`
so sánh keyword / hybrid / full-context). Lỗi provider → `LLMError` đã làm sạch → degrade, không crash.

👉 Chi tiết: [`docs/architecture.md`](docs/architecture.md) · lộ trình scale: `docs/internal/legal-guard.md` §5b.

## Chạy bằng Docker (Postgres + app)

```bash
make up            # build + chạy app (http://localhost:8000) + postgres + tự migrate
make logs          # xem log
make psql          # mở psql
make down          # dừng (giữ data) · make clean (xóa luôn volume DB)
make help          # tất cả lệnh
```

`docker-compose.yml`: `db` (postgres:16) + `redis` (7) + `app` (FastAPI, healthcheck `/ready`).
App tự đặt `DATABASE_URL` (postgres), `CONVERSATION_BACKEND=redis` + `REDIS_URL` (chat session trên
Redis), và chạy `alembic upgrade head` trước khi serve. API key đọc từ `.env` (`make env`).
Lệnh: `make psql` · `make redis-cli` · `make logs`.

## Chạy local không Docker (dùng [uv](https://docs.astral.sh/uv/))

```bash
uv sync                       # tạo .venv + cài deps theo pyproject.toml / uv.lock
cp .env.example .env          # điền QWEN_API_KEY (và GEMINI_API_KEY)
uv run uvicorn app:app --reload
# → http://localhost:8000/docs
```

Không có API key vẫn chạy được ở **chế độ stub** (trả response có nhãn `[..._STUB]`) để
dựng/demo luồng. Cấu hình key thật để có phân tích thật.

### Lệnh thường dùng
```bash
uv run uvicorn app:app --reload   # chạy server
uv run ruff check .               # lint
uv run pytest                     # test
uv add <package>                  # thêm thư viện (cập nhật pyproject + lock)
```

## Endpoints

| Method | Path | Mục đích |
|---|---|---|
| GET | `/` | Landing one-pager (`web/index.html`) |
| GET | `/app` | **UI demo** (`web/app.html`): upload → risk → fallback → **human checkpoint** Approve/Reject |
| GET | `/health` · `/ready` | Liveness · readiness (DB) — cho LB/k8s |
| POST | `/analyze` | Rà soát HĐ. `format=json`/`report` · `lang=en`/`vi` · **vị thế đàm phán** `leverage`/`urgency`/`relationship`/`alternatives` → priority + chiến lược |
| POST | `/evidence/revenue` | Ghi nhận doanh thu (evidence XPRIZE) |
| GET | `/evidence/summary` | Tổng doanh thu + breakdown tháng 5–8/2026, tách related-party |
| GET | `/cases?tenant=VN` | Lịch sử rà soát (mới nhất trước) |
| GET | `/cases/{id}` | Chi tiết 1 case đã lưu |
| DELETE | `/cases/{id}` | Xóa case (right-to-erasure PDPD/GDPR) |
| POST | `/cases/{id}/outcome` | Ghi kết quả đàm phán (flywheel dữ liệu — moat) |
| GET | `/insights/tactics` | Win-rate theo điều khoản từ kết quả thực tế |
| POST | `/channels/slack/events` | Webhook Slack (verify chữ ký + challenge) — bật khi có `SLACK_SIGNING_SECRET` |
| POST | `/channels/zalo/webhook` | Webhook Zalo OA (verify `X-ZEvent-Signature`) — bật khi có `ZALO_OA_SECRET` |

**MCP server:** `make mcp` (hoặc `uv run python -m legalguard.adapters.inbound.mcp_server`) expose tool
`analyze_contract` cho **Qwen-Agent / Claude / IDE** qua Model Context Protocol (chuẩn agent-tool 2026).

**Observability:** đặt `LANGFUSE_*` để gửi traces/evals (evidence AI-Native cho XPRIZE); rỗng = NoOp.

**Kênh nhắn tin (khép kín):** SME chat qua **Zalo/Slack** → bot verify chữ ký → (ack nhanh, xử lý nền)
tải file → rà soát → **gửi reply về chat** (rủi ro + ưu tiên + chiến lược, tiếng Việt). Cần secret + token
(`SLACK_BOT_TOKEN`/`ZALO_ACCESS_TOKEN`); thiếu token thì trả reply trong response (fallback). Hexagonal:
inbound (`channels.py`) + outbound sender (`chat_senders.py`), domain không đổi.

**Multi-tenancy 2 trục:** Quốc gia (jurisdiction → KB luật) × Công ty (Organization → cô lập dữ liệu
+ KB overlay riêng `knowledge_base/_orgs/<org_id>/`). Cô lập **theo công ty**, không theo quốc gia.

**Bảo mật:** đặt `API_KEYS="key:org_id:VN,..."` để bật xác thực (header `X-API-Key`) — mọi truy vấn
`cases` bị ràng theo `org_id` của key → công ty A không đọc được dữ liệu công ty B. PII (email/điện thoại/
số dài) được **redact trước khi gửi LLM/lưu/log**; hợp đồng được bọc như **dữ liệu không tin cậy**
(chống prompt injection); upload giới hạn `MAX_UPLOAD_BYTES`. Thiết kế đầy đủ: [`docs/security.md`](docs/security.md).

**Upload file:** `/analyze` field `file` nhận **PDF/DOCX/TXT (text)** + **PDF scan/ảnh (.png/.jpg) → OCR
bằng Qwen-VL** (tự kích hoạt khi không bóc được text; cần `QWEN_API_KEY`). Giới hạn `MAX_UPLOAD_BYTES`.

`/analyze` tự lưu mỗi lần rà soát vào DB và trả `case_id`. Persistence dùng **SQLAlchemy** —
cùng code chạy **SQLite** (mặc định, `DATABASE_URL=sqlite:///data/cases.db`) và **PostgreSQL**
(prod, đổi `DATABASE_URL`). Migrations bằng **Alembic** (`uv run alembic upgrade head`).
Thiết kế DB + lộ trình Postgres/pgvector: [`docs/data-model.md`](docs/data-model.md).

**Luồng concierge:** nhận HĐ khách → `POST /analyze?format=report` → giao báo cáo Markdown →
thu phí → `POST /evidence/revenue`. Sổ doanh thu lưu ở `data/revenue.csv` (đã gitignore).

## Yêu cầu
- Python ≥ 3.11
- Qwen API (LLM phân tích chính) · Gemini API (≥1 call, ràng buộc XPRIZE)
