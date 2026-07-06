# Devpost Submission — điền form sẵn-để-dán

> Copy từng field bên dưới vào form trên https://qwencloud-hackathon.devpost.com.
> Story dài (Inspiration/What it does/…) dùng nguyên văn trong [`DEVPOST.md`](DEVPOST.md).
> Hạn: **9 Jul 2026, 2:00 PM PT** (~4:00 sáng 10/7 giờ VN). Bản nộp = tag `v1.0-qwen`.

---

## 1. Thông tin ngắn (paste thẳng)

| Field Devpost | Giá trị |
|---|---|
| **Project title** | Legal Guard — Autopilot Agent for Cross-Border Contract Risk |
| **Tagline / elevator pitch** | An autopilot legal agent that reviews cross-border contracts, flags illegal/unfavorable clauses, and proposes position-aware negotiation tactics — with a human in the loop. |
| **Track** | Autopilot Agent |
| **Built with** (tags) | Qwen, DashScope, Alibaba Cloud ECS, Python, FastAPI, PostgreSQL, pgvector, Redis, Docker, Caddy, Alembic, MCP, RAG, BM25 |

## 2. Links (paste vào "Try it out" + các field bắt buộc)

| Field | Giá trị |
|---|---|
| **Repository URL** (public) | https://github.com/trungnguyen1618033/legal-guard-PH |
| **Live demo** | https://legalguard.duckdns.org — [/app](https://legalguard.duckdns.org/app) · [/lookup](https://legalguard.duckdns.org/lookup) · [/trust](https://legalguard.duckdns.org/trust) |
| **Demo video** (≤3 phút, public) | ⬜ TODO: `<YOUTUBE_LINK>` |
| **Proof of Alibaba Cloud deployment** (link file code) | https://github.com/trungnguyen1618033/legal-guard-PH/blob/main/legalguard/adapters/outbound/qwen.py — dùng endpoint `dashscope-intl.aliyuncs.com` (Alibaba Model Studio / Qwen Cloud). Bổ trợ: [`docker-compose.yml`](../docker-compose.yml), [`docs/deploy-ecs-selfhosted.md`](deploy-ecs-selfhosted.md) |
| **Architecture diagram** | https://github.com/trungnguyen1618033/legal-guard-PH/blob/main/docs/architecture-diagram.en.md |
| **License** | MIT (LICENSE ở gốc repo — GitHub tự hiện) |
| **Blog post** (tùy chọn, có giải riêng) | ⬜ TODO nếu nộp: `<BLOG_LINK>` (nháp: `docs/blog-qwen-cloud.md`) |

## 3. Story (paste nguyên văn từ DEVPOST.md)

Devpost có các ô: Inspiration · What it does · How we built it · Challenges · Accomplishments ·
What we learned · What's next → **copy đúng các mục cùng tên trong [`DEVPOST.md`](DEVPOST.md)**.

**How we use Qwen + Alibaba Cloud (bắt buộc):** All inference = Qwen qua DashScope-intl (Alibaba Model
Studio) — 6 model right-sized (`qwen3.7-max` reasoner · `qwen-flash` judge · `qwen-plus` lookup ·
`text-embedding-v4` · `qwen3-rerank` · `qwen3.7-plus` OCR). Hosting = Alibaba Cloud ECS (Docker: Caddy +
FastAPI + Postgres + Redis). Repo MIT open-core.

## 4. Điểm nhấn nên nêu trong description/video (ăn điểm Innovation 30% + fit Autopilot)
- **Đàm phán đa vòng CÓ TRẠNG THÁI** (differentiator): concession ledger nhớ qua vòng · walk-away guardrail
  theo red-line · concession ladder (nước đi trao đổi) · học từ win-rate flywheel.
- **Human-in-the-loop**: câu gửi đối tác bị khóa tới khi duyệt → escalate luật sư.
- **Autopilot**: cron quét luật mới → cảnh báo HĐ bị ảnh hưởng ("agent làm việc khi bạn ngủ") + self-tune.
- **Grounded, không bịa**: in-force filter + NLI + abstain. Độ chính xác **54/54** golden (công bố `/trust`).
- **Trust-by-design**: khớp Luật AI 134/2025 (giám sát người + minh bạch AI + audit) + redaction PII (PDPL).

---

## 5. Pre-submit checklist (làm theo thứ tự)
- [ ] Repo **Public** (Settings → visibility) — xác nhận LICENSE MIT hiện ở đầu trang repo
- [ ] Deploy ECS = bản mới nhất (`main`/`v1.0-qwen`) — check `/trust` hiện 54/54, `/app` có thang nhượng-bộ
- [ ] Quay + upload **video ≤3′ tiếng Anh, public** (HĐ ngắn thương mại) → điền `<YOUTUBE_LINK>` (mục 2)
- [ ] Điền form Devpost: mục 1 + 2 + 3 (story) + track Autopilot Agent
- [ ] Alibaba proof = link `qwen.py` (mục 2)
- [ ] Submit trước 8/7 (đệm an toàn trước hạn 9/7 2PM PT)
- [ ] (tùy chọn) nộp Blog post cho giải riêng
- [ ] (bảo mật) thu hồi key đã lộ: GEMINI_API_KEY + sk-ws-… (giờ vô dụng)
