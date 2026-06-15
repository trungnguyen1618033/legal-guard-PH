# Hội thoại & Memory (chat session) — thiết kế

> Chat phải nhớ **hợp đồng đang bàn + lịch sử** để trả lời tiếp ("nếu họ từ chối SIAC thì sao?")
> như AI chat thật, thay vì rà soát một-phát rời rạc. Nguồn: OpenAI Agents SDK session memory, mem0.

## 1. Tầng memory (theo chuẩn 2026)
- **Working memory (short-term):** lịch sử lượt chat trong phiên (user/assistant) — cửa sổ N lượt.
- **Deal context (long-term của phiên):** tóm tắt kết quả rà soát gần nhất (rủi ro + ưu tiên + chiến lược)
  → "đang bàn hợp đồng nào". Đây là state quan trọng nhất.
- **Bound token:** giữ N lượt gần nhất + (prod) **summarization** lượt cũ; tránh nhồi cả lịch sử.

## 2. Session
- Key = `"{platform}:{conversation_id}"` (vd `zalo:user123`, `slack:C0XYZ`). Mỗi key một `Conversation`.
- Lưu: `history[]` + `context` (deal) + `updated_at`. Port `ConversationStorePort`.
- Adapter MVP: **in-memory** (1 process). Prod: **Redis/SQL** (TTL phiên) — chỉ đổi adapter.

## 3. Định tuyến ý định (intent)
```
có file đính kèm  hoặc  text chứa tín hiệu HĐ (trọng tài/thanh toán/điều khoản…)  → RÀ SOÁT (analyze)
ngược lại, đã có deal context                                                    → TRẢ LỜI TIẾP (follow-up)
chưa có gì                                                                       → mời gửi hợp đồng
```
Follow-up = `reasoner.complete` với [bối cảnh deal + N lượt gần + câu hỏi] (không chạy lại full analyze).

## 4. Luồng
```
tin nhắn (key) → load Conversation → intent
  ├─ analyze: rà soát → reply gọn → context = tóm tắt deal
  └─ follow-up: trả lời dựa context + lịch sử
→ append (user, assistant) → trim cửa sổ → save
```

## 5. Triển khai
- `Conversation` (`domain/models.py`) · `ConversationStorePort` (`ports.py`).
- ✅ **3 backend store** (`adapters/outbound/conversation_store.py`): `InMemory` (dev) ·
  **`SqlAlchemy` (persist + ĐA INSTANCE, mặc định)** · `Redis` (TTL, cần `pip install redis`).
  Chọn qua `CONVERSATION_BACKEND` (migration `0004` tạo bảng `conversations`).
- ✅ **Progressive summarization** (`ChatHandler._summarize`): vượt 12 lượt → gộp lượt cũ vào
  `context` bằng `reasoner`, giữ 6 lượt gần (bound token).
- `ChatHandler` stateful: store + intent + follow-up qua `reasoner`. Channels truyền `conversation_id`.
- *Next (prod):* vector memory (mem0-style) cho hội thoại rất dài · intent bằng LLM classifier (thay heuristic).
