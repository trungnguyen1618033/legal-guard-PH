# Legal Guard — Devpost submission (Qwen Cloud Hackathon · Autopilot Agent)

> Copy-paste source for the Devpost form. Keep in sync with `README.md`.

**Tagline:** An autopilot legal agent that reviews cross-border contracts, flags illegal/unfavorable
clauses, and proposes position-aware negotiation tactics — with a human in the loop.

**Track:** Autopilot Agent · **Built with:** Qwen models on Qwen Cloud, Alibaba Cloud ECS · **License:** MIT

**Try it out:**
- 🌐 Live (Alibaba Cloud ECS): https://legalguard.duckdns.org — [`/app`](https://legalguard.duckdns.org/app) (analyze) · [`/lookup`](https://legalguard.duckdns.org/lookup) (legal Q&A + autopilot) · [`/trust`](https://legalguard.duckdns.org/trust) (published accuracy 54/54 golden)
- 📦 Repo (MIT): https://github.com/trungnguyen1618033/legal-guard-PH — submission tag `v1.0-qwen`
- 🎬 Demo video: `<YOUTUBE_LINK>` · Alibaba-deploy proof recording: `<YOUTUBE_LINK_2>`

---

## Inspiration
Vietnamese SMEs sign international contracts drafted by the other side's lawyers — and routinely accept
clauses that are unfavorable or even void under Vietnamese law (e.g. a 15% penalty when the Commercial
Law caps it at 8%). Big-law AI tools (Harvey, Luminance, Spellbook) assume an in-house legal team, an
English/common-law playbook, and enterprise budgets. Nobody serves the SME that just needs to know
*"what's risky here, and how do I push back from my actual bargaining position?"* — in Vietnamese, on
the chat apps they already use.

## What it does
- **Reviews a contract** (paste, upload, or scanned image via OCR) and flags each risky clause, separating
  **⚖️ illegal (voidable)** from merely **unfavorable**, with a deterministic citation to the in-force article.
- **Proposes position-aware fallbacks**: you declare leverage / urgency / relationship / BATNA and the
  agent returns keep-vs-concede tactics + a ready-to-send bilingual counter-clause — not a rigid template.
- **Keeps a human in the loop**: the message to the counterparty is locked until a reviewer approves;
  rejecting escalates to a lawyer.
- **Works proactively (autopilot)**: a cron service inside the production Docker stack scans
  newly-issued laws **every day at 5 AM** and tells you which past contracts are now affected —
  and self-tunes when you dismiss a false alarm. The agent literally works while you sleep.
- **Grounded, never fabricated**: in-force filtering (won't cite repealed law), NLI verification, and it
  **abstains** when the knowledge base doesn't cover a question.
- Channels: Web UI, **Slack** and **Zalo** bots, and an **MCP** tool.

## How we built it
- **Hexagonal (Ports & Adapters)** FastAPI core — the domain never imports a vendor SDK; swapping a
  provider is one line. Runs fully offline in a stub mode, so the whole flow is testable without keys.
- **ReAct agent loop** (`agent.py`) with 4 tools (`search_legal_knowledge`, `flag_risk`,
  `propose_fallback`, `request_human_review`); every step recorded in a `trace` + `execution_summary`.
- **Qwen models on Qwen Cloud / DashScope (Alibaba Model Studio)**, right-sized per task:
  `qwen3.7-max` (reasoning agent) · `qwen-flash` (NLI verify / self-critique) · `qwen-plus` (legal lookup) ·
  `text-embedding-v4` (retrieval) · `qwen3-rerank` (cross-encoder) · `qwen3.7-plus` (OCR).
- **Deployed on Alibaba Cloud ECS**: Docker (Caddy HTTPS + app + Postgres + Redis), Alembic migrations,
  persistent embeddings in Postgres.
- **RAG quality**: hybrid retrieval (BM25 + embeddings, RRF), grounding + citation, 2-layer verification
  (LLM-judge + NLI entailment), in-force/point-in-time filtering, citation closure. The NLI judge has its
  **own labeled eval**: 16/16 correct incl. hard negatives, 100% agreement with the flagship (`evaluation/nli_report.json`).
- **AI-Native evidence**: `GET /runs` exposes a live feed of the agent's tool calls and decisions.

## Challenges we ran into
- **Not citing dead law**: an in-force filter that returns only law valid at the relevant point in time —
  a safety feature that must *abstain* rather than answer when unsure.
- **Grounding vs hallucination**: NLI entailment to reject "citation exists but doesn't support the claim".
- **Latency**: model right-sizing (flash for yes/no checks) cut post-agent verification from ~23s to ~0.5s.
- **Honest metrics**: we publish 54/54 on an internal golden set via majority-vote, and openly note
  the one borderline case that still flickers run-to-run — rather than claiming a flat 100%.

## What we learned
The moat isn't the RAG (that's commodity) — it's position-aware negotiation, a data flywheel, and trust
by design. Open-sourcing the engine (MIT) while keeping the tactic/eval data private is the right split.

## What's next
Lawyer-verified golden set (trust lever) · self-hosted GPU reranker (measured +0.13 MRR@10 on Zalo LTR) ·
encrypt-at-rest + RLS for PDPD compliance · outcome flywheel productized · more jurisdictions.

## How we use Qwen + Alibaba Cloud (mandatory)
See the table in [`README.md`](../README.md#powered-by-qwen-models-on-qwen-cloud-deployed-on-alibaba-cloud)
and the diagram in [`architecture-diagram.en.md`](architecture-diagram.en.md). All inference is Qwen via
DashScope-intl; hosting is Alibaba Cloud ECS; the repo is MIT (open-core).

---

## ✅ Submission checklist (RE-VERIFY nội quy chính thức qwencloud-hackathon.devpost.com/rules — 6/7/2026)

Hạn nộp: **July 9, 2026 @ 2:00 PM PT** (= ~4:00 sáng 10/7 giờ VN) — mục tiêu an toàn: submit xong 8/7.
Ngôn ngữ: **MỌI tài liệu phải tiếng ANH** (hoặc kèm bản dịch EN) — description/video/testing instructions.

- [ ] Repo **public** + **LICENSE MIT "detectable & visible at top of repo page"** (GitHub tự nhận MIT ✓; chỉ cần bấm public)
- [x] Dùng Qwen models trên Qwen Cloud (6 model qua DashScope) — `qwen.py`
- [x] **Proof Alibaba = LINK FILE CODE** (nội quy: "a link to a code file that demonstrates use of Alibaba Cloud
      services and APIs") → `legalguard/adapters/outbound/qwen.py` + `config/settings.py` (endpoint
      `dashscope-intl.aliyuncs.com` = Alibaba Model Studio/Qwen Cloud). ⚠️ KHÔNG bắt buộc video — file code là đủ.
- [x] Deploy Alibaba Cloud ECS — live https://legalguard.duckdns.org (thêm bằng chứng runtime)
- [x] Architecture diagram (`architecture-diagram.en.md`)
- [x] Text description (file này) + chọn track **Autopilot Agent**
- [ ] 🎬 Video demo **<3 phút**, public **YouTube/Vimeo/Youku**, tiếng Anh, KHÔNG nhạc/nhãn-hiệu bản quyền → điền link
- [ ] (Điểm cộng, không bắt buộc) Recording backend chạy Alibaba: console ECS → SSH `docker ps` → `curl /health`
- [ ] (Optional, có giải Blog Post riêng) blog "building with Qwen Cloud" → điền link

**Chấm (Stage 2, đều nhau về nhóm):** Innovation & AI Creativity 30% · Technical Depth 30% · Problem Value 25% ·
Presentation & Documentation 15% (= demo rõ + arch docs; KHÔNG cần deck riêng). Stage 1 = pass/fail (đúng theme + dùng Qwen API).
Autopilot track nhấn: ambiguous inputs · external tools · human-in-the-loop · **production-ready (không phải toy demo)**.

Judging: Technical Depth 30% · Innovation 30% · Problem Value 25% · Presentation 15% — video nên phân bổ
thời lượng theo đúng tỉ trọng này (kỹ thuật + sáng tạo = 60% điểm).

---

## 🎬 Demo video script (~3 min, EN)
1. **Hook (0:00–0:20)** — "Vietnamese SMEs sign foreign contracts that are unfavorable or illegal under
   Vietnamese law. Legal Guard is an autopilot agent that catches this and helps you push back."
2. **Analyze (0:20–1:10)** — `/app`: paste a contract with a 15% penalty + Singapore-court + 50% deposit;
   pick position "buyer / weak leverage" → Analyze. Show: **⚖️ ILLEGAL (Art. 301, cap 8%)**, the
   **🤖 agent execution summary** (tool calls), and the **locked** message-to-counterparty (human checkpoint).
3. **See the agent think (1:10–1:40)** — open the Trace tab / `GET /runs` feed: real tool calls & decisions
   (AI-Native evidence).
4. **Negotiate (1:40–2:10)** — paste the counterparty's reply ("we'll only go to 12%") → a new negotiation
   round cites the 8% cap; generate a bilingual counter-clause.
5. **Autopilot (2:10–2:40)** — show the in-stack cron (`docker compose logs autopilot-cron`) + trigger
   `/monitor/run` with an older `since` so it fires on real data (Decree 63/2011 → 8 arbitration cases
   flagged): "the agent scans new laws while you sleep"; dismiss a false alarm → it self-tunes.
6. **Trust close (2:40–3:00)** — `/trust`: 54/54 internal golden (majority-vote), in-force filter, 2-layer verify —
   "grounded, never fabricated." Mention: Qwen on Qwen Cloud, Alibaba Cloud ECS, MIT open-core.
