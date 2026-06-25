# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

MVP scaffold exists and runs end-to-end. The Vietnamese planning docs are the source of truth for
scope/strategy (in `docs/internal/`, gitignored — not in the public repo):
`docs/internal/legal-guard.md` (plan + corrected hackathon facts + §5b production architecture),
`docs/internal/phan-tich-kha-thi.md` (feasibility + judge's-eye analysis),
`docs/internal/pitch-presell.md` (sales playbook).

## Commands (managed with `uv`)

```bash
uv sync                            # create .venv + install from pyproject.toml / uv.lock
uv run uvicorn app:app --reload    # run API (http://localhost:8000/docs)
uv run ruff check .                # lint
uv run pytest                      # full suite (offline; conftest blanks API keys → stub mode)
uv run pytest tests/test_agent.py::test_agent_produces_structured_risks_and_trace   # single test
uv run alembic upgrade head        # apply DB migrations (DATABASE_URL; sqlite default, postgres in prod)
uv run python -m evaluation.run_eval  # fast eval: precision/recall + groundedness on golden set (offline)
uv run python -m evaluation.legal_eval # eval TRA CỨU LUẬT: Recall@k/MRR + closure-recall + still-good-law (offline)
uv run python -m ingestion.hf_to_kb --pages 4 --keyword "hóa đơn" --out knowledge_base/_ingested # ETL: HF dataset luật VN → KB .md (front-matter status)
uv sync --group eval                  # cài lớp eval sâu (RAGAS) — opt-in, không cần cho runtime
uv run python -m evaluation.ragas_eval  # deep eval: RAGAS LLM-as-judge (cần QWEN_API_KEY; chậm/tốn call)
uv add <pkg>                       # add a dependency
```

AI/RAG quality techniques: grounding+citation+evidence (`tools.py`), verification 2-layer
(clause-existence + LLM-judge, `domain/verification.py`), lexical BM25 (Okapi, length-norm + IDF) +
embedding, hybrid retrieval RRF + opt-in LLM reranker
+ opt-in cross-encoder reranker (Qwen `gte-rerank`, `CROSS_ENCODER_RERANK`) + full-context
(`outbound/knowledge_base.py`, `RERANK_ENABLED`), structure-aware legal chunking + NFC + citation
extraction (`outbound/legal_chunker.py` — chunk theo Điều/Khoản, nhãn gắn vào `Snippet.source` dạng
`file.md#Điều 5`; Phase 0 hướng mở rộng tra cứu luật VN, xem `docs/internal/legal-search-expansion.md`),
citation closure document-aware đi theo dẫn chiếu kéo về điều luật liên quan ở ĐÚNG văn bản đích
(`CitationClosureRetriever`, `CITATION_CLOSURE`; `extract_article_refs` phân giải "Điều 9 của NĐ 123/2020"
→ đúng file qua map doc_id, "của Luật này"→cùng file; dựng cạnh bằng rule không LLM — Phase 2), lọc hiệu lực mặc-định-chỉ-trả-văn-bản-còn-hiệu-lực
(`InForceRetriever`, `IN_FORCE_FILTER`, theo front-matter `status` của file KB; ý định lịch sử mới hiện bản cũ),
căn cứ pháp lý tất định cho từng risk & fallback (`_legal_citation` trong `domain/analysis.py`,
`LEGAL_BASIS_GROUNDING`: tra KB gắn `Risk.legal_basis`/`Fallback.legal_basis` = điều luật còn hiệu lực,
ngưỡng trùng ≥3 thuật ngữ để tránh căn cứ lạc), adaptive routing + chunking (`domain/analysis.py`),
eval harness + A/B (`evaluation/`). Hai tầng eval: `run_eval.py` =
fast gate keyword-matching (offline, free, dùng trong CI); `ragas_eval.py` = deep gate RAGAS
LLM-as-judge (Faithfulness / Context Precision / Response Relevancy; + Context Recall + Factual
Correctness khi golden có `reference`), judge = Qwen qua endpoint OpenAI-compatible nên không cần
OpenAI key. Opt-in qua group `eval` (pin langchain <1.0 — RAGAS 0.4.3 cần `langchain_community.chat_models.vertexai`).

Advisory flow (`docs/advisory-flow.md`): `/analyze` nhận vị thế đàm phán (`NegotiationPosition`:
leverage/urgency/relationship/alternatives) → agent gán `Risk.priority` (must_fix/negotiate/acceptable)
+ sinh `AnalysisResult.strategy` (chiến lược giữ/nhượng + walk-away/BATNA). Đây là lời hứa "fallback
theo thế trận thật". MCP + observability: `inbound/mcp_server.py` expose tool `analyze_contract` qua Model Context Protocol
(`make mcp`); `outbound/observability.py` `ObservabilityPort` (NoOp / Langfuse qua `LANGFUSE_*`) →
`AnalysisService.observer` emit event mỗi lần analyze.

Chat/memory (`docs/conversation.md`): kênh Zalo/Slack qua `ChatHandler` stateful + `ConversationStorePort`
(in-memory MVP, prod Redis/SQL): nhớ history + deal context; intent routing (tín hiệu HĐ → analyze; có deal
context → follow-up qua `reasoner`; câu hỏi pháp lý đứng một mình → `AnalysisService.lookup` tra cứu KB có
grounding, cũng expose qua `POST /ask`). Webhook: ack nhanh + BackgroundTasks; outbound `chat_senders.py`.

Web UI: `web/index.html` (landing, `GET /`) + `web/app.html` (demo UI, `GET /app`): form
upload/dán HĐ + vị thế đàm phán → gọi `/analyze` → bảng risks/fallbacks/strategy/trace +
**human checkpoint** (english_reply bị khóa tới khi reviewer Approve; Reject = chuyển chuyên gia).
+ `web/lookup.html` (`GET /lookup`): form tra cứu luật → `/ask` → câu trả lời dẫn điều/khoản + nguồn + nút feedback.

Upload: `DocumentParserPort` = `OcrFallbackParser(PdfDocxParser, QwenVisionOcr)` — text-PDF/DOCX/TXT
dùng base; scan/ảnh (.png/.jpg/PDF-scan rỗng text) → OCR Qwen-VL (`QWEN_VL_MODEL`), fallback lỗi rõ
khi chưa có key. Còn thiếu (next): vòng đàm phán đa phiên, escalation chuyên gia thật, kênh Zalo.

Moat/flywheel (`docs/moat.md`): `Outcome` (kết quả đàm phán) → `OutcomeRepositoryPort` →
`POST /cases/{id}/outcome`, `GET /insights/tactics`; `AnalysisService` gắn `win_rate` vào fallback
(outcome-aware ranking). Đây là dữ liệu độc quyền — moat thật, không phải tech.
Vòng học: `Feedback` (phản hồi người dùng helpful/wrong/incomplete) → `FeedbackRepositoryPort` →
`POST /feedback` (+ nút trên web UI) + `GET /feedback` (export build golden set); gom lỗ hổng KB từ usage thật.
Trên Slack: câu trả lời (analyze/lookup) kèm Block Kit buttons 👍/⚠️/➖ → `POST /channels/slack/interactions`
(verify chữ ký trên raw body, replace_original xác nhận). Lookup chat hiện cả nguồn (📎). Routing: câu có dấu
hỏi/từ-để-hỏi (`_is_question`) ưu tiên lookup dù chứa từ khóa HĐ.

Security (`docs/security.md`): API-key auth + per-company scoping (`API_KEYS="key:org:VN"`), PII
redaction (`domain/redaction.py`), prompt-injection hardening, upload limit, right-to-erasure,
rate limiting (`RATE_LIMIT_PER_MIN`), LLM retry/backoff (`adapters/outbound/_http.py`).
CI: `.github/workflows/ci.yml` (ruff + pytest). Qwen via dashscope-intl (Singapore, no-training).
Prod TODO: encrypt-at-rest (RDS/KMS), RLS, observability.

Docker (Postgres + app): `make up` (build+run+migrate), `make down`, `make logs`, `make psql`,
`make help`. Compose sets `DATABASE_URL` to the postgres service; app runs `alembic upgrade head`
on start. `make test` / `make lint` / `make run` run locally without Docker.

Runs without API keys in **stub mode** (LLM clients return `[..._STUB]` text) so the full flow is
exercisable offline. Set `QWEN_API_KEY` / `GEMINI_API_KEY` in `.env` for real analysis.

## What this project is

**Legal Guard PH** (also referred to as "VietDeal Copilot" in the plan) is an AI agent that acts as an
outsourced legal department for Vietnamese SMEs negotiating international commercial contracts. It analyzes
contracts, flags risky clauses, and proposes flexible fallback negotiation tactics based on each party's
real bargaining position. Built for two hackathons: Qwen Cloud (deadline 8 Jul 2026, Autopilot
Agent track) and Gemini XPRIZE (deadline 17 Aug 2026, Professional Services).

## Architecture — Hexagonal (Ports & Adapters)

Full write-up: **`docs/architecture.md`**. Key rule: dependencies point inward; `legalguard/domain/`
never imports adapters or frameworks.

- **`legalguard/domain/`** — business core. `ports.py` defines the interfaces the domain needs
  (`LLMPort`, `KnowledgeBasePort`, `KnowledgeBaseProvider`, `DocumentParserPort`, `LLMError`).
  `agent.py` is the ReAct tool-calling loop; `analysis.py` is the `AnalysisService` use-case;
  `tools.py` holds tool schemas + dispatch; `models.py` holds DTOs; `tenants.py` the tenant config.
- **`legalguard/adapters/outbound/`** — implement the ports: `qwen.py`/`gemini.py` (`LLMPort`),
  `knowledge_base.py` (keyword + embedding retrievers + provider), `document_parser.py`.
- **`legalguard/adapters/inbound/http.py`** — FastAPI driving adapter (HTTP ↔ domain).
- **`legalguard/config/container.py`** — composition root, the ONLY place adapters are wired into
  the domain. Swapping a provider = new adapter + one line here; domain stays untouched.

Tenancy is two axes (`tenants.py`): **Tenant = country/jurisdiction** (selects KB `knowledge_base/<CC>/`)
and **Organization = company** (data isolation by `org_id` + per-company KB overlay at
`knowledge_base/_orgs/<org_id>/` via `OverlayRetriever`). Data isolation is per-COMPANY, not per-country;
`AnalysisService.analyze(contract, org)` and cases are scoped by `org_id`. Qwen = reasoner (agent),
Gemini = summarizer (≥1-Gemini-call XPRIZE rule). Deploy target: Alibaba Cloud ECS.

The **Fallback Matrix** (`docs/internal/legal-guard.md` §6) is the product's core logic: a mapping from a partner-imposed
clause → risk analysis → concrete compromise tactic. This is the differentiator (flexible tactics, not rigid
contract templates), so changes here are product-critical and should be grounded in the legal knowledge base
rather than invented.

## Tech stack

Python ≥3.11 + FastAPI, managed with `uv` (`pyproject.toml` + `uv.lock`). Lint with ruff, test with
pytest (`pythonpath=["."]` so tests import `legalguard.*`). LLM access goes through the `LLMPort`
interface in `legalguard/domain/ports.py`; KB retrieval via `KnowledgeBasePort` — keyword-based now,
swappable to a vector DB by adding an adapter, no domain change.
