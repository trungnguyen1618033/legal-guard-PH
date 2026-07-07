# Devpost Submission — điền form sẵn-để-dán

> Copy từng field bên dưới vào form trên https://qwencloud-hackathon.devpost.com.
> Story dài (Inspiration/What it does/…) dùng nguyên văn trong [`DEVPOST.md`](DEVPOST.md).
> Hạn: **9 Jul 2026, 2:00 PM PT** (~4:00 sáng 10/7 giờ VN). Bản nộp = tag `v1.0-qwen`.

---

## 1. Thông tin ngắn (paste thẳng)

| Field Devpost | Giá trị |
|---|---|
| **Project name** | Legal Guard |
| **Elevator pitch** | An autopilot legal agent for Vietnamese SMEs: flags illegal/unfavorable clauses in cross-border contracts and negotiates fallback tactics from your real bargaining position — with a human in the loop. |
| **Track** | Track 4: Autopilot Agent |
| **Built with** (tags) | python, fastapi, qwen, dashscope, alibaba-cloud-ecs, postgresql, pgvector, redis, docker, mcp, rag, bm25 |

## 2. Links (paste vào "Try it out" + các field bắt buộc)

| Field | Giá trị |
|---|---|
| **Repository URL** (public) | https://github.com/trungnguyen1618033/legal-guard-PH |
| **Live demo** | https://legalguard.duckdns.org — [/app](https://legalguard.duckdns.org/app) · [/lookup](https://legalguard.duckdns.org/lookup) · [/trust](https://legalguard.duckdns.org/trust) |
| **Demo video** (≤3 phút, public) | ⬜ TODO: `<YOUTUBE_LINK>` |
| **Proof of Alibaba Cloud deployment** (link file code) | https://github.com/trungnguyen1618033/legal-guard-PH/blob/main/legalguard/adapters/outbound/qwen.py — dùng endpoint `dashscope-intl.aliyuncs.com` (Alibaba Model Studio / Qwen Cloud). Bổ trợ: [`docker-compose.yml`](../docker-compose.yml), [`docs/deploy-ecs-selfhosted.md`](deploy-ecs-selfhosted.md) |
| **Architecture diagram** | https://github.com/trungnguyen1618033/legal-guard-PH/blob/main/docs/architecture-diagram.en.md |
| **License** | MIT (LICENSE ở gốc repo — GitHub tự hiện) |
| **Blog post** (tùy chọn, có giải riêng) | ✅ https://dev.to/ntt-fei/i-built-an-ai-that-reads-contracts-like-a-lawyer-and-knows-when-to-say-i-dont-know-27pb |

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

## 4b. Additional info (cho giám khảo — required fields)

| Field | Giá trị |
|---|---|
| Submitter type | Individual |
| Organization name | *(để TRỐNG — cá nhân, không áp dụng)* |
| Country of residence | Vietnam |
| Newly built or existing? | **New** |
| Start date | 06-09-26 |
| Track | **Track 4: Autopilot Agent** |
| Repository URL | https://github.com/trungnguyen1618033/legal-guard-PH |
| **Alibaba proof (code file URL)** | https://github.com/trungnguyen1618033/legal-guard-PH/blob/main/legalguard/adapters/outbound/qwen.py |

**"What you updated during the submission period"** — field CÓ ĐIỀU KIỆN ("nếu tồn tại trước 26/5"). Dự án
là **New** (commit đầu 09/06 — verify git) → thực chất N/A; nếu form vẫn bắt buộc thì paste (trung thực):
> Newly built during the submission period — first commit June 9, 2026 (after May 26); it did not exist before. Everything was created from scratch: the ReAct contract-review agent, hybrid RAG over in-force Vietnamese law with NLI verification, stateful multi-round position-aware negotiation (concession ledger + walk-away guardrail + concession ladder + win-rate flywheel), proactive autopilot law-monitoring, a human-in-the-loop checkpoint, and the Qwen-on-Alibaba-Cloud deployment.

**"Which AI tools have you leveraged" (SỬA — BỎ Gemini "real-time search"; paste):**
> Qwen models via Qwen Cloud / DashScope for ALL product inference (qwen3.7-max reasoner, qwen-flash judge/NLI, qwen-plus lookup, text-embedding-v4, qwen3-rerank, qwen3.7-plus vision-OCR). Claude Code as a coding assistant during development.

## 4c. Ảnh cần nộp (2 file) + prompt tạo

1. **Architecture Diagram** (png/jpg/pdf) — có thể render/AI-generate.
2. **Screenshot proof of Alibaba deployment** (png/jpg) — ⚠️ **PHẢI LÀ ẢNH THẬT** (chụp console Alibaba/terminal), **KHÔNG AI-generate** (đây là bằng chứng deploy thật; bịa = gian lận, mà bạn ĐÃ deploy thật nên chỉ cần chụp).

**Architecture diagram — ĐÃ RENDER SẴN:** upload `docs/assets/architecture-overview.png` (sơ đồ hệ thống —
Users→Alibaba ECS→Qwen Cloud 6 model). Bonus: `docs/assets/architecture-sequence.png` (luồng phân tích).
*(Nguồn mermaid: `docs/architecture-diagram.en.md` — muốn render lại thì dán khối ```mermaid vào https://mermaid.live.)*

**Prompt AI tạo ảnh Architecture Diagram (ChatGPT/Gemini) — nếu muốn đẹp hơn:**
> Create a clean, professional software architecture diagram (light background, 3:2 ratio) for "Legal Guard", a hexagonal (ports & adapters) FastAPI legal-AI agent. Left→right flow: Users → (Web UI · Slack · Zalo · MCP) → FastAPI inbound adapter → Domain core box (ReAct agent · analysis use-case · NLI self-critique · multi-round negotiation) → Outbound adapters → **Qwen Cloud / DashScope on Alibaba Cloud ECS** (qwen3.7-max reasoner, qwen-flash judge, qwen-plus lookup, text-embedding-v4, qwen3-rerank, qwen3.7-plus OCR) + Knowledge Base (in-force Vietnamese law) + PostgreSQL/pgvector + Redis. Label the arrows; emphasize all inference goes to Qwen on Alibaba Cloud. Minimal, boardroom-quality, no clutter, English labels.

**Screenshot Alibaba — ĐÃ CHỤP THẬT:** upload `docs/assets/ecs-deployment-proof.png` (console Alibaba Cloud
→ ECS Instance, region Singapore ap-southeast-1: instance `legalguard` status **Running**, 2 vCPU/4GiB,
IP public 47.84.59.79). Field này của Devpost ghi mâu thuẫn (ảnh HOẶC link code) → nộp **cả ảnh thật +
link `qwen.py`** cho chắc.
⚠️ Instance subscription hết hạn ~27/7 → GIA HẠN tới sau 31/7 để live sống suốt judging period.

**Thumbnail + gallery — ĐÃ CÓ:** Thumbnail = `docs/assets/devpost-thumbnail.png` (3:2, focal robot+shield,
premium — đọc rõ ở card nhỏ). Gallery = `devpost-gallery-1.png` + `architecture-overview.png` +
`demo-analyze/trace/lookup/trust.png` (screenshot UI thật).

## 5. Pre-submit checklist (làm theo thứ tự)
- [ ] Repo **Public** (Settings → visibility) — xác nhận LICENSE MIT hiện ở đầu trang repo
- [ ] Deploy ECS = bản mới nhất (`main`/`v1.0-qwen`) — check `/trust` hiện 54/54, `/app` có thang nhượng-bộ
- [ ] Quay + upload **video ≤3′ tiếng Anh, public** (HĐ ngắn thương mại) → điền `<YOUTUBE_LINK>` (mục 2)
- [ ] Điền form Devpost: mục 1 + 2 + 3 (story) + track Autopilot Agent
- [ ] Alibaba proof = link `qwen.py` (mục 2)
- [ ] Submit trước 8/7 (đệm an toàn trước hạn 9/7 2PM PT)
- [x] Blog post đã đăng: https://dev.to/ntt-fei/i-built-an-ai-that-reads-contracts-like-a-lawyer-and-knows-when-to-say-i-dont-know-27pb
- [ ] (bảo mật) thu hồi key đã lộ: GEMINI_API_KEY + sk-ws-… (giờ vô dụng)
