# Luồng Tư vấn Đàm phán — thiết kế thực tế

> Khắc phục khuyết điểm: sản phẩm trước là *bộ phân tích một-phát*, bỏ qua **vị thế đàm phán** dù
> hứa "fallback theo thế trận thực tế". Bản này đưa khung đàm phán thật (BATNA/ZOPA/leverage) vào lõi.

## 1. Khung đàm phán áp dụng (nguồn: HBS/Karrass)
- **BATNA** (giải pháp thay thế tốt nhất) = nguồn *leverage* chính → quyết định **walk-away point**.
- **ZOPA** = vùng thỏa thuận khả thi; biết ranh giới để **không nhượng quá mức tối thiểu**.
- **Bên yếu thế** dễ rơi "negotiation trap" (nhận deal xấu để tránh mất đơn) → cần **ưu tiên rõ**
  điều gì *phải giữ* vs *có thể nhượng*.

## 2. Vị thế đàm phán = ĐẦU VÀO (trước đây bỏ qua)

| Trường | Giá trị | Ảnh hưởng tư vấn |
|---|---|---|
| `leverage` | strong / balanced / weak | weak → fallback mềm, ưu tiên giữ điều khoản sống còn |
| `urgency` | low / high | high → bớt cứng rắn, đổi nhượng lấy tốc độ |
| `relationship` | new / repeat | new → siết bảo vệ thanh toán/định danh đối tác |
| `alternatives` | có / không (BATNA) | không có BATNA → tránh "walk-away" hão, tập trung giảm thiệt |

## 3. Output tư vấn (sâu hơn "list rủi ro")

Mỗi rủi ro được gán **`priority`**:
- `must_fix` — điều khoản sống còn, phải giữ (vd trọng tài bất lợi khi giá trị lớn).
- `negotiate` — nên thương lượng lại, có thể đổi chác.
- `acceptable` — chấp nhận được nếu cần nhượng để chốt deal.

Và một **`strategy`** tổng thể (ngôn ngữ thường, theo `lang`):
- Thứ tự ưu tiên (giữ gì / nhượng gì để đổi gì).
- **Walk-away point** dựa trên BATNA (nếu không có BATNA → nói rõ + tập trung giảm thiểu).
- Bước đi cụ thể tiếp theo.

## 4. Luồng concierge thực tế (mục tiêu vận hành)
```
Hỏi vị thế (leverage/urgency/relationship/BATNA) + HĐ
  → AI: rà soát + gán priority + chiến lược (giữ/nhượng/walk-away)
  → CHUYÊN GIA duyệt (điểm must_fix/rủi ro cao)
  → giao khách (báo cáo tiếng Việt) qua kênh thật (Zalo/email)
  → vòng sau khi đối tác phản hồi  ↺
```
Giai đoạn này: **concierge** (chuyên gia + AI nội bộ) là luồng thật; tự-phục-vụ là về sau.

## 5. Đã/đang triển khai trong code
- `NegotiationPosition` (đầu vào) · `Risk.priority` · `AnalysisResult.strategy`.
- Agent nhận vị thế → gán priority + sinh chiến lược tổng thể (final message).
- API `/analyze` nhận `leverage/urgency/relationship/alternatives`; báo cáo có mục **Chiến lược đàm phán**.
- ✅ **OCR cho HĐ scan/ảnh** (Qwen-VL): upload `.png/.jpg/PDF-scan` → `OcrFallbackParser` tự OCR khi
  text rỗng (fallback an toàn khi chưa có key). `docs` xem `architecture.md` (DocumentParserPort).
- ✅ **Kênh Zalo OA / Slack khép kín** (`channels.py` + `chat_senders.py`): webhook verify chữ ký →
  (ack nhanh, xử lý nền) tải file user gửi → analyze → **gửi reply về chat** (Slack `chat.postMessage`,
  Zalo OA send). Bật bằng secret + token (`SLACK_BOT_TOKEN` / `ZALO_ACCESS_TOKEN`); thiếu token → trả
  reply trong HTTP response (fallback).
- *Chưa làm (next):* vòng đàm phán đa phiên · escalation chuyên gia thật · một-phía-luật.
