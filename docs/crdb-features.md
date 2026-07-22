# CockroachDB tools used — Legal Guard

CockroachDB × AWS "Build with Agentic Memory" requires **at least 2 of 4** CockroachDB tools.
Legal Guard uses **all 4** (verified live on a CockroachDB Cloud **Basic** cluster, `v26.2.1`, AWS `ap-southeast-1`).

| # | CockroachDB tool | Status | Where |
|---|---|---|---|
| 1 | **Distributed Vector Indexing (C-SPANN)** | ✅ used, verified live | agent memory + KB retrieval |
| 2 | **ccloud CLI (Agent-Ready)** | ✅ used, verified live | `scripts/crdb_ops.py` |
| 3 | **Cloud Managed MCP Server** | ✅ connected (OAuth, Basic tier) | `.mcp.json` (Claude Code) |
| 4 | **Agent Skills Repo** | ✅ used | `cockroachlabs/cockroachdb-skills` (34 skills) |

## 1. Distributed Vector Indexing (C-SPANN)
Agent memory **and** knowledge-base embeddings are stored in CockroachDB `VECTOR` columns with
`CREATE VECTOR INDEX` (C-SPANN) and queried by ANN (`<=>` cosine distance) **in-database**.
- `legalguard/adapters/outbound/sql_memory_store.py` — `memory_episodes.vec` + per-counterparty ANN recall.
- `legalguard/adapters/outbound/embedding_store.py` — `kb_vectors.vec` + `search_ann`.
- Transactional data (cases/outcomes/feedback) + vector data live in the **same distributed DB**.
- Verify: `uv run python -m scripts.crdb_verify` (connect + VECTOR + CREATE VECTOR INDEX + `<=>`).

## 2. ccloud CLI (Agent-Ready)
Official CLI, JSON output on every command → scriptable ops (deploy + monitoring) with no console.
- `scripts/crdb_ops.py` wraps ccloud: `clusters` / `info` / `connstring` (deploy) / `health` (CI/monitor).
- Setup: `brew install cockroachdb/tap/ccloud` → `ccloud auth login`.
- Verify: `uv run python -m scripts.crdb_ops health <cluster>` → `{"healthy": true, "version": "v26.2.1", ...}`.

## 3. Cloud Managed MCP Server (connected — Basic tier ✅)
Managed MCP endpoint lets the agent inspect schema / run read-only analytical queries against the cluster.
Endpoint `https://cockroachlabs.cloud/mcp`; read-only (`mcp:read`) by default, blocks `DROP`/`TRUNCATE`.
**Connected via OAuth on a Basic-tier cluster** — tools available to Claude Code:
`list_databases`, `list_tables`, `get_table_schema`, `select_query`, `explain_query`, `show_running_queries`, …
Config: **`.mcp.json.example`** (needs the `mcp-cluster-id` header).

**Enable (OAuth — recommended):**
```shell
claude mcp add cockroachdb-cloud https://cockroachlabs.cloud/mcp \
  --transport http --header "mcp-cluster-id: <cluster-id>"      # ccloud cluster list -o json → .id
```
then in Claude Code: `/mcp` → `cockroachdb-cloud` → **Authenticate** → grant read → **Authorize**.

**Enable (service-account API key — non-interactive):** create a service account + API key with role
**Cluster Operator** (`ccloud service-account` / Console), add header
`Authorization: Bearer <api-key>` alongside `mcp-cluster-id`.

Complements the app's own MCP server (`legalguard/adapters/inbound/mcp_server.py`:
`analyze_contract` / `lookup_law` / `recall_memory`).

## 4. Agent Skills Repo (bonus)
CockroachDB's open-source Agent Skills (`cockroachlabs/cockroachdb-skills`, Apache-2.0) — machine-executable
CRDB expertise (SQL, observability, security, capacity, MOLT migration…). Portable across agents (Claude
Code, Cursor, …) via the Agent Skills Specification.
- Install: `npx skills add cockroachlabs/cockroachdb-skills` (lands in `.agents/skills/`, symlinked to
  `.claude/skills/`; gitignored as a third-party artifact — reproduce with one command).
- Used for CRDB operations during development/deploy, e.g. `cockroachdb-sql`, `monitoring-background-jobs`,
  `managing-cluster-capacity`, `molt-fetch`.

## AWS
≥1 AWS service: **Amazon ECS** (app) + **S3** (artifacts). CockroachDB Cloud cluster runs on AWS.
