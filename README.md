# Legal Guard PH

AI "phòng pháp chế thuê ngoài" cho SME Việt Nam: phân tích hợp đồng thương mại quốc tế,
cảnh báo điều khoản rủi ro, và đề xuất chiến thuật thỏa hiệp (fallback) theo luật thương mại VN.

> Track **Autopilot Agent** (Qwen Cloud Hackathon) · Category **Professional Services** (Gemini XPRIZE).
> 📚 **Toàn bộ tài liệu:** [`docs/README.md`](docs/README.md) (chiến lược · kỹ thuật · thị trường · bảo mật).

## 🚀 Quick demo (cho giám khảo)

```bash
uv sync && uv run uvicorn app:app          # đặt QWEN_API_KEY trong .env để phân tích THẬT
```
Mở **http://localhost:8000/app** → bấm **"📄 Dùng hợp đồng mẫu"** → **"🔍 Phân tích hợp đồng"**.
Agent (xem tab **Trace**) tự: tra KB luật → gắn cờ rủi ro → đối chiếu NLI → soạn fallback theo vị thế.
Kết quả khoe 3 điểm khác biệt:
- ⚖️ **Điều 2 phạt 15% → TRÁI LUẬT** (có thể VÔ HIỆU theo Điều 301 Luật TM 2005) — tách khỏi điều chỉ *bất lợi*.
- ♟️ **Chiến lược đàm phán theo vị thế "Bên Mua yếu"** (giữ / nhượng / walk-away) — không phải mẫu cứng.
- 🧑‍⚖️ **Human checkpoint**: câu gửi đối tác bị khóa tới khi chuyên gia duyệt.

Không có key Qwen → vẫn chạy offline ở **chế độ stub** (kết quả mô phỏng, đủ để xem luồng).
Trang khác: **`/lookup`** (tra cứu luật + 🗺️ lược đồ văn bản kiểu TVPL) · **`/dashboard`** · **`/docs`** (API).

## Kiến trúc — Hexagonal (Ports & Adapters)

```
app.py                         ASGI entrypoint → build_app()
legalguard/
  domain/                      lõi nghiệp vụ (không phụ thuộc hạ tầng)
    models · ports · agent (ReAct loop) · tools · analysis (use-case) · tenants
    verification (NLI) · negotiation (đa phiên) · counter_clause · regulatory · redline · dashboard
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

Kỹ thuật chất lượng: **grounding + citation** (mỗi rủi ro gắn `source` + căn cứ điều luật tất định) ·
**verification 2 tầng** (LLM-judge + **NLI entailment** chống citation "tồn tại nhưng không hỗ trợ") ·
**hybrid retrieval RRF** (BM25 + embedding) + reranker opt-in · **lọc hiệu lực** (chỉ trả VB còn hiệu lực,
point-in-time) + **citation closure** (đi theo dẫn chiếu chéo) · **reason-then-format** (model suy luận trước
khi điền structured output) · **eval harness + A/B** (`evaluation/`). Lỗi provider → `LLMError` → degrade, không crash.

**Khác biệt (moat):** không chỉ soi HĐ mà đàm phán **theo vị thế thật** (leverage/urgency/BATNA → priority
+ chiến lược + **điều khoản phản-đề song ngữ** `/counter`) · **regulatory change intel** (`/impact`: VB mới
ảnh hưởng HĐ nào, article-level, cảnh báo Slack/Zalo) · **system-of-record** (`/dashboard`) · **living flywheel**
(feedback → golden set). Phân tích sâu: `docs/internal/moat-and-differentiation.md`.

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
| GET | `/app` | **UI demo** (`web/app.html`): upload → risk → fallback → **human checkpoint** + nút "📝 soạn điều khoản phản-đề" |
| GET | `/lookup` | **UI tra cứu luật** (`web/lookup.html`): hỏi đáp pháp lý + "VB mới ảnh hưởng HĐ nào?" + changelog + redline |
| GET | `/dashboard` | **UI bảng điều khiển** (`web/dashboard.html`): system-of-record tổng hợp công ty |
| GET | `/health` · `/ready` | Liveness · readiness (DB) — cho LB/k8s |
| POST | `/analyze` | Rà soát HĐ. `format=json`/`report` · `lang=en`/`vi` · **vị thế đàm phán** `leverage`/`urgency`/`relationship`/`alternatives` → priority + chiến lược |
| POST | `/ask` | Tra cứu luật (RAG có grounding) → câu trả lời dẫn Điều/Khoản **còn hiệu lực** + nguồn |
| POST | `/counter` | Soạn **điều khoản phản-đề song ngữ VN/EN** cho 1 điều khoản rủi ro (bám căn cứ + vị thế) |
| POST | `/negotiate` | **Đàm phán đa phiên**: bối cảnh deal + tin đối tác → đánh giá + chiến lược vòng tới + reply + status |
| GET | `/changes/{doc_id}` | "What changed" cấp văn bản: VB này sửa đổi/thay thế/của VB nào |
| GET | `/graph/{doc_id}` | **Lược đồ văn bản** (nodes+edges, đa-hop) — quan hệ + hiệu lực kiểu TVPL |
| GET | `/latest/{doc_id}` | Map tới **văn bản mới nhất** (theo chuỗi replaced_by) |
| GET | `/articles-changed/{doc_id}` | Điều nào của VB đã bị VB khác sửa (**bôi vàng** kiểu TVPL) |
| POST | `/redline` | Diff 2 phiên bản text (`[+thêm+]`/`[-bỏ-]` + similarity, tất định) |
| GET | `/impact/{doc_id}` | **Regulatory change intel**: VB mới ảnh hưởng case nào của công ty (article-level) |
| POST | `/impact/{doc_id}/notify` | Gửi cảnh báo VB mới ảnh hưởng HĐ qua Slack/Zalo (`via`/`channel`) |
| POST | `/monitor/run` | **Autopilot**: tự quét VB luật MỚI (`since`) → HĐ bị ảnh hưởng → digest Slack/Zalo (cron) |
| POST · GET | `/feedback` | Ghi · liệt kê phản hồi người dùng (vòng học → golden set) |
| POST | `/evidence/revenue` | Ghi nhận doanh thu (evidence XPRIZE) |
| GET | `/evidence/summary` | Tổng doanh thu + breakdown tháng 5–8/2026, tách related-party |
| GET | `/cases?tenant=VN` | Lịch sử rà soát (mới nhất trước) |
| GET | `/cases/{id}` | Chi tiết 1 case đã lưu |
| DELETE | `/cases/{id}` | Xóa case (right-to-erasure PDPD/GDPR) |
| POST | `/cases/{id}/outcome` | Ghi kết quả đàm phán (flywheel dữ liệu — moat) |
| GET | `/insights/tactics` | Win-rate theo điều khoản từ kết quả thực tế |
| GET | `/insights/dashboard` | System-of-record: HĐ rà soát, top điều khoản rủi ro, feedback, win-rate |
| POST | `/channels/slack/events` | Webhook Slack (verify chữ ký + challenge) — bật khi có `SLACK_SIGNING_SECRET` |
| POST | `/channels/slack/interactions` | Nút feedback Slack 👍/⚠️/➖ (verify chữ ký raw body) |
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
