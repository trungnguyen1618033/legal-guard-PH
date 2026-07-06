# Prompt tạo ảnh — Blog + Devpost gallery

> Dùng ChatGPT / Gemini / image tools. **Quy tắc vàng:**
> - ✅ **AI-generate**: hero + minh họa khái niệm (trang trí blog / thumbnail Devpost).
> - ⚠️ **ẢNH THẬT (KHÔNG AI)**: screenshot UI sản phẩm (`/app`·`/lookup`·`/trust`·Trace) + **bằng chứng deploy
>   Alibaba** (console ECS + `docker ps` + `/health`). AI vẽ UI giả = trông fake + rủi ro gian lận.
> - Thêm **"no text, no logos"** vào mọi prompt (AI viết chữ trong ảnh thường lỗi/nhòe).
> - Giữ **cùng bảng màu** cho đồng bộ: navy + teal + amber, nền sáng, phong cách flat/editorial.

---

## A. Ảnh AI-GENERATE (trang trí)

**1. Hero (blog cover + Devpost thumbnail) — 16:9**
> Editorial tech illustration, clean flat modern style, light background, palette navy + teal + amber.
> A confident Vietnamese small-business owner at a desk reviewing a multi-page international contract on
> a laptop; beside her a friendly AI assistant / shield motif highlighting one contract clause in red
> (risky) and one in green (safe); subtle scales-of-justice and document icons. Professional, optimistic,
> uncluttered. No text, no logos. 16:9.

**2. Lesson 1 — right-sizing models**
> Flat isometric illustration, light background, navy/teal/amber. A law firm as a metaphor for AI models:
> a large "senior partner" desk (deliberate) and a small fast "paralegal" desk (quick), with tasks routed
> to the right desk by little arrows. Clean, minimal. No text, no logos. 16:9.

**3. Lesson 2 — grounding / no hallucination**
> Flat illustration, light background, navy/teal/amber. An AI robot checking a claim against an open law
> book with a magnifying glass; one statement gets a green "verified" check, another a red "unsupported"
> cross; a small thought bubble suggesting honest uncertainty ("?"). Professional, trustworthy. No text. 16:9.

**4. Lesson 5 — negotiation copilot (moat, ảnh nổi bật nhất)**
> Flat illustration, light background, navy/teal/amber. A negotiation table with two parties facing each
> other; an AI copilot stands beside the near party showing a checklist ledger (some items checked = secured)
> and a glowing exit/"walk-away" sign; a chess-piece being moved to signal strategy. Confident, strategic,
> not aggressive. No text, no logos. 16:9.

**5. Lesson 4 — autopilot (works while you sleep)**
> Flat night-scene illustration, calm deep-blue palette with a warm amber accent. A person asleep at night
> while a small AI agent stays awake scanning a stack of legal documents with a radar sweep at 5 AM; a
> notification bell lights up on one affected contract. Peaceful, "agent works while you sleep". No text. 16:9.

## B. Ảnh THẬT — screenshot (KHÔNG AI)
Chụp từ live `https://legalguard.duckdns.org` (hoặc local `/app`):
- **Analyze**: kết quả rà HĐ — có nhãn ⚖️ TRÁI LUẬT + priority + căn cứ điều luật.
- **Trace / `/runs`**: agent tool-calls (AI-Native evidence).
- **Negotiate**: card đàm phán — ✅ Đã chốt + 🪜 thang nhượng-bộ + 🚪 walk-away.
- **`/trust`**: trang công bố 54/54 + phương pháp.
- **`/lookup`**: câu trả lời dẫn Điều/Khoản + 🗺️ lược đồ văn bản.
→ Devpost gallery (tối đa 15 ảnh, 3:2 đẹp nhất): ưu tiên các ảnh THẬT này — chứng minh sản phẩm chạy thật.

## C. Architecture Diagram (Devpost bắt buộc)
- **Chuẩn nhất**: render mermaid — copy khối ```mermaid``` trong `architecture-diagram.en.md` → https://mermaid.live → Export PNG.
- Hoặc AI-generate: xem prompt trong [`SUBMISSION.md`](SUBMISSION.md) §4c.

## D. Bằng chứng deploy Alibaba (Devpost bắt buộc) — ⚠️ ẢNH THẬT
SSH vào ECS → ghép 1 ảnh: Alibaba Cloud console (ECS instance id + region) · terminal `docker ps` ·
`curl -s https://legalguard.duckdns.org/health` → `{"status":"ok","qwen_ready":true}`. **KHÔNG AI-generate.**
