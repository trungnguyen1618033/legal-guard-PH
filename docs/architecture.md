# Kiến trúc — Legal Guard PH

Chuẩn áp dụng: **Hexagonal Architecture (Ports & Adapters)** của Alistair Cockburn.
Mục tiêu: tách **nghiệp vụ (domain)** khỏi **hạ tầng (FastAPI, Qwen, file KB)**
để dễ test, dễ thay provider, và mở rộng đa quốc gia mà không sửa lõi.

---

## 1. Nguyên tắc cốt lõi: Dependency Rule

> Mọi phụ thuộc hướng **vào trong**. Domain không bao giờ import adapter/framework.

```
            ┌──────────────────── Inbound (driving) ────────────────────┐
            │   adapters/inbound/http.py  (FastAPI)                      │
            └───────────────────────────┬───────────────────────────────┘
                                         │ gọi
                                         ▼
        ╔════════════════════════ DOMAIN (hexagon) ════════════════════════╗
        ║  analysis.py (use-case AnalysisService)                          ║
        ║  agent.py (ReAct loop) · tools.py · tenants.py · models.py        ║
        ║                                                                  ║
        ║  ports.py — interface domain ĐỊNH NGHĨA:                          ║
        ║    LLMPort · KnowledgeBasePort · KnowledgeBaseProvider ·          ║
        ║    DocumentParserPort · LLMError                                  ║
        ╚═══════════════▲══════════════════════════════▲═══════════════════╝
                        │ implement                     │ implement
        ┌───────────────┴───────────────┐  ┌────────────┴──────────────────┐
        │ adapters/outbound/qwen.py      │  │ adapters/outbound/             │
        │  (LLMPort)                     │  │   knowledge_base.py            │
        │                                │  │   document_parser.py           │
        └────────────────────────────────┘  └───────────────────────────────┘

        Composition root: config/container.py  — nơi DUY NHẤT ráp adapter vào domain.
```

Domain chỉ biết **port** (interface). Adapter ở ngoài *implement* port. Việc chọn
adapter nào xảy ra duy nhất ở `config/container.py` (composition root).

---

## 2. Cấu trúc thư mục

```
app.py                              ASGI entrypoint → build_app()
legalguard/
  domain/                           ← BÊN TRONG hexagon (không phụ thuộc hạ tầng)
    models.py                       DTO: Risk, Fallback, ChatTurn, ToolCall, Snippet,
                                    AgentContext, AgentRun, AnalysisResult
    ports.py                        LLMPort, KnowledgeBasePort, KnowledgeBaseProvider,
                                    DocumentParserPort, LLMError
    agent.py                        ReAct loop (phụ thuộc LLMPort)
    tools.py                        tool schemas + execute_tool (grounding: flag_risk kèm source)
    verification.py                 LLM-as-judge: kiểm rủi ro có được KB hậu thuẫn (chống hallucination)
    analysis.py                     AnalysisService (use-case rà soát)
    evidence.py                     EvidenceService (use-case doanh thu/evidence vận hành)
    reporting.py                    render báo cáo concierge (Markdown, thuần)
    tenants.py                      2 trục: Tenant (quốc gia → KB luật) · Organization (công ty → cô lập + overlay)
  adapters/
    inbound/http.py                 driving adapter: FastAPI (HTTP ↔ domain) + landing
    inbound/channels.py             driving adapter: webhook Zalo OA / Slack (verify chữ ký → analyze)
    inbound/mcp_server.py           driving adapter: MCP server (tool analyze_contract cho Qwen-Agent/Claude)
    outbound/observability.py       ObservabilityPort: NoOp · Langfuse (traces/evals — evidence AI-Native)
    outbound/qwen.py                LLMPort: Qwen Cloud (chat/complete/embed) — reasoner · judge · lookup
    outbound/knowledge_base.py      KnowledgeBasePort: keyword · embedding · Hybrid(RRF) · Rerank(LLM) · FullContext(CAG)
    outbound/document_parser.py     DocumentParserPort: PDF/DOCX/TXT
    outbound/revenue_log.py         RevenueLogPort: CSV (evidence doanh thu)
    outbound/sql_case_repository.py CaseRepositoryPort: SQLAlchemy (SQLite local / Postgres prod)
  config/
    settings.py                     đọc .env (pydantic-settings)
    container.py                    composition root (wiring)
knowledge_base/VN/                  dữ liệu KB theo tenant
tests/                              test theo port (inject stub/fake, không gọi mạng)
```

---

## 3. Ports & Adapters

| Port (domain định nghĩa) | Adapter (hạ tầng implement) | Vai trò |
|---|---|---|
| `LLMPort` | `QwenAdapter`, (fake trong test) | Gọi LLM (chat/complete/embed) |
| `KnowledgeBasePort` | `KeywordRetriever`, `EmbeddingRetriever` | Truy xuất KB |
| `KnowledgeBaseProvider` | `FileKnowledgeBaseProvider` | Tạo retriever theo tenant |
| `DocumentParserPort` | `PdfDocxParser` | Bóc tách file hợp đồng |
| `RevenueLogPort` | `CsvRevenueLog` | Lưu/đọc doanh thu (evidence) |
| `CaseRepositoryPort` | `SqlAlchemyCaseRepository` (SQLite/Postgres) | Lưu/đọc cases (persistence + audit) |
| (inbound) | `http.py` (FastAPI) | Cổng vào driving |

**Đổi provider = viết adapter mới + sửa 1 dòng ở `container.py`.** Domain không đổi.

---

## 4. Lõi nghiệp vụ: Agentic ReAct loop

`agent.run_agent` là vòng lặp Reason → Act → Observe:
1. LLM (`LLMPort`) tự quyết định gọi tool nào.
2. Tools: `search_legal_knowledge` (RAG) · `flag_risk` · `propose_fallback` · `request_human_review`.
3. Kết quả ghi vào `AgentContext` dưới dạng **structured output** (qua schema tool-call).
4. Mỗi bước ghi `TraceStep` → execution trace (debug + evidence AI-Native).
5. Rủi ro `high` → tự gắn cờ **human-in-the-loop** (yêu cầu track Autopilot Agent).

`AnalysisService` (use-case) điều phối: tạo retriever theo tenant → `run_agent` →
**(verification ∥ tóm tắt (qwen-flash) ∥ gắn căn cứ pháp lý) chạy SONG SONG** → lưu case → trả `AnalysisResult`.
Lỗi provider → `LLMError` đã làm sạch → degrade, không crash.

**Model right-sizing (latency):** việc KHÓ (agent phân tích, sinh chiến lược) dùng flagship `qwen3.7-max`;
việc PHỤ yes/no (NLI entailment, verify gộp) dùng `judge` = `qwen-flash` (`QWEN_FAST_MODEL`) — đo thực:
NLI flagship ~23s/call vs flash ~0.5s, KHỚP verdict trên test pháp lý → khâu hậu-agent 264s→7s mà không
bỏ bước kiểm nào; agent vẫn dùng flagship nên chất lượng phân tích giữ nguyên.

### Kỹ thuật chất lượng AI/RAG
- **Agentic RAG:** agent tự quyết định khi nào/tra gì (không pipeline cứng).
- **Grounding + citation:** mỗi rủi ro gắn `source` (quote KB) + `evidence` (trích nguyên văn hợp đồng) — `tools.py`.
- **Verification 2 lớp:** (1) clause-existence offline — `evidence` phải có thật trong hợp đồng (HalluGraph-lite, chống bịa điều khoản); (2) LLM-as-judge khi có key — `verification.py`.
- **Adaptive routing + chunking:** hợp đồng ngắn → đường rẻ (ít vòng); dài → chia cửa sổ (không bỏ sót điều khoản cuối) — `analysis.py`.
- **Hybrid retrieval (RRF):** fuse keyword + embedding; **reranker** LLM opt-in (`RERANK_ENABLED`).
- **Đảm bảo chất lượng LLM:** (1) structured output qua tool schema + **validate/ép args** (bỏ output rác,
  ép enum severity) — `tools.py`; (2) **grounding bắt buộc** (evidence ∈ hợp đồng) + verification GỘP
  (LLM-judge); (3) **temperature thấp** (`LLM_TEMPERATURE=0.1`) cho nhất quán; (4) **retry/backoff**
  + parse-guard JSON; (5) **eval harness** đo groundedness/precision như cổng chất lượng.
- **Eval harness + A/B retrieval:** `evaluation/` đo precision/recall + groundedness; `compare()`
  so sánh `keyword` / `hybrid` / `full` (CAG) để **chọn cơ chế bằng số liệu** thay vì theo trend
  ("RAG lỗi thời?" → đo, đừng đoán). Cơ chế nằm sau `KnowledgeBasePort` nên đổi không đụng domain.

---

## 5. Vì sao Hexagonal hợp dự án này

- **Testability:** test inject fake `LLMPort`/retriever → chạy offline, không tốn quota
  (xem `tests/`). Đây là lý do toàn bộ test chạy được mà không gọi LLM thật.
- **Right-sizing LLM:** Qwen flagship `qwen3.7-max` (reasoner — việc khó) + `qwen-flash` (judge:
  NLI/verify + tóm tắt) + `qwen-plus` (lookup) chỉ là cách dùng cùng `LLMPort` với model khác nhau —
  cắt latency mà không phân nhánh trong domain (domain chỉ thấy `reasoner`/`judge`/`lookup_llm`).
  Thêm provider thứ 2 (nếu cần) = 1 adapter + 1 dòng container, domain không đổi.
- **Multi-tenant đa quốc gia:** thêm nước = thêm dữ liệu KB + entry tenant, không sửa lõi.
- **Đường nâng cấp sạch:** thay `FileKnowledgeBaseProvider` bằng vector DB, hay thêm
  Postgres/queue (§5b của `docs/internal/legal-guard.md`) chỉ là thêm/đổi adapter ở composition root.

---

## 6. Giai đoạn sau (production) — vẫn trong khuôn Hexagonal

| Nhu cầu | Cách thêm (không đụng domain) |
|---|---|
| Vector DB thật | Adapter mới cho `KnowledgeBaseProvider` (pgvector/Milvus) |
| Postgres cho cases | Đổi `DATABASE_URL` sang `postgresql+psycopg://...` (cùng adapter SQLAlchemy). Xem `data-model.md` |
| Async parse/embedding | Adapter inbound dạng worker/queue + `DocumentParserPort` async |
| Cache | Decorator adapter quanh `LLMPort`/`KnowledgeBasePort` |
| Observability | Decorator/middleware quanh adapter, ghi trace + API usage |

Tất cả là **thêm adapter / port mới**, lõi nghiệp vụ giữ nguyên — đúng tinh thần Ports & Adapters.
