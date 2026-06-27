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
uv run python -m ingestion.hf_to_kb --pages 4 --keyword "hóa đơn" --out knowledge_base/_ingested # ETL sample: HF dataset luật VN → KB .md (front-matter status)
uv run python -m ingestion.hf_to_kb --bulk --limit 2000 --out knowledge_base/_ingested # CON BATCH bulk: ingest toàn bộ th1nhng0 (cần `uv add datasets`) + cạnh đồ thị (amends/replaced_by/guides) + hiệu lực
uv run python -m evaluation.feedback_to_golden --org default --out evaluation/golden_candidates.json # vòng học: feedback ⚠️/➖ → ứng viên golden + báo lỗ hổng KB
uv sync --group eval                  # cài lớp eval sâu (RAGAS) — opt-in, không cần cho runtime
uv run python -m evaluation.ragas_eval  # deep eval: RAGAS LLM-as-judge (cần QWEN_API_KEY; chậm/tốn call)
uv run python -m evaluation.integration_check  # smoke LLM THẬT (như trên Slack): analyze/lookup/counter… → lưu snapshot.json+md (evaluation/snapshots/) để diff giữa các lần
uv run python -m evaluation.integration_check --compare evaluation/snapshots/<cũ>/snapshot.json  # so nhanh với lần chạy cũ (định tuyến/#risk/độ dài reply)
uv run python -m evaluation.lookup_format_check  # test format+cache lookup nhiều case THẬT (Trả lời/Căn cứ + đo cache)
uv add <pkg>                       # add a dependency
```

AI/RAG quality techniques: grounding+citation+evidence (`tools.py`), verification 2-layer
(clause-existence + LLM-judge + NLI entailment `nli_supports` — kiểm "nguồn CÓ hậu thuẫn claim không",
chống citation tồn-tại-nhưng-không-hỗ-trợ, `NLI_VERIFICATION`; áp vào legal_basis grounding + lookup,
`domain/verification.py`), **NLI-mâu-thuẫn `nli_contradicts`** (đảo chiều — "điều khoản CÓ TRÁI điều luật
không"; Phase B phát hiện TRÁI LUẬT có grounding, parser CHẶT bất-đối-xứng: NO/KHÔNG→False an toàn, chỉ
'YES' tiếng Anh→True, bỏ 'CÓ' tránh va 'có thể'→illegal sai), lexical BM25 (Okapi, length-norm + IDF) +
embedding, hybrid retrieval RRF + opt-in LLM reranker
+ opt-in cross-encoder reranker (Qwen `gte-rerank`, `CROSS_ENCODER_RERANK`) + full-context
(`outbound/knowledge_base.py`, `RERANK_ENABLED`). **Rerank theo path** (đo: chi phí rerank chỉ ~272ms/
retrieve, latency analyze ~99% là vòng flagship output-bound — KHÔNG nén được ở tầng retrieval): `/analyze`
gọi `for_org(org, rerank=False)` (hybrid RRF, bỏ rerank — giảm tải quota khi đông user, zero quality cost);
`/lookup` giữ rerank (Q&A pháp lý cần xếp hạng chính xác). structure-aware legal chunking + NFC + citation
extraction (`outbound/legal_chunker.py` — chunk theo Điều/Khoản, nhãn gắn vào `Snippet.source` dạng
`file.md#Điều 5`; Phase 0 hướng mở rộng tra cứu luật VN, xem `docs/internal/legal-search-expansion.md`),
citation closure document-aware đi theo dẫn chiếu kéo về điều luật liên quan ở ĐÚNG văn bản đích
(`CitationClosureRetriever`, `CITATION_CLOSURE`; article-level: `extract_article_refs` phân giải "Điều 9 của
NĐ 123/2020"→đúng file qua map doc_id, "của Luật này"→cùng file; doc-level: cạnh amends/amended_by/replaced_by/
guided_by từ front-matter → kéo VB sửa đổi/thay thế/hướng dẫn liên quan; dựng cạnh bằng rule không LLM — Phase 2), lọc hiệu lực mặc-định-chỉ-trả-văn-bản-còn-hiệu-lực
(`InForceRetriever`, `IN_FORCE_FILTER`, theo front-matter `status`; ý định lịch sử mới hiện bản cũ;
**point-in-time #11**: câu hỏi có mốc thời gian "năm 2020"/"1/6/2022" → trả VB còn hiệu lực TẠI mốc đó
theo effective_date/expiry_date — `_extract_as_of`/`_valid_at`),
căn cứ pháp lý tất định cho từng risk & fallback (`_legal_citation` trong `domain/analysis.py`,
`LEGAL_BASIS_GROUNDING`: tra KB gắn `Risk.legal_basis`/`Fallback.legal_basis` = điều luật còn hiệu lực,
ngưỡng trùng ≥3 thuật ngữ để tránh căn cứ lạc), adaptive routing + chunking (`domain/analysis.py`),
**latency — model right-sizing (3 tầng)**: việc KHÓ (agent phân tích, sinh chiến lược) dùng flagship
`qwen3.7-max`; việc PHỤ yes/no (NLI entailment, verify gộp) dùng `judge` = `qwen-flash` (`QWEN_FAST_MODEL`)
— đo thực tế: NLI flagship ~23s vs flash ~0.5s, flash KHỚP flagship → cắt hậu-agent ~264s→~7s. TRA CỨU
(`lookup`) dùng `qwen-plus` (`QWEN_LOOKUP_MODEL`, ~4-6s vs ~48s flagship, format/citation y hệt) — HYBRID:
câu point-in-time (có năm/ngày, `_PIT_RE`) tự route flagship vì plus yếu hơn ở suy luận thời điểm (đã đo).
Lookup còn: template cố định **Trả lời/Căn cứ**, redact PII câu hỏi trước khi gửi LLM, cache LRU
(`LOOKUP_CACHE_SIZE`, hỏi lặp→0ms), ack "đang tra cứu". Hậu-agent (verify ∥ summary ∥ legal_basis) chạy
song song; NLI mỗi clause cũng song song (`_attach_legal_basis`).
eval harness + A/B (`evaluation/`). Hai tầng eval: `run_eval.py` =
fast gate keyword-matching (offline, free, dùng trong CI); `ragas_eval.py` = deep gate RAGAS
LLM-as-judge (Faithfulness / Context Precision / Response Relevancy; + Context Recall + Factual
Correctness khi golden có `reference`), judge = Qwen qua endpoint OpenAI-compatible nên không cần
OpenAI key. Opt-in qua group `eval` (pin langchain <1.0 — RAGAS 0.4.3 cần `langchain_community.chat_models.vertexai`).

Advisory flow (`docs/advisory-flow.md`): `/analyze` nhận vị thế đàm phán (`NegotiationPosition`:
leverage/urgency/relationship/alternatives + **`protected_party`** "bên mình bảo vệ") → agent gán
`Risk.priority` (must_fix/negotiate/acceptable) + **`Risk.legal_status`** {illegal (trái luật, có thể vô
hiệu — kèm `violated_law`) | unfavorable} + sinh `AnalysisResult.strategy` (giữ/nhượng + walk-away/BATNA).
Lawyer-review (Phase A+B, `docs/internal/lawyer-review-flow.md`): party-aware + tách TRÁI-LUẬT vs bất-lợi;
prompt rỗng protected_party → mặc định "SME client in {country}". Chat reply + web gắn nhãn ⚖️ TRÁI LUẬT.
**Phase B — phát hiện TRÁI LUẬT có grounding (`_detect_illegal` trong `domain/analysis.py`, `ILLEGAL_DETECTION`)**:
hậu-agent (sau legal_basis), với mỗi risk `unfavorable` đã có `legal_basis` (điều luật THẬT đã retrieve) →
`nli_contradicts` hỏi judge "điều khoản CÓ trái điều luật này không"; YES rõ → nâng `unfavorable`→`illegal` +
`violated_law` trích từ legal_basis (vd "Điều 466"). BẢO THỦ (nghi ngờ→giữ unfavorable, KHÔNG hạ illegal của
agent), song song mỗi risk, LUÔN ép human-review + note "cần luật sư đối chiếu bản gốc" — định vị là lớp SÀNG
LỌC cho luật sư, không phán quyết. Phụ thuộc `legal_basis_grounding` (cần legal_basis để có điều luật đối
chiếu). KB cần điều luật liên quan (đã thêm Đ.466/468 BLDS — trần lãi vay 20%/năm, lãi quá hạn 150%). Đo thật:
HĐ thương mại phạt 15%→illegal Đ.301; HĐ vay→illegal Đ.466. Đây là lời hứa "fallback theo thế trận thật". MCP + observability: `inbound/mcp_server.py` expose tool `analyze_contract` qua Model Context Protocol
(`make mcp`); `outbound/observability.py` `ObservabilityPort` (NoOp / Langfuse qua `LANGFUSE_*`) →
`AnalysisService.observer` emit event mỗi lần analyze.

Chat/memory (`docs/conversation.md`): kênh Zalo/Slack qua `ChatHandler` stateful + `ConversationStorePort`
(in-memory MVP, prod Redis/SQL): nhớ history + deal context; intent routing (tín hiệu HĐ → analyze; có deal
context → follow-up qua `reasoner`; câu hỏi pháp lý đứng một mình → `AnalysisService.lookup` tra cứu KB có
grounding, cũng expose qua `POST /ask`). Webhook: ack nhanh + BackgroundTasks; outbound `chat_senders.py`.
Concurrency/threading: hội thoại định danh theo THREAD (`slack:{channel}:{thread_ts}`) — mỗi thread = 1 deal
riêng, reply LUÔN threaded dưới tin người hỏi (`thread_ts or ts`); **lock per-conversation** (`threading.Lock`
trong `reply_ex`) tuần tự hóa tin cùng hội thoại → chống race load→sửa→save, hội thoại khác chạy song song
(verified test contention; đủ 1 instance, đa-instance cần Redis lock — `docs/internal/scale-concurrency.md`).
History redact PII trước khi lưu; reply Slack chia nhiều block (`_mrkdwn_blocks`, ≤2900/block, không cụt).

Web UI: `web/index.html` (landing, `GET /`) + `web/app.html` (demo UI, `GET /app`): form
upload/dán HĐ + vị thế đàm phán → gọi `/analyze` → bảng risks/fallbacks/strategy/trace +
**human checkpoint** (english_reply bị khóa tới khi reviewer Approve; Reject = chuyển chuyên gia).
+ `web/lookup.html` (`GET /lookup`): form tra cứu luật → `/ask` → câu trả lời dẫn điều/khoản + nguồn + nút feedback
(+ section "VB mới ảnh hưởng HĐ nào?" `/impact`, changelog, redline, **🗺️ Lược đồ văn bản** `loadGraph`: gọi
`/graph`+`/latest`+`/articles-changed` → vẽ nodes tô màu hiệu lực + edges quan hệ + banner bản-mới-nhất +
bôi-vàng-điều-bị-sửa, kiểu TVPL). app.html mỗi fallback có nút "📝 soạn
điều khoản phản-đề" (`/counter`). + `web/dashboard.html` (`GET /dashboard`): system-of-record → `/insights/dashboard`
(HĐ rà soát, phân bố severity, top điều khoản rủi ro, feedback, win-rate chiến thuật).

Upload: `DocumentParserPort` = `OcrFallbackParser(PdfDocxParser, QwenVisionOcr)` — text-PDF/DOCX/TXT
dùng base; scan/ảnh (.png/.jpg/PDF-scan rỗng text) → OCR Qwen-VL (`QWEN_VL_MODEL`), fallback lỗi rõ
khi chưa có key. Còn thiếu (next): escalation chuyên gia thật (hiện chỉ gắn cờ needs_human_review); Zalo
prod cần token/verify OA thật (webhook + sender đã code).

Đàm phán đa phiên (`domain/negotiation.py`, lõi Autopilot Agent): `POST /negotiate` {deal_context,
partner_message, leverage/urgency/…, protected_party} → `negotiate_round`: nhận bối cảnh deal (từ /analyze
hoặc vòng trước) + tin đối tác vừa gửi → `NegotiationRound` {assessment (đối tác nhượng/giữ gì), strategy
(vòng tới), reply_vi/reply_en, status: continue|close|walk_away}. Reasoner soạn bám vị thế; offline → khung
an toàn (grounded=False). `_parse_round` thuần (ép enum status). UI app.html: card "💬 Đàm phán đa phiên" sau
kết quả — dán phản hồi đối tác → round mới, NỐI bối cảnh qua các vòng (`_deal`), badge status.

Counter-clause (`domain/counter_clause.py`): `POST /counter` {clause, risk, suggestion, legal_basis, leverage}
→ điều khoản PHẢN-ĐỀ song ngữ VN/EN dán-được-ngay vào HĐ (khác `english_reply` = câu nhắn đối tác). Qwen
reasoner soạn bám `legal_basis` + vị thế; offline → khung an toàn `grounded=False`, KHÔNG bịa luật.
`_parse_counter` thuần (khối ```json/{} trần, fallback vi=raw). UI: nút "📝 Soạn điều khoản phản-đề" mỗi
fallback trong `web/app.html`.

Moat/flywheel (`docs/moat.md`): `Outcome` (kết quả đàm phán) → `OutcomeRepositoryPort` →
`POST /cases/{id}/outcome`, `GET /insights/tactics`; `AnalysisService` gắn `win_rate` vào fallback
(outcome-aware ranking). Đây là dữ liệu độc quyền — moat thật, không phải tech. **UI đóng vòng**: mỗi
fallback trong app.html có nút "📊 Kết quả thực tế" (Chấp nhận/Một phần/Từ chối) → ghi Outcome → nuôi
win-rate → lần phân tích sau hiện badge `win X%` (càng dùng càng khôn).
**Escalation chuyên gia THẬT** (`POST /escalate` {case_id, reason, via?, channel?}): reviewer Reject (app.html)
→ gửi case cho luật sư qua kênh chuyên gia (`EXPERT_CHANNEL` cấu hình sẵn, hoặc channel truyền vào) — hoàn tất
human-checkpoint (không chỉ gắn cờ mà CHUYỂN tới người thật). Chưa cấu hình kênh → vẫn nhận (ok, sent=False).
System-of-record dashboard: `GET /insights/dashboard` = tổng hợp 1 org (HĐ đã rà soát, rủi ro hay gặp +
phân bố severity, top điều khoản rủi ro, tín hiệu feedback + lỗ hổng KB, top chiến thuật theo win-rate).
`domain/dashboard.build_dashboard` THUẦN (gộp cases/feedback/win_rates). Càng dùng càng nhiều dữ liệu →
switching cost (moat: system-of-record).
Vòng học: `Feedback` (phản hồi người dùng helpful/wrong/incomplete) → `FeedbackRepositoryPort` →
`POST /feedback` (+ nút trên web UI) + `GET /feedback` (export build golden set); gom lỗ hổng KB từ usage thật.
Đóng vòng: `evaluation/feedback_to_golden.py` biến feedback ⚠️ wrong/➖ incomplete → ứng viên golden set
(`expected` rỗng cho luật sư điền) + báo lỗ hổng KB (`gap_report`) → merge vào `legal_golden.json` → eval đo
cải thiện (usage→feedback→golden→đo→vá). Hàm thuần test offline; CLI đọc feedback từ DB qua repo.
Trên Slack: câu trả lời (analyze/lookup) kèm Block Kit buttons 👍/⚠️/➖ → `POST /channels/slack/interactions`
(verify chữ ký trên raw body, replace_original xác nhận). Lookup chat hiện cả nguồn (📎). Routing: câu có dấu
hỏi/từ-để-hỏi (`_is_question`) ưu tiên lookup dù chứa từ khóa HĐ.

"What changed" (`docs`/#10): `GET /changes/{doc_id}` = changelog cấp văn bản (sửa đổi/thay thế bởi/của VB nào,
ngày hiệu lực — suy 2 chiều từ front-matter, `legal_changelog`); `POST /redline` {old,new} = diff text 2 phiên
bản ([+thêm+]/[-bỏ-] + similarity, `domain/redline.py`, difflib tất định, không LLM).

Legal-search (kiểu TVPL — Phase 1, `verified_legal_graphrag_2026_reviewed.md`): **`GET /graph/{doc_id}?depth=`** =
LƯỢC ĐỒ văn bản {nodes (doc_id/title/status/effective_date/in_kb), edges (from/relation/to)} mở rộng đa-hop
(BFS 2 chiều từ front-matter, `legal_graph`); **`GET /latest/{doc_id}`** = map tới VĂN BẢN MỚI NHẤT theo chuỗi
`replaced_by`, chọn bản effective_date lớn nhất khi nhiều (`latest_version`). Ingestion ghi cạnh đồ thị:
`group_relationships`+`to_kb_markdown(relations=)` (front-matter amends/replaced_by/guides…); CON BATCH bulk
`run_bulk` join metadata+content+relationships th1nhng0 (`--bulk`, cần `datasets`; đọc content.parquet THẲNG
bằng pyarrow — `datasets` lỗi cast large_string). HƯỚNG quan hệ đã VERIFY bằng cặp thật (70/2025⇄123/2020):
"được/bị X"=source làm X cho other; "X"=other làm X cho source (`_REL_FIELD`). Engine (closure/in-force/
point-in-time/changelog/impact) ĐÃ có — Phase 1 = nạp graph quy mô lớn + endpoint lược đồ/VB-mới-nhất.
**Phase 2 — article-change ("sửa chỗ nào"/bôi vàng)**: `extract_article_changes` (`legal_chunker.py`, RULE tất
định: "Sửa đổi, bổ sung Điều N"→amend, "Bãi bỏ…Điều N"→repeal, "Bổ sung Điều Na"→add, "Thay thế…"→replace;
lấy động từ GẦN điều nhất, cụm "sửa đổi, bổ sung"=amend) → ingestion TỰ điền `amends_articles` từ thân VB sửa
(thay khai tay). **`GET /articles-changed/{doc_id}`** = đọc luật → ĐIỀU nào đã bị VB nào sửa (`amended_articles`,
'bôi vàng' kiểu TVPL). Đã verify trên data thật (slice hóa đơn: 04/2014→replaced_by→123/2020, lược đồ 12 nodes).

Regulatory change intelligence (chủ động, moat system-of-record): `GET /impact/{doc_id}` = VB pháp luật MỚI
ban hành → case nào của công ty viện dẫn văn bản nó vừa sửa đổi/thay thế/hướng dẫn → cần rà soát lại.
Nối: `affected_doc_files` (suy file luật bị tác động qua changelog quan hệ amends/replaces/guides; trả
{file: {relation, articles}} — `articles` từ front-matter `amends_articles` của VB mới) →
`AnalysisService.regulatory_impact` → `scan_cases` (THUẦN, `domain/regulatory.py`: quét `legal_basis`/`source`
của risk+fallback, khử trùng theo (case,kind,clause,file)). ARTICLE-LEVEL: CHỈ quan hệ `amends` mới lọc theo
`amends_articles` (chỉ cảnh báo case viện dẫn ĐÚNG điều bị sửa, giảm báo động giả); `replaces`/`guides` =
doc-level (thay cả VB → mọi viện dẫn lỗi thời). Cô lập `org_id`.
UI: section "Văn bản mới ảnh hưởng hợp đồng nào?" trong `web/lookup.html`.
Cảnh báo CHỦ ĐỘNG: `POST /impact/{doc_id}/notify` {via: slack|zalo, channel} → quét + `format_impact_alert`
(gom theo case, text) → gửi qua sender tương ứng (truyền vào `build_api(senders=...)` từ container, dùng chung
sender với webhook). Hợp với cron/ops khi VB mới ban hành.
**AUTOPILOT giám sát chủ động** (`POST /monitor/run` {since, via?, channel?}): agent TỰ phát hiện luật MỚI
(`recent_laws`: effective_date >= since) → `AnalysisService.monitor` quét MỌI VB mới × case của org →
digest `format_monitor_digest` → gửi Slack/Zalo nếu có via+channel. KHÔNG cần chỉ từng doc_id (khác /impact).
UI: section "🤖 Autopilot — quét luật mới" trong `web/lookup.html`. Production = cron trên ECS gọi hằng ngày
(`curl -XPOST .../monitor/run -d '{"since":"<hôm-qua>","via":"slack","channel":"..."}'`) → "agent làm việc
khi bạn ngủ" (đúng tinh thần Autopilot Agent). Cô lập org_id.

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
  `tools.py` holds tool schemas + dispatch (reason-then-format: `reasoning` là property ĐẦU TIÊN của
  `flag_risk`/`propose_fallback` — model suy luận trước khi điền các trường quyết định severity/priority/
  suggestion; optional, vào trace để audit); `models.py` holds DTOs; `tenants.py` the tenant config.
- **`legalguard/adapters/outbound/`** — implement the ports: `qwen.py`/`gemini.py` (`LLMPort`),
  `knowledge_base.py` (keyword + embedding retrievers + provider), `document_parser.py`.
- **`legalguard/adapters/inbound/http.py`** — FastAPI driving adapter (HTTP ↔ domain).
- **`legalguard/config/container.py`** — composition root, the ONLY place adapters are wired into
  the domain. Swapping a provider = new adapter + one line here; domain stays untouched.

Tenancy is two axes (`tenants.py`): **Tenant = country/jurisdiction** (selects KB `knowledge_base/<CC>/`)
and **Organization = company** (data isolation by `org_id` + per-company KB overlay at
`knowledge_base/_orgs/<org_id>/` via `OverlayRetriever`). Data isolation is per-COMPANY, not per-country;
`AnalysisService.analyze(contract, org)` and cases are scoped by `org_id`. VAI TRÒ LLM (right-sizing):
Qwen flagship `qwen3.7-max` = reasoner (agent phân tích — việc KHÓ); Qwen `qwen-flash` = `judge` (NLI/verify
yes/no — ~0.5s vs ~23s); Qwen `qwen-plus` = `lookup_llm` (tra cứu Q&A — ~4-6s, hybrid: point-in-time→flagship);
Gemini = summarizer (≥1-Gemini-call XPRIZE rule). `judge`/`lookup_llm` mặc định = reasoner nếu không cấu hình
(giữ tương thích/stub). Deploy target: Alibaba Cloud ECS.

The **Fallback Matrix** (`docs/internal/legal-guard.md` §6) is the product's core logic: a mapping from a partner-imposed
clause → risk analysis → concrete compromise tactic. This is the differentiator (flexible tactics, not rigid
contract templates), so changes here are product-critical and should be grounded in the legal knowledge base
rather than invented.

## Tech stack

Python ≥3.11 + FastAPI, managed with `uv` (`pyproject.toml` + `uv.lock`). Lint with ruff, test with
pytest (`pythonpath=["."]` so tests import `legalguard.*`). LLM access goes through the `LLMPort`
interface in `legalguard/domain/ports.py`; KB retrieval via `KnowledgeBasePort` — keyword-based now,
swappable to a vector DB by adding an adapter, no domain change.
