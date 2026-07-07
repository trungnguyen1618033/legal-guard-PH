# Prompt tạo ảnh — Blog + Devpost gallery

## Bạn cần BAO NHIÊU ảnh? (không phải cứ đủ 5)
| Mục đích | Cần | Loại |
|---|---|---|
| **Architecture Diagram** (Devpost bắt buộc) | 1 | render mermaid (chuẩn) hoặc AI |
| **Proof deploy Alibaba** (Devpost bắt buộc) | 1 | ⚠️ **SCREENSHOT THẬT** — KHÔNG AI |
| **Video demo** (Devpost bắt buộc) | — | quay màn hình (không phải ảnh) |
| **Gallery Devpost** (khuyên, tối đa 15) | 3–5 | ⚠️ **screenshot THẬT** sản phẩm |
| **Blog** (tùy chọn) | 1 hero + 0–3 minh họa | AI-generate |

→ **Tối thiểu**: architecture (1) + proof Alibaba (1) + vài screenshot thật. **AI-image chỉ cần 1 hero** cho blog
là đủ; 4 minh họa còn lại là *nice-to-have*, làm nếu dư thời gian. **Đừng để việc tạo ảnh chặn nộp bài.**

> **Quy tắc vàng:** ✅ AI-generate = hero + minh họa khái niệm (trang trí). ⚠️ ẢNH THẬT (KHÔNG AI) =
> screenshot UI + proof Alibaba (AI vẽ UI/console giả = trông fake + rủi ro gian lận).

---

## Cách dùng prompt (tối ưu)
1. Dán **STYLE** (dưới) + **1 SCENE** vào ChatGPT (GPT-image) / Gemini (Imagen) / Midjourney.
2. Image model **hay bịa chữ lỗi** → mọi prompt đã ép *"absolutely no text"*. Nếu vẫn ra chữ → thêm
   "remove all text" ở lần chỉnh.
3. Muốn **đồng bộ**: giữ NGUYÊN đoạn STYLE cho cả bộ → 5 ảnh cùng tông.
4. Tỉ lệ: **blog hero 16:9** · **Devpost thumbnail/gallery 3:2** (đổi "16:9"→"3:2" ở cuối prompt).

### STYLE (prefix — dán trước mọi scene)
> Flat modern editorial vector illustration. Clean light background. Palette: deep navy, teal, warm amber,
> soft shadows. Professional, optimistic, uncluttered, boardroom-quality. **Absolutely no text, no letters,
> no numbers, no logos, no UI mockups.** Aspect ratio 16:9.

---

## A. Ảnh AI-GENERATE

**0. DEVPOST THUMBNAIL (3:2)** *(card gallery — bố cục gọn, đọc được ở size nhỏ)*
> [STYLE nhưng 3:2] Centered composition optimized to read at small thumbnail size: a friendly geometric
> AI-assistant / shield protecting a contract document; one clause glows red (risky/illegal), one glows green
> (safe); a small Vietnam flag accent + subtle scales-of-justice. Bold simple shapes, high contrast. No text.
> *(Devpost card đã có title bên dưới → không cần chữ trong ảnh. Hoặc crop hero 16:9 → 3:2 cho nhanh.)*

**1. HERO** *(nên có — blog cover + Devpost thumbnail)*
> [STYLE] Scene: a confident Vietnamese woman running a small export business, at a tidy desk with a laptop
> showing a multi-page contract; beside her a friendly geometric AI-assistant / shield motif points at one
> contract line marked red (risky) and one marked green (safe); faint scales-of-justice and document icons
> float subtly. Focus on trust and clarity.

**2. Right-sizing models** *(Lesson 1 — optional)*
> [STYLE] Scene: two desks as a metaphor for AI models — a large slow "senior partner" desk and a small fast
> "assistant" desk — with paper tasks flowing by arrows to the correct desk. Sense of smart delegation.

**3. Grounding / no hallucination** *(Lesson 2 — optional)*
> [STYLE] Scene: a friendly robot holding a magnifying glass over an open law book, comparing a claim to the
> statute; one claim gets a green checkmark, another a red cross; a small "?" bubble suggesting honest doubt.

**4. Negotiation copilot** *(Lesson 5 — ưu tiên nếu chỉ làm thêm 1 ảnh: đây là moat)*
> [STYLE] Scene: a negotiation table, two parties facing each other; an AI copilot beside the near party holds
> a checklist ledger with several items ticked (secured) and points to a glowing exit / "walk-away" arrow; a
> hand moves a chess piece to signal strategy. Confident and strategic, not aggressive.

**5. Autopilot at night** *(Lesson 4 — optional)*
> [STYLE, but night palette: deep blue with one warm amber accent] Scene: a person peacefully asleep while a
> small AI agent stays awake scanning a stack of legal documents with a radar sweep; a single notification
> bell glows on one flagged document. Calm "works while you sleep" mood.

## B. Ảnh THẬT — screenshot (KHÔNG AI)
Chụp từ live `https://legalguard.duckdns.org` (hoặc local `/app`) — 3:2 đẹp cho gallery:
- **Analyze**: kết quả rà HĐ có nhãn ⚖️ TRÁI LUẬT + priority + căn cứ điều luật.
- **Trace / `/runs`**: agent tool-calls (AI-Native evidence).
- **Negotiate**: ✅ Đã chốt + 🪜 thang nhượng-bộ + 🚪 walk-away.
- **`/trust`**: 54/54 + phương pháp.  ·  **`/lookup`**: dẫn Điều/Khoản + 🗺️ lược đồ VB.

## C. Architecture Diagram (Devpost bắt buộc)
- **Chuẩn nhất**: copy khối ```mermaid``` trong `architecture-diagram.en.md` → https://mermaid.live → Export PNG.
- Hoặc AI: [STYLE] + "software architecture diagram, left→right: Users → (Web/Slack/Zalo/MCP) → FastAPI →
  Domain core (ReAct agent · NLI verify · multi-round negotiation) → Qwen Cloud/DashScope on Alibaba Cloud
  (6 models) + Knowledge Base + PostgreSQL/pgvector + Redis; labeled arrows; emphasize all inference → Qwen."
  *(Lưu ý: AI thường vẽ sơ đồ có chữ lỗi → render mermaid an toàn hơn cho diagram.)*

## D. Proof deploy Alibaba (Devpost bắt buộc) — ⚠️ ẢNH THẬT
SSH ECS → ghép 1 ảnh: Alibaba Cloud console (ECS instance id + region) · terminal `docker ps` ·
`curl -s https://legalguard.duckdns.org/health` → `{"status":"ok","qwen_ready":true}`. **KHÔNG AI-generate.**
