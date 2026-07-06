# Moat & Defensibility — Legal Guard

> Đồng thuận 2026: **tech KHÔNG phải moat** (LLM ai cũng gọi được; "AI wrapper không data moat"
> là nhóm thất bại nhiều nhất). Foundation model sẽ tự nhảy vào vertical → *phải xây moat trước*.

## Moat-stack (theo thứ tự xây được)

| Lớp | Moat | Trạng thái |
|---|---|---|
| 1. Domain KB curated | Ma trận fallback luật VN do luật sư duyệt | có (cần làm dày) |
| 2. 🥇 **Data flywheel KẾT QUẢ** | Ghi `Outcome` (fallback nào dùng + thắng/thua) → học tactic nào thực thắng cho SME Việt. **Foundation model không lấy được** | **đã build cơ chế** (`outcomes` + `/insights/tactics`) |
| 3. Workflow lock-in | System of record HĐ + lịch sử + KB overlay riêng công ty | nền đã có |
| 4. Compliance/trust | Compliant-by-design theo Luật AI VN (grounding/audit/oversight) + uy tín luật sư | nền đã có |
| 5. Network effect | Benchmark ẩn danh "công ty như bạn thắng X% điều khoản…" | tương lai (cần đủ data) |

## Vòng dữ liệu (flywheel) — tài sản độc quyền nhất

```
Khách dùng → rà soát HĐ + ghi kết quả đàm phán (Outcome)
   → win-rate per điều khoản (outcome-aware ranking) → gợi ý chuẩn hơn
   → khách thắng nhiều hơn → dùng nhiều hơn → nhiều data hơn ↺
```
Cài đặt: `domain/models.Outcome`, `OutcomeRepositoryPort`, `POST /cases/{id}/outcome`,
`GET /insights/tactics`. `AnalysisService` gắn `win_rate` vào fallback (outcome-aware ranking).

## "Tech hay" defensible (đúng brand chiến lược gia đàm phán)
- **Outcome-aware fallback ranking** (đã có nền) — càng dùng càng chuẩn.
- **Counterparty/negotiation modeling** (tương lai) — dự đoán phản ứng đối tác → fallback mạnh nhất khả thi.
- **KHÔNG fine-tune sớm** — chưa đủ data + mất citation/audit (hỏng cho legal + Luật AI VN).
  Fine-tune model luật VN nhỏ là moat về SAU khi flywheel đã tích đủ.

## Hệ quả
- Moat **không** đến từ đánh bóng code, mà từ **dữ liệu kết quả tích lũy + KB luật sư + workflow + compliance**.
- Ưu tiên thực thi: thu thập Outcome thật từ khách thật càng sớm càng tốt → flywheel mới quay.
