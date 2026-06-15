# Triển khai bot Slack — tài liệu kỹ thuật (admin)

Cách dựng và vận hành bot Legal Guard trên một workspace Slack: tạo app, scopes,
webhook, biến môi trường, xử lý sự cố. **Chỉ admin/người triển khai cần đọc** — đọc 1 lần lúc setup.

> 📖 **Người dùng cuối KHÔNG cần tài liệu này.** Gửi họ sổ tay sử dụng:
> [`slack-handbook.md`](slack-handbook.md) (use case từng bước, ví dụ hội thoại, FAQ).

## ❓ Có cần @mention bot không?

**Không bắt buộc — bot hỗ trợ cả hai chế độ:**

| Chế độ | Khi nào dùng | Cách hoạt động |
|---|---|---|
| **Channel riêng** (khuyên dùng) | Tạo `#ra-soat-hop-dong`, invite bot | Bot phản hồi **mọi tin nhắn** — gõ tự nhiên, không cần tag |
| **@mention** | Channel đông người (`#sales`, `#general`...) | Chỉ khi gõ `@LegalGuard <nội dung>` bot mới phản hồi tin đó |

⚠️ Lưu ý khi invite bot vào channel chung: bot là *member* của channel nên vẫn nghe mọi tin —
tin **không** mention sẽ vẫn được xử lý như ở channel riêng. Muốn bot "im lặng trừ khi gọi tên"
ở channel đông, **đừng invite bot vào channel** — chỉ cần `@mention` là đủ để bot nhận event
(cần scope + event `app_mention`, xem mục cài đặt).

> Bot tự bỏ qua: tin của chính nó và các bot khác, tin bị sửa/xóa, bản giao lại (retry) từ
> Slack, và tự **dedup khi mention trong channel bot là member** (Slack bắn 2 event cho cùng
> 1 tin — bot chỉ trả lời 1 lần).

## 🚀 Cách dùng (3 cách gửi hợp đồng)

| Cách | Thao tác | Bot làm gì |
|---|---|---|
| **Dán text** | Dán điều khoản vào channel (VI/EN) | Nhận diện tín hiệu hợp đồng → rà soát |
| **Gửi file** | Đính kèm PDF / DOCX / TXT / **ảnh scan** (≤10MB) | Bóc text (scan → OCR) → rà soát |
| **Hỏi tiếp** | Sau khi đã rà soát, hỏi thường: *"Nếu đối tác từ chối SIAC thì sao?"* | Trả lời dựa trên ngữ cảnh deal đang bàn (bot nhớ phiên theo channel) |

**Tín hiệu để bot rà soát** (tin dán text chỉ được phân tích khi chứa ít nhất một từ):
`hợp đồng` · `điều khoản` · `trọng tài` · `thanh toán` · `kiểm định` · `giao hàng` ·
`contract` · `clause` · `arbitration` · `payment` · `inspection` · `delivery`.
Tin không có tín hiệu → bot coi là câu hỏi follow-up (nếu đang có deal) hoặc hướng dẫn gửi hợp đồng.

**Kết quả bot trả về:**
- 📋 Danh sách điều khoản rủi ro, gắn ưu tiên: 🔴 phải sửa · 🟠 đàm phán · 🟢 chấp nhận được
- 🧭 Chiến lược đàm phán (giữ gì / nhượng gì / điểm rút lui)
- ⚖️ Cảnh báo khi có rủi ro cao → nên để chuyên gia pháp lý duyệt trước khi áp dụng

Hỏi trong **thread** thì bot trả lời đúng thread đó. Mỗi channel là một phiên tư vấn riêng
(bot nhớ lịch sử + deal đang bàn theo channel).

## 🛠️ Cài đặt (admin làm 1 lần)

### 1. Tạo Slack app

[api.slack.com/apps](https://api.slack.com/apps) → **Create New App → From scratch** → chọn workspace.

### 2. Bot Token Scopes (OAuth & Permissions)

| Scope | Để làm gì |
|---|---|
| `chat:write` | Gửi reply về channel |
| `files:read` | Tải file hợp đồng đính kèm |
| `channels:history` | Nhận tin nhắn ở public channel (chế độ channel riêng) |
| `app_mentions:read` | Nhận tin `@mention` bot (chế độ mention) |
| `groups:history` | (nếu dùng private channel) |
| `im:history` | (nếu muốn nhắn riêng — DM với bot) |

→ **Install App to Workspace** → copy **Bot User OAuth Token** (`xoxb-…`).
Mỗi lần đổi scope phải **Reinstall App** thì token mới có hiệu lực.

### 3. Cấu hình server

Trong `.env`:

```bash
SLACK_SIGNING_SECRET=...   # Basic Information → Signing Secret
SLACK_BOT_TOKEN=xoxb-...   # bước 2
```

Khởi động server (`uv run uvicorn app:app` hoặc `make up`). Test local thì mở tunnel:
`ngrok http 8000` → lấy URL HTTPS.

### 4. Event Subscriptions

Bật **Enable Events** → Request URL: `https://<host>/channels/slack/events`
(server phải đang chạy — Slack gửi challenge, app tự trả lời).

**Subscribe to bot events:** `message.channels` + `app_mention`
(+ `message.groups` / `message.im` nếu cần) → **Save**.

### 5. Dùng thử

```
/invite @LegalGuard          ← trong channel riêng đã tạo
```

Gửi thử: `Tranh chấp giải quyết bằng trọng tài tại Bắc Kinh. Thanh toán T/T sau 60 ngày.`
→ bot trả về danh sách rủi ro + chiến lược trong vài giây (LLM thật có thể lâu hơn).

## 🔧 Sự cố thường gặp

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| Bot im lặng hoàn toàn | Chưa invite bot vào channel · thiếu `SLACK_BOT_TOKEN` · thiếu scope `channels:history` | `/invite @bot`; kiểm tra `.env`; xem log server (lỗi `not_in_channel`, `invalid_auth`... được log rõ) |
| Request URL không verify được | Server chưa chạy / tunnel sai / `SLACK_SIGNING_SECRET` sai | Chạy server trước, kiểm tra secret |
| Bot báo "Không đọc được file" | File hỏng hoặc scan mờ; OCR cần `QWEN_API_KEY` | Gửi lại bản rõ hơn; cấu hình key |
| Bot báo "File quá lớn" | File > `MAX_UPLOAD_BYTES` (mặc định 10MB) | Gửi bản gọn hơn hoặc tăng giới hạn |
| Reply có nhãn `[QWEN_STUB]` | Chưa cấu hình `QWEN_API_KEY` (chế độ stub) | Điền key thật vào `.env` |

## 🔒 Riêng tư & dữ liệu

- File hợp đồng **không được lưu** — chỉ phân tích trong bộ nhớ rồi bỏ. Hệ thống lưu
  vân tay SHA-256 + metadata để đối chiếu audit (xem [`security.md`](security.md)).
- PII (email/SĐT) được che trước khi gửi AI. Lịch sử chat lưu theo channel (TTL 7 ngày
  với backend Redis) để bot nhớ ngữ cảnh deal.
- Lưu ý: nội dung **dán trực tiếp** vào chat sẽ nằm trong lịch sử phiên — deal nhạy cảm
  nên gửi dạng **file** thay vì dán text.

---

*Cập nhật 6/2026. Kiến trúc kênh chat: [`conversation.md`](conversation.md) · webhook/bảo mật: [`security.md`](security.md).*
