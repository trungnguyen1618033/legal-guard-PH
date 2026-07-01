# Architecture Diagram (EN) — Legal Guard

Diagram for the Qwen Cloud Hackathon (Autopilot Agent track). Renders on GitHub; screenshot for the
Devpost submission. **Alibaba Cloud** blocks are highlighted (a track requirement). Vietnamese version:
[`architecture-diagram.md`](architecture-diagram.md).

## System overview

```mermaid
flowchart TB
    subgraph users["👤 Users"]
        U1["Web UI /app · /lookup · /dashboard"]
        U2["Slack bot"]
        U3["Zalo OA"]
    end

    subgraph alibaba["☁️ ALIBABA CLOUD ECS (required deploy)"]
        CADDY["Caddy — HTTPS / TLS"]
        subgraph app["FastAPI — Hexagonal (Ports & Adapters)"]
            IN["Inbound adapters<br/>http · channels · MCP"]
            subgraph core["Domain core (no infra deps)"]
                AGENT["🤖 Agent ReAct loop<br/>(tool-calling)"]
                TOOLS["Tools: search_kb ·<br/>flag_risk · propose_fallback ·<br/>request_human_review"]
                ANALYSIS["AnalysisService<br/>2-layer verify · self-critique · audit"]
                CHECK["⚖️ Human checkpoint"]
                AUTOPILOT["🛰️ Autopilot monitor<br/>(scan new laws → impact)"]
            end
            OUT["Outbound adapters<br/>qwen · gemini · KB · parser"]
        end
        PG[("Postgres<br/>cases · outcomes · kb_vectors")]
        REDIS[("Redis<br/>chat session")]
    end

    subgraph qwencloud["☁️ QWEN CLOUD / DashScope (Alibaba Model Studio)"]
        QMAX["qwen3.7-max<br/>reasoning agent"]
        QFLASH["qwen-flash<br/>NLI verify (judge)"]
        QPLUS["qwen-plus<br/>legal lookup"]
        QEMB["text-embedding-v4<br/>retrieval"]
        QRR["qwen3-rerank<br/>cross-encoder"]
        QVL["qwen3.7-plus<br/>OCR (scan/image)"]
    end

    GEM["Gemini 2.5-flash<br/>(≥1 call — XPRIZE rule)"]
    KB[("📚 Knowledge Base<br/>in-force VN law + fallback matrix<br/>+ private overlay _orgs/")]

    U1 & U2 & U3 -->|HTTPS| CADDY --> IN --> ANALYSIS
    ANALYSIS --> AGENT --> TOOLS --> OUT
    ANALYSIS --> CHECK
    IN --> AUTOPILOT --> ANALYSIS
    OUT -->|reasoning + tool-call| QMAX
    OUT -->|NLI verify| QFLASH
    OUT -->|lookup| QPLUS
    OUT -->|embed| QEMB
    OUT -->|rerank| QRR
    OUT -->|OCR| QVL
    OUT --> KB
    OUT -->|summary| GEM
    ANALYSIS --> PG
    IN --> REDIS

    style alibaba fill:#fff0e6,stroke:#ff6a00,stroke-width:3px
    style qwencloud fill:#fff0e6,stroke:#ff6a00,stroke-width:3px
    style CHECK fill:#e6f7ed,stroke:#198754,stroke-width:2px
    style AGENT fill:#e6f0ff,stroke:#0d6efd,stroke-width:2px
    style AUTOPILOT fill:#e6f0ff,stroke:#0d6efd,stroke-width:2px
```

## Analysis flow (sequence)

```mermaid
sequenceDiagram
    actor User as SME
    participant App as FastAPI (ECS)
    participant Agent as Agent loop
    participant Qwen as Qwen Cloud
    participant KB as Knowledge Base
    participant Rev as Reviewer (human)

    User->>App: Send contract (PDF / scan / text)
    App->>Qwen: OCR if scanned (qwen3.7-plus)
    App->>Agent: Analyze (with bargaining position)
    loop ReAct (each step = one tool-call)
        Agent->>Qwen: reasoning (qwen3.7-max)
        Agent->>KB: search_legal_knowledge (hybrid RAG)
        Agent->>Agent: flag_risk · propose_fallback
    end
    Agent->>App: risks + fallbacks + strategy + trace + execution_summary
    App->>Qwen: self-critique / NLI verify (qwen-flash)
    App-->>Rev: ⚖️ Human checkpoint (english_reply locked)
    Rev->>App: Approve / Reject → escalate
    App->>User: Report (unlocks message to counterparty)
```

## Why it fits the Autopilot Agent track
- **End-to-end autonomy** via real **tool-calling** (parse → RAG → flag risk → propose fallback → strategy), not a single prompt.
- **Self-critique**: the agent verifies its own findings (evidence-existence + NLI) before returning.
- **Proactive autopilot**: `/monitor/run` scans newly-issued laws → which past contracts are affected → self-tunes on false-alarm feedback ("works while you sleep").
- **Human-in-the-loop**: the message to the counterparty stays locked until a human approves.
- **AI-Native evidence**: `GET /runs` + per-run `execution_summary` expose the agent's tool calls & decisions.
- **Runs on Alibaba Cloud**: ECS host + Qwen Cloud/DashScope (Model Studio) for all LLM calls.
