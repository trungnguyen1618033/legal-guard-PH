# Model portability — swapping the LLM (beyond Qwen)

Legal Guard is **model-agnostic by architecture** (hexagonal). The domain depends only on the `LLMPort`
interface (`legalguard/domain/ports.py`): `complete()`, `chat(tools=…)`, `embed()`. The default adapter
`QwenAdapter` speaks the **OpenAI chat-completions format** (`{base_url}/chat/completions`) over a configurable
`base_url` — so most providers need **zero code change**.

## The 6 LLM roles (right-sizing) — all env-configurable
| Role | Env (default) | Used for |
|---|---|---|
| reasoner (flagship) | `QWEN_MODEL` = qwen3.7-max | agent analysis, negotiation |
| judge | `QWEN_FAST_MODEL` = qwen-flash | NLI verify, relevance gate (yes/no) |
| lookup | `QWEN_LOOKUP_MODEL` = qwen-plus | legal Q&A |
| fast-review | `QWEN_FAST_REVIEW_MODEL` = qwen-flash | quick contract scan |
| counter | `QWEN_COUNTER_MODEL` = qwen-plus | draft counter-clauses |
| embeddings | `QWEN_EMBED_MODEL` = text-embedding-v4 | KB + memory vectors |
All are built from `QwenAdapter(QWEN_API_KEY, QWEN_BASE_URL, <model>)` in `config/container.py`.

## Path A — any **OpenAI-compatible** provider → change ENV only (no code)
Point `QWEN_BASE_URL` + `QWEN_API_KEY` + the model names at the provider. Works with OpenAI, Azure OpenAI,
OpenRouter, Together, Groq, DeepSeek, Fireworks, and local **vLLM / Ollama / LM Studio** (OpenAI mode).

```bash
# Example: OpenAI
QWEN_API_KEY=sk-...
QWEN_BASE_URL=https://api.openai.com/v1
QWEN_MODEL=gpt-5
QWEN_FAST_MODEL=gpt-5-mini
QWEN_LOOKUP_MODEL=gpt-5-mini
QWEN_EMBED_MODEL=text-embedding-3-large

# Example: local, no cloud (vLLM / Ollama OpenAI-compatible)
QWEN_BASE_URL=http://localhost:11434/v1
QWEN_MODEL=llama3.1:70b
QWEN_API_KEY=ollama            # any non-empty string
```
Nothing else changes — the agent loop, tool-calling, verification, and memory all keep working.

> **Verified (2026-07-22):** setting `QWEN_BASE_URL=https://api.openai.com/v1` + `QWEN_MODEL=gpt-5`
> `QWEN_FAST_MODEL=gpt-5-mini` → the wired reasoner/judge use those models against
> `https://api.openai.com/v1/chat/completions` with **no code change** (confirmed via `build_service()`).

## Path B — **native** (non-OpenAI) API → add one adapter (~1 file)
For Anthropic Messages API or Google Gemini native SDK, add an adapter implementing `LLMPort`
(`complete`/`chat`/`embed`) next to `qwen.py`, then swap one line in `config/container.py` (or gate on an
`LLM_PROVIDER` env). The domain and everything above are untouched — that's the point of the port.

## Qwen-specific extras — graceful degradation
These are optional and **fail safe** if the new provider lacks them:
- **Embeddings** (`QWEN_EMBED_MODEL`): use the provider's embeddings endpoint; if absent, `embed()` returns
  `None` → retrieval falls back to lexical **BM25** (hybrid still works, lower recall).
- **Reranker** (`QWEN_RERANK_MODEL` = qwen3-rerank): optional cross-encoder; disable with `RERANK_ENABLED=0`
  or point `RERANK_URL` at a self-hosted TEI reranker (`HttpReranker`).
- **Vision/OCR** (`QWEN_VL_MODEL`): for scanned contracts; without a vision model, text-PDF/DOCX still parse.

## Why this matters
- **No lock-in**: swap Qwen → OpenAI/local in minutes for cost, latency, or compliance reasons.
- **AWS-ready**: Bedrock AgentCore Runtime is model-agnostic — this design runs any of the above on it.
- **Testability**: tests run offline in stub mode (`available=False` → deterministic `[..._STUB]`), no provider needed.
