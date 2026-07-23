# Tài liệu Legal Guard — mục lục

> Tài liệu công khai (engine MIT). Chiến lược/moat nội bộ nằm ở `docs/internal/` (gitignored, không public).
> Bản song ngữ: `*.md` = tiếng Việt · `*.en.md` = English.

## Bắt đầu
| Tài liệu | Nội dung |
|---|---|
| [product-overview.md](product-overview.md) | Sản phẩm là gì, dùng cho ai, giá trị cốt lõi |
| [../README.md](../README.md) · [../README.vi.md](../README.vi.md) | Giới thiệu + quickstart (EN / VI) |
| [OPEN-CORE.md](OPEN-CORE.md) | Ranh giới open-core: phần MIT công khai vs moat riêng |

## Kiến trúc & thiết kế
| Tài liệu | Nội dung |
|---|---|
| [architecture.md](architecture.md) · [architecture.en.md](architecture.en.md) | Hexagonal (ports & adapters), agent design |
| [architecture-diagram.md](architecture-diagram.md) · [architecture-diagram.en.md](architecture-diagram.en.md) | Sơ đồ kiến trúc |
| [data-model.md](data-model.md) | Mô hình dữ liệu, bảng, cô lập org |
| [conversation.md](conversation.md) | Hội thoại/bộ nhớ phiên (Slack/Zalo/web) |
| [advisory-flow.md](advisory-flow.md) | Luồng tư vấn: vị thế đàm phán → rủi ro → fallback |
| [model-portability.md](model-portability.md) | Đổi LLM ngoài Qwen (env-only / +1 adapter) |
| [capacity.md](capacity.md) | Sức chứa, đồng thời, giới hạn |

## Tính năng
| Tài liệu | Nội dung |
|---|---|
| [crdb-features.md](crdb-features.md) | Agentic memory trên CockroachDB (4 tool CRDB) |
| [lawyer-mode.md](lawyer-mode.md) | Chế độ luật sư: party-aware, tách trái-luật/bất-lợi |

## Kênh Slack
| Tài liệu | Đối tượng |
|---|---|
| [slack-guide.md](slack-guide.md) | **Admin/kỹ thuật** — cài đặt bot, scope, webhook |
| [slack-handbook.md](slack-handbook.md) | **Người dùng** — cách dùng bot hằng ngày |

## Triển khai (CHỌN theo mục tiêu — KHÔNG trùng nhau)
| Tài liệu | Dùng khi |
|---|---|
| [deployment.md](deployment.md) | Tổng quan thiết kế production & scale |
| [deploy-free.md](deploy-free.md) | Demo/chấm điểm **$0** (CockroachDB Basic free + 1 URL HTTPS) |
| [deploy-aws.md](deploy-aws.md) | **AWS** (ECS/EC2 + S3) + CockroachDB (cuộc thi CRDB) |
| [deploy-ecs.md](deploy-ecs.md) | **Alibaba Cloud ECS** + HTTPS (DB ngoài) — prod hiện tại |
| [deploy-ecs-selfhosted.md](deploy-ecs-selfhosted.md) | Alibaba ECS **self-contained** (app+Caddy+Postgres+Redis trong Docker) |

## Bảo mật & tuân thủ
| Tài liệu | Nội dung |
|---|---|
| [security.md](security.md) | Auth, cô lập org, redact PII, erasure, rate-limit, đa-tổ-chức |
| [compliance-vn.md](compliance-vn.md) | Posture pháp lý VN: chống-UPL · Luật AI 134/2025 · PDPL 91/2025 |

## Blog / bài viết
| Tài liệu | Nội dung |
|---|---|
| [blog-qwen-cloud.md](blog-qwen-cloud.md) · [blog-qwen-cloud.vi.md](blog-qwen-cloud.vi.md) | Bài kỹ thuật (Qwen Cloud) |

_Ảnh minh họa: `docs/assets/`._
