# Architecture Diagram — Legal Guard PH

Sơ đồ kiến trúc cho Qwen Hackathon (track Autopilot Agent). Render trực tiếp trên GitHub;
chụp màn hình để nộp Devpost. Phần **Alibaba Cloud** được tô đậm (yêu cầu bắt buộc của track).

## Tổng quan hệ thống

```mermaid
flowchart TB
    subgraph users["👤 Người dùng"]
        U1["Web UI /app"]
        U2["Slack bot"]
        U3["Zalo OA"]
    end

    subgraph alibaba["☁️ ALIBABA CLOUD ECS (deploy bắt buộc)"]
        CADDY["Caddy — HTTPS / TLS"]
        subgraph app["FastAPI — Hexagonal (Ports & Adapters)"]
            IN["Inbound adapters<br/>http · channels · mcp"]
            subgraph core["Domain core (không phụ thuộc hạ tầng)"]
                AGENT["🤖 Agent ReAct loop<br/>tool-calling"]
                TOOLS["Tools: search_kb ·<br/>flag_risk · propose_fallback ·<br/>request_human_review"]
                ANALYSIS["AnalysisService<br/>chunk · verify 2 lớp · audit"]
                CHECK["⚖️ Human checkpoint"]
            end
            OUT["Outbound adapters<br/>qwen · kb · parser"]
        end
    end

    subgraph qwencloud["☁️ QWEN CLOUD / DashScope (Alibaba)"]
        QMAX["qwen3.7-max<br/>(reasoning agent)"]
        QFLASH["qwen-flash<br/>(judge: NLI/verify/tóm tắt)"]
        QEMB["text-embedding-v4<br/>(retrieval)"]
        QVL["qwen3.7-plus<br/>(OCR scan/ảnh)"]
    end

    subgraph ext["Dịch vụ ngoài"]
        NEON["Neon Postgres<br/>(cases · outcomes)"]
        UP["Upstash Redis<br/>(chat session)"]
    end

    KB[("📚 Knowledge Base<br/>fallback matrix<br/>luật VN")]

    U1 & U2 & U3 -->|HTTPS| CADDY --> IN --> ANALYSIS
    ANALYSIS --> AGENT --> TOOLS --> OUT
    ANALYSIS --> CHECK
    OUT -->|reasoning + tool-call| QMAX
    OUT -->|embed| QEMB
    OUT -->|OCR| QVL
    OUT --> KB
    OUT -->|NLI/verify/summary| QFLASH
    ANALYSIS --> NEON
    IN --> UP

    style alibaba fill:#fff0e6,stroke:#ff6a00,stroke-width:3px
    style qwencloud fill:#fff0e6,stroke:#ff6a00,stroke-width:3px
    style CHECK fill:#e6f7ed,stroke:#198754,stroke-width:2px
    style AGENT fill:#e6f0ff,stroke:#0d6efd,stroke-width:2px
```

## Luồng phân tích (sequence)

```mermaid
sequenceDiagram
    actor User as SME
    participant App as FastAPI (ECS)
    participant Agent as Agent loop
    participant Qwen as Qwen Cloud
    participant KB as Knowledge Base
    participant Rev as Reviewer (người)

    User->>App: Gửi hợp đồng (PDF/scan/text)
    App->>Qwen: OCR nếu scan (qwen3.7-plus)
    App->>Agent: Phân tích (theo vị thế đàm phán)
    loop ReAct (mỗi vòng = 1 tool-call)
        Agent->>Qwen: reasoning (qwen3.7-max)
        Agent->>KB: search_legal_knowledge (RAG)
        Agent->>Agent: flag_risk · propose_fallback
    end
    Agent->>App: rủi ro + fallback + chiến lược + trace
    App->>App: verify 2 lớp (clause-existence + LLM-judge)
    App-->>Rev: ⚖️ Human checkpoint (khóa english_reply)
    Rev->>App: Approve / Reject
    App->>User: Báo cáo (mở khóa câu gửi đối tác)
```

## Điểm nhấn cho giám khảo Autopilot Agent
- **Agent tự động end-to-end**: parse → RAG → flag risk → propose fallback → strategy, qua **tool-calling** thật (không phải prompt đơn).
- **Human-in-the-loop checkpoint**: khuyến nghị bị khóa tới khi người duyệt — đúng tiêu chí track.
- **Chạy trên Alibaba Cloud**: ECS (host) + Qwen Cloud/DashScope (qwen3.7-max reasoning, text-embedding-v4, qwen3.7-plus OCR).
- **Xử lý input mơ hồ**: OCR ảnh scan, adaptive routing, chunk hợp đồng dài.
