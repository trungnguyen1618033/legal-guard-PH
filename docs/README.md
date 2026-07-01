# Tài liệu — Legal Guard PH

Bản đồ toàn bộ tài liệu dự án. Bắt đầu từ [`/README.md`](../README.md) (quickstart) rồi tới đây.

## 📊 Chiến lược & Kinh doanh
| Tài liệu | Nội dung |
|---|---|
| [internal/legal-guard.md](internal/legal-guard.md) 🔒 | Kế hoạch dự án: 2 hackathon (số liệu đã verify), mục tiêu giải, lộ trình, kiến trúc §5b |
| [internal/phan-tich-kha-thi.md](internal/phan-tich-kha-thi.md) 🔒 | Phân tích khả thi + góc nhìn giám khảo + mục tiêu XPRIZE + mốc Go/No-Go 30/6 |
| [product-overview.md](product-overview.md) | **Giới thiệu sản phẩm cho khách hàng**: tính năng đầy đủ · điểm khác biệt · an toàn dữ liệu (không có giá) |
| [market-analysis.md](market-analysis.md) | Đối thủ · định vị · nỗi đau SME · Luật AI VN (tailwind) |
| [moat.md](moat.md) | Chiến lược độc quyền: data flywheel kết quả đàm phán · workflow · compliance |
| [internal/pitch-presell.md](internal/pitch-presell.md) 🔒 | Bộ pitch pre-sell: ICP · kịch bản gọi · bảng giá · xử lý từ chối |
| [internal/legal-search-expansion.md](internal/legal-search-expansion.md) 🔒 | **Mở rộng: tra cứu+tổng hợp luật VN bằng AI** · tiềm năng/use case · embedding VN · RAG dẫn-chiếu-chéo (citation graph, closure, temporal) · roadmap |
| [internal/legal-search-tech-process.md](internal/legal-search-tech-process.md) 🔒 | **Kỹ thuật/công nghệ/quy trình** RAG luật VN: ingestion ETL (dataset mở vbpl.vn) · serving stack (pgvector + CTE + self-host reranker) · eval harness (golden set, Recall@k/closure/in-force) · lộ trình theo mốc |
| [internal/moat-and-differentiation.md](internal/moat-and-differentiation.md) 🔒 | **Moat & "độc lạ duy nhất"**: cái gì commoditize vs moat thật · khe hở duy nhất (đàm phán theo vị thế) · 3 góc định vị · việc cần làm theo ROI (NLI verify, living flywheel, system-of-record, proactive compliance) |

> 🔒 = tài liệu nội bộ trong `docs/internal/` — **gitignore, không có trong repo public** (chiến lược thi đấu, giá, lead).

## 🏗️ Kỹ thuật
| Tài liệu | Nội dung |
|---|---|
| [architecture.md](architecture.md) | Hexagonal (Ports & Adapters) · agentic RAG · multi-tenancy 2 trục · kỹ thuật chất lượng AI |
| [architecture.en.md](architecture.en.md) | 🌐 EN — agent/autopilot showcase cho giám khảo quốc tế (ReAct · self-critique · /runs evidence · right-sizing) |
| [OPEN-CORE.md](OPEN-CORE.md) | Ranh giới Public (MIT) vs Private (moat) — engine mở, dữ liệu sâu private overlay (song ngữ) |
| [advisory-flow.md](advisory-flow.md) | Luồng tư vấn thật: vị thế đàm phán (BATNA/leverage) → ưu tiên giữ/nhượng → chiến lược |
| [conversation.md](conversation.md) | Chat session/memory: working memory + deal context · intent routing · follow-up |
| [slack-guide.md](slack-guide.md) | Cài đặt bot Slack (admin): app/scopes/events · env · troubleshooting |
| [slack-handbook.md](slack-handbook.md) | Sổ tay người dùng Slack: 8 use case (soát HĐ · tra cứu luật · point-in-time · feedback) · routing · FAQ |
| [data-model.md](data-model.md) | Persistence SQLAlchemy (SQLite→Postgres) · Alembic · bảng `cases` |
| [security.md](security.md) | Threat model · cô lập theo công ty · redaction PII · prompt-injection · compliance |
| [deployment.md](deployment.md) | Triển khai & scale trên Alibaba Cloud · topology · tiers · CI/CD · bottlenecks |
| [deploy-ecs-selfhosted.md](deploy-ecs-selfhosted.md) | **Deploy ECS self-contained** (app+Caddy+PG+Redis 1 VM, DuckDNS, $0 ngoài) + backup DB + log/debug + SSH tunnel chọc DB từ local |
| [deploy-ecs.md](deploy-ecs.md) | Deploy ECS + HTTPS bản dùng **Neon + Upstash** (DB/Redis ngoài) |
| [architecture-diagram.md](architecture-diagram.md) | Sơ đồ kiến trúc (Mermaid) cho Devpost — tô đậm Alibaba Cloud |
| [architecture-diagram.en.md](architecture-diagram.en.md) | 🌐 EN — sơ đồ + sequence cho giám khảo quốc tế (đúng deploy hiện tại + đủ 6 model Qwen) |
| [DEVPOST.md](DEVPOST.md) | 🌐 EN — bản nộp Devpost (Inspiration/What/How/Challenges/Next) + block Qwen+Alibaba + script video |
| [capacity.md](capacity.md) | Ước tính năng lực: nghẽn ở quota LLM · ~8–10k công ty/account standard · đòn bẩy |
| [knowledge_base/_README.md](../knowledge_base/_README.md) | Thiết kế & độ phủ KB · cách mở rộng tình huống/quốc gia |

## 🚀 Phát triển & Vận hành
| Tài liệu | Nội dung |
|---|---|
| [/README.md](../README.md) | **English-first** (cửa chính cuộc thi quốc tế) — agent framing · quickstart · endpoints · open-core |
| [/README.vi.md](../README.vi.md) | Bản tiếng Việt đầy đủ (endpoints chi tiết · channels · security · persistence) |
| [/CLAUDE.md](../CLAUDE.md) | Hướng dẫn cho Claude Code: lệnh, kiến trúc, kỹ thuật AI, bảo mật |

## Trạng thái dự án (25/6/2026)
- ✅ MVP chạy được (221 test, lint sạch), offline qua stub.
- ✅ Agentic RAG hiện đại + bảo mật + multi-tenancy 2 trục + persistence Postgres-ready + Docker.
- ✅ **Tra cứu luật VN**: chunk Điều/Khoản + NFC, lọc hiệu lực + point-in-time, citation-closure
  document-aware (xuyên Luật→NĐ→TT), cross-encoder rerank (opt-in), **NLI entailment verify**,
  eval harness (`evaluation/legal_eval.py`), ingestion dataset mở (`ingestion/hf_to_kb.py`).
- ✅ **Moat đã dựng**: đàm phán theo vị thế + **điều khoản phản-đề song ngữ** (`/counter`) ·
  **regulatory change intel** article-level + cảnh báo Slack/Zalo (`/impact`) · **system-of-record
  dashboard** (`/dashboard`, `/insights/dashboard`) · **living flywheel** feedback→golden
  (`evaluation/feedback_to_golden.py`) · reason-then-format structured output.
- ✅ Hạ tầng deploy Alibaba Cloud ECS SẴN SÀNG (Dockerfile · compose.prod · Caddy auto-TLS · `deploy-ecs.md`).
- ✅ Tập trung Qwen hackathon (gác XPRIZE). Chờ `QWEN_API_KEY` để chạy thật + deploy.
- ⬜ Còn lại (cần hạ tầng/cost): reranker/embedding pháp lý VN **self-host** (GPU) · **hard-negative mining** từ feedback (training).
