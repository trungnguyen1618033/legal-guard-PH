# Sổ tay sử dụng Legal Guard trên Slack

Dành cho **người dùng cuối** (sales / chủ doanh nghiệp đang đàm phán hợp đồng).
Phần cài đặt bot cho workspace (admin): xem [`slack-guide.md`](slack-guide.md).

Legal Guard là "phòng pháp chế thuê ngoài" ngay trong Slack: gửi điều khoản hoặc file
hợp đồng → trong vài chục giây nhận lại **rủi ro + chiến lược đàm phán**, tiếng Việt.

---

## Tính năng nhanh

| # | Tính năng | Cách kích hoạt |
|---|---|---|
| 1 | Rà soát điều khoản dán trực tiếp | Dán text có từ khóa hợp đồng vào channel |
| 2 | Rà soát file hợp đồng | Đính kèm PDF / DOCX / TXT / **ảnh scan** (≤10MB) |
| 3 | Hỏi đáp tiếp theo ngữ cảnh deal | Hỏi tự nhiên sau khi đã rà soát — bot nhớ deal đang bàn |
| 4 | Gọi bot ở channel đông | `@LegalGuard <nội dung>` — trả lời đúng thread |

---

## Đọc kết quả như thế nào

Bot trả về 3 phần, ví dụ:

> 📋 **Rà soát hợp đồng:**
> 🔴 Điều khoản trọng tài: Trọng tài tại nơi bất lợi cho SME VN
> 🟠 Điều khoản thanh toán: Thanh toán T/T trả sau, rủi ro quỵt tiền
>
> 🧭 Chiến lược (vị thế balanced): GIỮ CỨNG điều khoản trọng tài (must_fix);
> CÓ THỂ NHƯỢNG về kiểm định để chốt deal; điểm RÚT: nếu không đạt trọng tài
> trung lập và bạn có đối tác thay thế (BATNA).
> ⚖️ Có điểm rủi ro cao — nên để chuyên gia pháp lý duyệt trước khi áp dụng.

| Ký hiệu | Nghĩa | Hành động của bạn |
|---|---|---|
| 🔴 `must_fix` | Rủi ro phải sửa bằng được | Không ký nếu đối tác không nhượng |
| 🟠 `negotiate` | Nên đàm phán lại | Mặc cả — có thể đổi lấy điều khoản khác |
| 🟢 `acceptable` | Chấp nhận được | Có thể nhượng để chốt deal |
| 🧭 | Chiến lược tổng | Giữ gì / nhượng gì / khi nào rút lui |
| ⚖️ | Cần chuyên gia duyệt | Đừng gửi đối tác trước khi có người duyệt |

> 💬 Slack trả bản **tóm tắt nhanh**. Bản đầy đủ — gồm **câu phản hồi tiếng Anh sẵn gửi
> đối tác** cho từng điều khoản + nút duyệt của chuyên gia — nằm trên web app (`/app`).
> Quy trình chuẩn: xem nhanh trên Slack → vào web duyệt → copy câu tiếng Anh gửi đối tác.

---

## Use case 1 — Đối tác gửi draft, cần soi nhanh điều khoản

*Tình huống: đối tác Trung Quốc gửi draft, sales không rành pháp lý, muốn biết "có bẫy không".*

1. Vào channel có bot (vd `#ra-soat-hop-dong`).
2. Copy phần điều khoản đáng ngờ (EN hay VI đều được), dán thẳng:
   ```
   Disputes shall be resolved by arbitration in Beijing.
   Payment by T/T 60 days after delivery.
   Quality inspection at destination port.
   ```
3. Bot tự nhận diện đây là nội dung hợp đồng (nhờ từ khóa: *arbitration, payment,
   inspection, trọng tài, thanh toán…*) → trả kết quả như mẫu ở trên.
4. Chuyển kết quả 🔴 cho sếp/chuyên gia quyết trước khi phản hồi đối tác.

> ⚠️ Nếu text **không có từ khóa hợp đồng nào**, bot coi là câu hỏi thường —
> muốn chắc chắn được rà soát, thêm chữ "hợp đồng:" trước đoạn dán, hoặc gửi dạng file.

## Use case 2 — Gửi nguyên file hợp đồng (PDF / ảnh chụp)

*Tình huống: đối tác gửi PDF 8 trang, hoặc chỉ có bản giấy chụp bằng điện thoại.*

1. Trong channel có bot, bấm **+** → đính kèm file (PDF, DOCX/DOC, TXT, PNG/JPG — tối đa 10MB).
2. Không cần gõ gì thêm — bot **báo nhận ngay** ("📥 Đã nhận! Em đang rà soát…") rồi tự tải
   file, bóc text (ảnh scan → OCR tự động) và rà soát. Kết quả về sau vài phút.
3. Hợp đồng dài được phân tích theo từng đoạn — kết quả gộp đủ, không sót phần cuối
   (nếu có phần chưa quét được, bot sẽ nói rõ trong kết quả).

**Khi gặp lỗi:** "Không đọc được file" → file hỏng/scan quá mờ, chụp lại rõ hơn;
"File quá lớn" → nén hoặc tách nhỏ.

> 🔒 File **không bị lưu lại** — hệ thống chỉ phân tích trong bộ nhớ rồi bỏ, lưu duy nhất
> vân tay SHA-256 để đối chiếu khi cần. Deal nhạy cảm nên gửi **file** thay vì dán text
> (text dán nằm trong lịch sử chat).

## Use case 3 — Hỏi tiếp như nói chuyện với luật sư

*Tình huống: đã rà soát xong, giờ muốn bàn cách đàm phán.*

Sau lần rà soát, bot **nhớ deal đang bàn theo channel** (7 ngày). Cứ hỏi tự nhiên:

```
Bạn:  Nếu đối tác từ chối đổi trọng tài sang SIAC thì sao?
Bot:  (tư vấn dựa trên đúng các rủi ro + chiến lược của deal này)

Bạn:  Bên mình đang cần đơn này gấp, nhượng khoản thanh toán được không?
Bot:  (cân nhắc theo ngữ cảnh: thanh toán đang ở mức 🟠 negotiate...)
```

Mẹo: hỏi trong **thread** của kết quả rà soát — bot trả lời đúng thread, channel gọn gàng.

## Use case 4 — Gọi bot giữa channel đông người

*Tình huống: đang bàn deal trong `#sales`, không muốn chuyển channel.*

Gõ `@LegalGuard` + nội dung (hoặc mention kèm file đính kèm):

```
@LegalGuard hợp đồng yêu cầu đặt cọc 50%, thanh toán T/T trả sau 60 ngày
```

- Bot chỉ phản hồi tin **có mention** (khi không phải member của channel đó).
- Trả lời đúng thread của tin nhắn — không làm loãng channel.
- Lưu ý: nếu bot **được invite vào** channel, nó nghe mọi tin như channel riêng —
  channel đông thì *đừng invite*, chỉ mention là đủ.

## Use case 5 — Nhiều deal cùng lúc

Bộ nhớ deal tính **theo channel** (mọi thread trong channel chung một ngữ cảnh).
Đang đàm phán 2 hợp đồng song song? Tách mỗi deal một channel:

```
#deal-seafood-shanghai   ← deal A: bot nhớ ngữ cảnh A
#deal-coffee-hamburg     ← deal B: bot nhớ ngữ cảnh B
```

Gửi hợp đồng mới vào channel cũ thì ngữ cảnh chuyển sang deal mới nhất.

---

## Câu hỏi thường gặp

**Bot trả lời "Gửi giúp em nội dung điều khoản…"?**
Tin của bạn không có từ khóa hợp đồng và channel chưa có deal nào đang bàn — dán điều
khoản hoặc gửi file trước.

**Kết quả có nhãn `[QWEN_STUB]`?**
Server đang chạy chế độ demo (chưa cấu hình API key AI) — báo admin.

**Bot có thay luật sư không?**
Không. Bot làm phần nặng (đọc, soi rủi ro, gợi ý chiến thuật); điều khoản 🔴 và quyết định
cuối luôn cần người duyệt — đó là thiết kế chủ đích, không phải giới hạn.

**Dữ liệu của tôi đi đâu?**
File không lưu; PII (email/SĐT) được che trước khi gửi AI; lịch sử chat giữ 7 ngày để bot
nhớ ngữ cảnh. Chi tiết: [`security.md`](security.md).

---

*Cập nhật 6/2026 · Cài đặt bot: [`slack-guide.md`](slack-guide.md) · Web app đầy đủ: `https://<host>/app`*
