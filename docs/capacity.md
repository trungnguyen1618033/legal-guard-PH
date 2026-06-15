# Ước tính Năng lực (Capacity Planning) — Legal Guard PH

> Kết luận trước: **điểm nghẽn là quota LLM (TPM của Qwen), KHÔNG phải server/DB.** Server rẻ;
> số người dùng phục vụ được do **token/phút của tài khoản DashScope** quyết định.
> ⚠️ Số dưới là **ước tính có phương pháp** — phải xác nhận quota thật trong DashScope console.

## 1. Giả định (nêu rõ để tính lại được)

| Tham số | Giá trị giả định | Ghi chú |
|---|---|---|
| LLM call / 1 lần `/analyze` | **~8 Qwen + 1 Gemini ≈ 9** | agent loop (~4) + verification (~3, mỗi rủi ro 1) + embed (~1) + summary (1) |
| Token / 1 lần `/analyze` | **~60,000** | HĐ + KB context nhân nhiều call |
| Wall-clock / 1 lần | **~30s** | 9 call tuần tự/bán song song |
| DashScope standard | **600 RPM · 1,000,000 TPM** | Qwen-Turbo: 5M TPM. **Free tier ~3 RPM = không dùng được** |
| Hành vi khách | **~5 lần rà soát / công ty / tháng** | SME xuất khẩu không ký hằng ngày |

## 2. Bottleneck = quota LLM (tính 2 chiều)

- **Theo TPM:** 1,000,000 ÷ 60,000 ≈ **~16 lần/phút**
- **Theo RPM:** 600 ÷ 8 ≈ **~75 lần/phút**
- → **TPM ràng buộc trước → ~16 lần `/analyze`/phút ≈ ~1,000/giờ** (1 tài khoản standard).

**Đồng thời (in-flight):** 16/phút × 30s ≈ **~8 request song song** → **1 app instance** (threadpool 40)
là **dư sức**. Tăng server KHÔNG giúp gì cho đến khi nâng quota LLM.

## 3. Phục vụ được bao nhiêu công ty?

Quy đổi 5 lần/tháng → tải/phút mỗi công ty: 5 ÷ 22 ngày ÷ 8h ÷ 60 ≈ 0.00047/phút; ×4 (peak) ≈ 0.0019/phút.

| Cấu hình | Throughput | **Công ty hoạt động** (≈) | Đồng thời |
|---|---|---|---|
| **Free tier (3 RPM)** | < 1 lần/phút | **~vài chục (chỉ demo)** | 1 |
| **Standard (1M TPM)** | ~16 lần/phút | **~8,000–10,000** | ~8 |
| **Qwen-Turbo (5M TPM)** | ~80 lần/phút | **~40,000–50,000** | ~40 |
| **+ giảm call 9→5 & cache** | ~2× | **~16,000–20,000** (standard) | — |

> "Người dùng đăng ký" có thể cao hơn nhiều (đa số không rà soát cùng lúc). Endpoint nhẹ
> (`/cases`, `/insights`, `/health`) là DB-bound → hàng nghìn req/s, không phải bottleneck.

## 4. Phân tầng năng lực

| Tier | Hạ tầng | Phục vụ |
|---|---|---|
| **Demo (free credit)** | 1 container, Qwen free | vài user thử — KHÔNG cho production |
| **MVP (standard)** | 1 app + RDS, Qwen paid standard | **~8–10k công ty** (1 account) |
| **Growth** | Turbo / quota tăng + cache + ít call hơn | **~40k+** |
| **Scale** | nhiều account/region + autoscale | tuyến tính theo quota |

## 5. Đòn bẩy tăng năng lực (theo thứ tự ROI)

1. **Nâng quota DashScope / enterprise tier** — ceiling thật; mở ticket xin tăng.
2. **Giảm số LLM call/analysis** (đòn bẩy lớn nhất, làm được bằng code):
   - **Gộp verification** 1 call cho tất cả rủi ro (thay vì 1/rủi ro) → bớt ~3 call.
   - **Cache** retrieval + kết quả phân tích HĐ trùng/giống.
   - Adaptive routing (đã có) giảm vòng cho HĐ đơn giản.
3. **Qwen-Turbo** cho bước phù hợp (TPM 5×) khi chất lượng cho phép.
4. **Async client** (httpx async) — nâng concurrency/instance (giờ sync, threadpool 40).
   *Chỉ quan trọng SAU khi đã nâng quota LLM* (vì quota binds trước).
5. **Batching/queue** giờ thấp điểm cho tác vụ nền (embed).

## 6. Lưu ý chi phí (unit economics)

~60k token/lần → chi phí token/lần × ~5 lần/tháng phải **< giá gói ($30–100/tháng)**. Giảm call/token
(mục 5) vừa tăng năng lực vừa cải thiện biên lợi nhuận. Tính lại theo bảng giá Qwen thực tế khi có.

## 7. Việc cần làm để chốt số thật
- Xác nhận **RPM/TPM/concurrency** thật của account trong **DashScope console** (free vs paid khác nhau lớn).
- Đo **token/call thực tế** + **latency** khi cắm key (chạy `evaluation/` với key thật).
- Load test endpoint nhẹ (k6/locust) để xác nhận DB/app ngưỡng (kỳ vọng >>> nhu cầu).
