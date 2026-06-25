# Sổ tay sử dụng Legal Guard trên Slack

Dành cho **người dùng cuối** (sales / chủ doanh nghiệp đang đàm phán hợp đồng).
Phần cài đặt bot cho workspace (admin): xem [`slack-guide.md`](slack-guide.md).

Legal Guard là "phòng pháp chế thuê ngoài" ngay trong Slack, **2 việc chính**:
1. **Soát hợp đồng** — gửi điều khoản/file → rủi ro + chiến lược đàm phán.
2. **Tra cứu luật** — hỏi thẳng câu hỏi pháp lý → câu trả lời dẫn đúng Điều/Khoản **còn hiệu lực**.

---

## Tính năng nhanh

| # | Tính năng | Cách kích hoạt |
|---|---|---|
| 1 | Rà soát điều khoản dán trực tiếp | Dán text có từ khóa hợp đồng vào channel |
| 2 | Rà soát file hợp đồng | Đính kèm PDF / DOCX / TXT / **ảnh scan** (≤10MB) |
| 3 | Hỏi đáp tiếp theo ngữ cảnh deal | Hỏi tự nhiên sau khi đã rà soát — bot nhớ deal đang bàn |
| 4 | Gọi bot ở channel đông | `@LegalGuard <nội dung>` — trả lời đúng thread |
| 5 | Tra cứu quy định pháp luật VN | Hỏi thẳng câu hỏi pháp lý → dẫn đúng Điều/Khoản **còn hiệu lực** + 📎 nguồn |
| 6 | Tra cứu luật **tại một thời điểm** | Thêm mốc vào câu: *"…năm 2020"* → trả luật còn hiệu lực **lúc đó** |
| 7 | Phản hồi 1 chạm | Bấm 👍 Đúng / ⚠️ Sai / ➖ Thiếu dưới câu trả lời — hệ thống học từ đó |

> 📌 **Câu có dấu hỏi → bot ưu tiên TRA CỨU** (kể cả khi câu nhắc tới "hợp đồng"). Muốn **rà soát**
> một đoạn điều khoản: dán đoạn đó (không phải câu hỏi) hoặc gửi file.

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

> ⚠️ **Phân biệt rà soát vs tra cứu:** dán một *đoạn điều khoản* (không có dấu hỏi) → bot **rà soát**.
> Gõ một *câu hỏi* ("…?", "…thế nào", "…bao nhiêu") → bot **tra cứu luật** (dù câu có chữ "hợp đồng").
> Muốn chắc chắn được rà soát: gửi dạng **file** hoặc dán đoạn điều khoản nguyên văn.

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

## Use case 6 — Tra cứu nhanh một quy định pháp luật VN

*Tình huống: cần biết một quy định mà không có hợp đồng nào để soát.*

Hỏi thẳng câu hỏi pháp lý (gõ vào channel hoặc `@LegalGuard`):

```
Bạn:  Thời điểm lập hóa đơn khi xuất khẩu hàng hóa?
Bot:  (trả lời ngôn ngữ thường + dẫn ĐÚNG Điều 9 Nghị định 123/2020 — bản đã sửa bởi
       NĐ 70/2025; tự kèm các quy định liên quan)

Bạn:  Phạt vi phạm hợp đồng tối đa bao nhiêu phần trăm?
Bot:  Không quá 8% giá trị phần nghĩa vụ bị vi phạm (Điều 301 Luật Thương mại 2005)...
```

- Câu trả lời **dẫn đúng điều/khoản** + dòng **📎 Nguồn** ở cuối, và **chỉ dùng văn bản còn hiệu lực**
  (không lôi nhầm bản đã hết hiệu lực/bị thay — lỗi mà tra Google/ChatGPT hay mắc).
- Mỗi câu trả lời kèm **nút 👍 Đúng / ⚠️ Sai / ➖ Thiếu** — bấm 1 chạm để hệ thống học (xem Use case 8).
- Việc nhạy cảm (đưa vào hợp đồng/quyết định) vẫn qua **chuyên gia duyệt** như mọi đầu ra khác.

## Use case 7 — Tra cứu luật TẠI một thời điểm (point-in-time)

*Tình huống: cần biết quy định áp dụng ở một thời điểm trong quá khứ (vd để xử lý hồ sơ năm cũ).*

Thêm **mốc thời gian** vào câu hỏi — bot trả luật **còn hiệu lực tại đúng thời điểm đó**:

```
Bạn:  Thời điểm lập hóa đơn quy định thế nào năm 2020?
Bot:  (trả theo Thông tư 39/2014 — quy định đang áp dụng NĂM 2020,
       KHÔNG phải Nghị định 123/2020 mới có hiệu lực 1/7/2022)

Bạn:  ...còn năm 2024 thì sao?
Bot:  (trả theo Nghị định 123/2020 — quy định còn hiệu lực năm 2024)
```

- Hỗ trợ: *"năm 2020"*, *"ngày 1/6/2022"*, *"01/06/2022"*.
- Không ghi mốc → mặc định trả **quy định hiện hành**.
- Muốn xem mọi bản kể cả đã hết hiệu lực: nói *"trước đây"* / *"bản cũ"*.

## Use case 8 — Góp ý để bot tốt hơn (nút phản hồi)

*Tình huống: câu trả lời chưa đúng/đủ — báo cho hệ thống bằng 1 chạm.*

Dưới mỗi câu trả lời của bot có 3 nút:

| Nút | Khi nào bấm |
|---|---|
| 👍 **Đúng** | Câu trả lời chính xác, hữu ích |
| ⚠️ **Sai** | Dẫn sai điều/khoản, hoặc nội dung không đúng |
| ➖ **Thiếu** | Đúng nhưng chưa đủ — thiếu căn cứ/trường hợp |

Bấm xong tin nhắn đổi thành *"✅ Cảm ơn phản hồi của bạn — đã ghi nhận."* Phản hồi (đặc biệt ⚠️/➖)
giúp đội pháp lý **biết chỗ cơ sở tri thức còn yếu để bổ sung** — càng dùng càng chuẩn.

---

## Câu hỏi thường gặp

**Bot trả lời "Gửi giúp em nội dung điều khoản…"?**
Tin của bạn quá ngắn/không phải câu hỏi (vd "ok", "cảm ơn"), không có điều khoản và channel
chưa có deal — gõ một **câu hỏi pháp lý**, **dán điều khoản**, hoặc **gửi file**.

**Hỏi luật mà bot lại đi rà soát hợp đồng (hoặc ngược lại)?**
Bot phân luồng theo dấu hiệu: *câu hỏi* (có "?"/"thế nào"/"bao nhiêu") → **tra cứu**; *đoạn điều khoản*
(không phải câu hỏi) có từ khóa HĐ → **rà soát**; có file → luôn rà soát. Diễn đạt lại cho rõ ý định.

**Kết quả có nhãn `[QWEN_STUB]`?**
Server đang chạy chế độ demo (chưa cấu hình API key AI) — báo admin.

**Bot có thay luật sư không?**
Không. Bot làm phần nặng (đọc, soi rủi ro, gợi ý chiến thuật); điều khoản 🔴 và quyết định
cuối luôn cần người duyệt — đó là thiết kế chủ đích, không phải giới hạn.

**Dữ liệu của tôi đi đâu?**
File không lưu; PII (email/SĐT) được che trước khi gửi AI; lịch sử chat giữ 7 ngày để bot
nhớ ngữ cảnh. Chi tiết: [`security.md`](security.md).

---

*Cập nhật 25/6/2026 · Cài đặt bot: [`slack-guide.md`](slack-guide.md) · Web: `/app` (soát HĐ) · `/lookup` (tra cứu luật)*
