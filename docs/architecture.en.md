# Architecture & Agent Design (EN)

> English technical overview for reviewers. Vietnamese deep-dive: [`architecture.md`](architecture.md).
> This document focuses on **what makes it an agent** and **how it stays grounded**.

## 1. Hexagonal core (Ports & Adapters)

The business logic in `legalguard/domain/` never imports a framework or a vendor SDK. It defines
**ports** (interfaces) — `LLMPort`, `KnowledgeBasePort`, `DocumentParserPort` — and the
`adapters/outbound/` layer implements them (Qwen, file-based KB, PDF/DOCX/OCR parser).
`config/container.py` is the single composition root. Consequences:

- Swapping the LLM provider, or file-KB ↔ vector DB, is **one line** in the container; the core is untouched.
- The whole pipeline runs **offline in stub mode** (LLM adapters return labelled placeholder text), so
  the agent loop, tools, verification and HTTP surface are all testable without any API key.

## 2. The agent: a ReAct tool-calling loop

`domain/agent.py` runs a bounded **ReAct loop** (default ≤6 iterations). Each turn the LLM decides which
tool(s) to call; the dispatcher runs them and feeds observations back. Tools (`domain/tools.py`):

| Tool | Effect |
|---|---|
| `search_legal_knowledge` | Retrieve grounding passages from the legal KB (hybrid RAG). |
| `flag_risk` | Record a risk (reason-first schema: the model must state *why* before severity/priority). |
| `propose_fallback` | Record a position-aware compromise tactic + a ready-to-send bilingual reply. |
| `request_human_review` | Signal that an expert must approve before use. |

Every step is captured as a `TraceStep {step, tool, arguments, observation}`. The agent handles
**ambiguous input** (raw pasted text, scanned PDFs via Qwen-VL OCR, a free-form bargaining position) and
emits structured output via **reason-then-format** — it reasons in prose first, then fills the decision
fields, which measurably reduces hallucinated severities.

## 3. Self-critique (the agent checks its own work)

After the loop, `domain/verification.py::verify_risks` runs a two-layer critique:

1. **Evidence existence** (free, language-agnostic): the quote a risk cites must actually appear in the
   contract; otherwise the risk is marked `verified=False`.
2. **NLI entailment** (one batched judge call): does the retrieved law *support* each remaining risk?
   Conservative — a risk is demoted only on an explicit "NO"; uncertainty is kept and sent to a human.

Any unverified risk forces `needs_human_review`. The same NLI machinery runs in reverse
(`nli_contradicts`) to escalate an *unfavorable* clause to *illegal* only when it genuinely contradicts
an in-force article — never on a guess.

## 4. Proactive autopilot + a feedback loop

`POST /monitor/run` is the "works while you sleep" path: it finds laws effective since a date, computes
which stored contracts cite documents those laws amend/replace/guide (article-level, to cut false
positives), and emits a digest (optionally pushed to Slack/Zalo by a daily cron). It **self-tunes** —
`POST /monitor/feedback` records a "false alarm", and `filter_affected` suppresses that pair on the next
run, so the autopilot gets quieter and more precise over time.

## 5. Human-in-the-loop

The outbound message to the counterparty is **locked** until a reviewer approves it in the UI. Reject →
`POST /escalate` routes the case to a configured lawyer channel. This is both a track requirement and a
liability guardrail: the AI screens and drafts; a human authorizes.

## 6. AI-Native evidence (make the agent visible)

- `AnalysisResult.execution_summary` — per-run tool-call breakdown (searches / risks / fallbacks /
  reviews requested), so reviewers see *how much* the agent did.
- `GET /runs` — an org-scoped feed of recent runs (tool calls, risks, unverified count, escalations):
  proof the agent runs continuously and makes decisions.
- `domain/observability.py` — optional Langfuse traces/events (`LANGFUSE_*`); NoOp when unset.

## 7. Grounding & retrieval quality

- **Citation grounding**: each risk/fallback carries a deterministic `legal_basis = "file#Article N: …"`.
- **Hybrid retrieval**: BM25 (Okapi) + embeddings fused by RRF, with optional cross-encoder rerank.
- **In-force filtering**: only returns law valid *at the relevant point in time* (status + effective/
  expiry dates), so the agent never cites repealed law — a safety feature, not a bug.
- **Citation closure**: follows cross-references to pull the related articles in the correct document.

## 8. Right-sizing & resilience

Hard reasoning (analysis, strategy) uses the flagship **`qwen3.7-max`**; cheap yes/no checks (NLI verify)
use **`qwen-flash`** — measured ~23s → ~0.5s with matching verdicts; legal lookup uses **`qwen-plus`**;
retrieval uses **`text-embedding-v4`** (+ opt-in **`qwen3-rerank`**); OCR uses **`qwen3.7-plus`**. All via
Qwen Cloud / DashScope (Alibaba Model Studio). Post-agent verify ∥ summarize ∥ ground run in parallel.
Any provider failure degrades to a typed `LLMError` and a safe fallback rather than a crash.

## 9. Tenancy & isolation

Two axes: **Tenant = jurisdiction** (selects `knowledge_base/<CC>/`) and **Organization = company**
(data isolation by `org_id` + a private KB overlay at `knowledge_base/_orgs/<org_id>/`). API-key auth
scopes every query to one org; PII is redacted before it reaches the LLM, logs, or storage.
