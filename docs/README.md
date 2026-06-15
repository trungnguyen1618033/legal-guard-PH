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

> 🔒 = tài liệu nội bộ trong `docs/internal/` — **gitignore, không có trong repo public** (chiến lược thi đấu, giá, lead).

## 🏗️ Kỹ thuật
| Tài liệu | Nội dung |
|---|---|
| [architecture.md](architecture.md) | Hexagonal (Ports & Adapters) · agentic RAG · multi-tenancy 2 trục · kỹ thuật chất lượng AI |
| [advisory-flow.md](advisory-flow.md) | Luồng tư vấn thật: vị thế đàm phán (BATNA/leverage) → ưu tiên giữ/nhượng → chiến lược |
| [conversation.md](conversation.md) | Chat session/memory: working memory + deal context · intent routing · follow-up |
| [slack-guide.md](slack-guide.md) | Cài đặt bot Slack (admin): app/scopes/events · env · troubleshooting |
| [slack-handbook.md](slack-handbook.md) | Sổ tay người dùng Slack: tính năng · 5 use case từng bước · đọc kết quả · FAQ |
| [data-model.md](data-model.md) | Persistence SQLAlchemy (SQLite→Postgres) · Alembic · bảng `cases` |
| [security.md](security.md) | Threat model · cô lập theo công ty · redaction PII · prompt-injection · compliance |
| [deployment.md](deployment.md) | Triển khai & scale trên Alibaba Cloud · topology · tiers · CI/CD · bottlenecks |
| [capacity.md](capacity.md) | Ước tính năng lực: nghẽn ở quota LLM · ~8–10k công ty/account standard · đòn bẩy |
| [knowledge_base/_README.md](../knowledge_base/_README.md) | Thiết kế & độ phủ KB · cách mở rộng tình huống/quốc gia |

## 🚀 Phát triển & Vận hành
| Tài liệu | Nội dung |
|---|---|
| [/README.md](../README.md) | Quickstart (uv + Docker) · endpoints · kiến trúc tóm tắt |
| [/CLAUDE.md](../CLAUDE.md) | Hướng dẫn cho Claude Code: lệnh, kiến trúc, kỹ thuật AI, bảo mật |

## Trạng thái dự án (10/6/2026)
- ✅ MVP chạy được (62 test, lint sạch), offline qua stub.
- ✅ Agentic RAG hiện đại + bảo mật + multi-tenancy 2 trục + persistence Postgres-ready + Docker.
- ⏳ Chờ `QWEN_API_KEY` để chạy thật + deploy Alibaba Cloud.
- 🔴 Ưu tiên cao nhất (XPRIZE): bán hàng/khách thật trước mốc Go/No-Go 30/6.
