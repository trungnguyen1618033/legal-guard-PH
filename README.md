# Legal Guard — Agentic-Memory Legal Agent for Cross-Border Contracts

![Agentic memory on CockroachDB](https://img.shields.io/badge/agentic_memory-CockroachDB_VECTOR_%C2%B7_C--SPANN-6933FF)
![Measured accuracy](https://img.shields.io/badge/measured_accuracy-~98%25_(53–54%2F54)-brightgreen)
![Tests](https://img.shields.io/badge/tests-650%2B_passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-blue)
![Powered by Qwen](https://img.shields.io/badge/reasoning-Qwen_models-orange)

An AI agent that acts as an **outsourced legal department**: it reads an international commercial
contract, **flags risky and illegal clauses**, and proposes **position-aware negotiation tactics** —
then keeps a human in the loop before anything goes to the counterparty.

**Measured accuracy: ~98% (53–54/54)** on a lawyer-style golden set spanning 12 Vietnamese legal domains,
run against the real Qwen stack via majority-vote (3 runs/case). One or two borderline cases flicker
run-to-run (a wording match on the hosted model), so a given run reads 53 or 54 out of 54 — we publish the
measured range rather than cherry-pick a flat 100%. Methodology and live numbers at [`/trust`](web/trust.html)
(report: [`evaluation/accuracy_report.json`](evaluation/accuracy_report.json)).

> 🏆 Built for the **CockroachDB "Build with Agentic Memory" hackathon** — the agent keeps **durable,
> per-counterparty memory** on CockroachDB's distributed vector index (C-SPANN) and recalls it over MCP.
> Reasoning is powered by **Qwen** models (the project began on the Qwen Cloud Autopilot Agent track).
> Proving ground: Vietnamese SMEs negotiating cross-border deals.
> 🇻🇳 Vietnamese readme: [`README.vi.md`](README.vi.md) · 🏗️ Architecture: [`docs/architecture.en.md`](docs/architecture.en.md) · ⚖️ Open-core boundary: [`docs/OPEN-CORE.md`](docs/OPEN-CORE.md)

## Why it fits "Build with Agentic Memory"

The hackathon asks for an agent with **durable, queryable memory** that makes it act smarter over time.
Legal Guard's agent remembers **each counterparty across deals** — stored and recalled on CockroachDB
vector search — and combines that with end-to-end contract review, external tools (MCP), and
human-in-the-loop checkpoints:

- **Agentic memory (the hero)** — every negotiation outcome becomes a per-counterparty *episode*; on the
  next deal the agent recalls *"they accepted an 8% penalty cap last time"* via CockroachDB `VECTOR` +
  `CREATE VECTOR INDEX` (C-SPANN) ANN. Written async (off the hot-path), recalled as advisory context,
  strictly org-isolated with cascade right-to-erasure. Exposed over **MCP** as `recall_memory`.
- **End-to-end autonomy** — upload/paste a contract → the agent runs a **ReAct loop**, deciding which
  tools to call (`search_legal_knowledge`, `flag_risk`, `propose_fallback`, `request_human_review`)
  until it reaches a grounded conclusion, recording every step in a `trace`.
- **Self-critique** — after flagging risks the agent verifies its own findings (evidence must exist in
  the contract + a judge confirms each risk is supported by retrieved law) and marks unverified ones.
- **Position-aware negotiation (the differentiator)** — declare your leverage/urgency/BATNA and the agent
  runs *stateful* multi-round negotiation: a **concession ledger** remembers what's secured across rounds
  (never gives back a won point), a deterministic **walk-away guardrail** protects red-lines, and it
  proposes trade-based next moves — learning from real deal outcomes (win-rate flywheel).
- **Proactive autopilot** — `POST /monitor/run` scans newly-issued laws and tells you which of your
  past contracts are now affected — *"the agent works while you sleep"* (built for a daily cron). It
  even **self-tunes**: dismissed false alarms are suppressed next run.
- **Human-in-the-loop** — the message-to-counterparty stays **locked** until a reviewer approves;
  rejecting escalates the case to a real lawyer channel.
- **AI-Native evidence** — `GET /runs` exposes a live feed of what the agent did (tool calls, risks
  flagged, items escalated) so judges can *see* the agent making decisions, not just its output.

## 🚀 Quick demo (no API key needed)

```bash
uv sync && uv run uvicorn app:app          # runs in STUB mode offline (simulated LLM output)
```
Open **http://localhost:8000/app** → paste the sample below (or `examples/sample_contract_en.txt`) →
**Analyze**. Watch the **Trace** tab: the agent searches the legal KB → flags risks → checks each via
NLI → drafts position-aware fallbacks. Set `QWEN_API_KEY` in `.env` for real analysis.

What the demo shows:
- ⚖️ A **15% penalty clause flagged as *illegal*** (voidable under Art. 301 of Vietnam's Commercial
  Law 2005, which caps it at 8%) — separated from merely *unfavorable* terms.
- ♟️ A **negotiation strategy tuned to your bargaining position** (keep / concede / walk-away) — not a
  rigid template.
- 🧑‍⚖️ A **human checkpoint** gating the outbound message until an expert approves.

Other pages: **`/lookup`** (grounded legal Q&A + a TVPL-style document graph) · **`/dashboard`**
(system-of-record) · **`/runs`** (agent activity feed) · **`/docs`** (OpenAPI).

## Screenshots (real Qwen run)

| Contract analysis — risks flagged, ⚖️ illegal vs unfavorable | Agent ReAct trace — every tool call recorded |
|---|---|
| ![Contract analysis](docs/assets/demo-analyze.png) | ![Agent trace](docs/assets/demo-trace.png) |

| Grounded legal Q&A — answer + article citation + sources | Published trust page — methodology + measured accuracy |
|---|---|
| ![Legal lookup](docs/assets/demo-lookup.png) | ![Trust page](docs/assets/demo-trust.png) |

## Architecture — Hexagonal (Ports & Adapters)

```
app.py                         ASGI entrypoint
legalguard/
  domain/                      business core (no framework/infra imports)
    agent (ReAct loop) · tools · analysis (use-case) · verification (NLI self-critique)
    negotiation (multi-round) · counter_clause · regulatory (autopilot) · runs (AI evidence)
  adapters/
    inbound/http.py            FastAPI driving adapter · inbound/mcp_server.py (Model Context Protocol)
    outbound/                  qwen · knowledge_base (hybrid RAG) · document_parser (+OCR)
  config/container.py          composition root — the only place adapters are wired in
knowledge_base/VN/             in-force Vietnamese law (verbatim) + a 12-situation fallback matrix
```

**Dependencies point inward**: the domain defines ports, adapters implement them. Swapping a provider
is one line in `container.py`; the core never changes. **Model right-sizing**: hard reasoning uses the
flagship Qwen model; cheap yes/no checks (NLI verify) use a fast model — ~23s → ~0.5s with no quality loss.

**RAG quality:** grounding + citation (every risk carries a deterministic article reference) ·
2-layer verification (LLM-judge + **NLI entailment** to catch "citation exists but doesn't support the
claim") · hybrid retrieval (BM25 + embeddings, RRF) + optional rerank · **in-force filtering** (only
returns law valid at the relevant point in time) + **citation closure**. Provider errors degrade to a
safe `LLMError` instead of crashing. Full write-up: [`docs/architecture.en.md`](docs/architecture.en.md)
· diagram: [`docs/architecture-diagram.en.md`](docs/architecture-diagram.en.md).

## Stack — CockroachDB agentic memory · Qwen reasoning

**Memory & data: CockroachDB.** Agent memory, cases, KB embeddings and the flywheel all live on
CockroachDB; per-counterparty recall uses native `VECTOR` columns + `CREATE VECTOR INDEX` (C-SPANN) for
in-database ANN. One `DATABASE_URL` unifies app + memory + KB; the same SQLAlchemy layer also runs on
Postgres/SQLite via the hexagonal `MemoryPort` — swapping the backend is one line in `config/container.py`.

**Reasoning: Qwen.** All LLM calls go to **Qwen models via Qwen Cloud / DashScope** — endpoint
`https://dashscope-intl.aliyuncs.com`. Model right-sizing per task:

| Qwen model | Role in the agent |
|---|---|
| `qwen3.7-max` | Flagship reasoner — the ReAct analysis/strategy agent |
| `qwen-flash` | Fast judge — NLI verify / self-critique (~0.5s vs ~23s, no quality loss) |
| `qwen-plus` | Legal lookup Q&A (`/ask`) |
| `text-embedding-v4` | Embeddings for hybrid retrieval |
| `qwen3-rerank` | Cross-encoder reranking (opt-in) |
| `qwen3.7-plus` | Multimodal OCR for scanned/image contracts |

**Deploy**: Docker (Caddy HTTPS + FastAPI + Redis), `alembic upgrade head` on start against
**CockroachDB** (deploy target: AWS ECS + S3 for this track). Embeddings + agent memory persist as
CockroachDB `VECTOR`. The hexagonal `LLMPort`/`MemoryPort` mean swapping the LLM provider or the database
is one line in `config/container.py`.

## 🧠 Agentic memory — remembers each counterparty

Every negotiation outcome becomes an **episode** the agent recalls in later deals with the *same
counterparty* (*"they accepted an 8% penalty cap last time"*). It's written **async** (off the response
hot-path) and recalled as **advisory** context injected into the negotiation prompt — never as legal
authority, so measured accuracy is unchanged whether the flag is on or off. Strictly **org-isolated**,
with **cascade right-to-erasure** (PDPD/GDPR) and a similarity **noise-floor** so off-topic queries
recall nothing.

Two higher-order behaviours make it more than a log: **consolidation** collapses many episodes for a
counterparty into one compact *profile* (distilled "who they are", not a noisy list), and **bi-temporal**
memory means when a counterparty's stance changes the old episode is marked superseded — *kept for
provenance, never deleted* — so recall returns the **current** position while `include_history` exposes the
timeline (point-in-time / audit).

Backed by a swappable **`MemoryPort`** (hexagonal): SQLite/Postgres use in-RAM cosine; **CockroachDB**
uses native `VECTOR` columns + `CREATE VECTOR INDEX` (C-SPANN) for in-database ANN recall — the backend
changes in one line, the domain never does. Exposed over **MCP** as `recall_memory`.

```bash
# verify a CockroachDB cluster supports vector search (v25.4+):
CRDB_URL="postgresql://<user>:<pass>@<host>:26257/defaultdb?sslmode=verify-full" \
  uv run python -m scripts.crdb_verify
# enable (.env): AGENTIC_MEMORY=1 and COCKROACHDB_URL=<same connection string>
# recall quality gate (2 backends): Recall@k / MRR / org-isolation / noise / supersede / consolidation
uv run python -m evaluation.memory_eval
```

## Run with Docker

```bash
make up      # build + run app (http://localhost:8000) + Postgres + Redis, auto-migrates
make logs    # tail logs   ·   make down (stop)   ·   make help (all commands)
```

## Run locally with [uv](https://docs.astral.sh/uv/)

```bash
uv sync
cp .env.example .env          # optional: add QWEN_API_KEY for real analysis
uv run uvicorn app:app --reload          # → http://localhost:8000/docs
uv run pytest                            # full offline test suite
uv run ruff check .                      # lint
```

## Key endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/analyze` | Review a contract. `lang=en`/`vi` + bargaining position (`leverage`/`urgency`/`relationship`/`alternatives`) → risks, fallbacks, strategy, trace, `execution_summary`. Long docs: `async_mode=true` → poll `/analyze/result/{id}`. |
| GET | `/runs` | **Agent activity feed** (AI-Native evidence): tool calls, risks, escalations per run. |
| POST | `/ask` | Grounded legal Q&A → answer citing in-force Article/Clause + sources. |
| POST | `/counter` | Draft a bilingual VN/EN **counter-clause** for a risky term. |
| POST | `/negotiate` | **Stateful multi-round negotiation**: deal context + counterparty reply (+ prior `state`) → assessment · next-round strategy · bilingual reply · status · updated **concession ledger** (secured/conceded/red-lines carried across rounds) · **concession ladder** (proposed trades, red-line-screened) · `walk_away_recommended` (fires when a red-line is blocked and a BATNA exists). Tactics are biased by the org's real win-rate flywheel. |
| POST | `/monitor/run` | **Autopilot**: scan newly-issued laws (`since`) → which contracts are affected → digest. |
| POST | `/monitor/feedback` | Mark a monitor alert as a false alarm → suppressed next run (self-tuning). |
| GET | `/graph/{doc_id}` · `/latest/{doc_id}` · `/articles-changed/{doc_id}` | Document relationship graph / latest version / amended articles (TVPL-style). |
| GET | `/impact/{doc_id}` | Regulatory-change intelligence: which stored contracts a new law affects (article-level). |
| POST | `/escalate` | Hand a case to a **lawyer** channel (human checkpoint reject). |
| GET | `/trust` · `/trust.json` | Published reliability: methodology + eval metrics. |
| — | MCP | `make mcp` exposes `analyze_contract` via Model Context Protocol (Qwen-Agent / Claude / IDE). |

(Full endpoint list, channels, security, persistence: [`README.vi.md`](README.vi.md).)

## Open-core

The **engine is MIT-licensed and fully open** (this repo) — it runs end-to-end on the included public
legal corpus + a 12-situation sample fallback matrix. Proprietary depth (party-aware tactic library,
lawyer-verified evaluation set, deal-outcome flywheel data) layers on at deploy time via a private
overlay and is **not** in this repo. See [`docs/OPEN-CORE.md`](docs/OPEN-CORE.md). License: [`LICENSE`](LICENSE) (MIT).

## Requirements
- Python ≥ 3.11 · Qwen API (primary LLM; hexagonal `LLMPort` → add a 2nd provider in one line)
- Runs fully offline in **stub mode** without any API key.
