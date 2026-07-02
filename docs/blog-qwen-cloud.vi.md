# Tôi xây AI đọc hợp đồng như luật sư — và biết nói "tôi chưa đủ căn cứ"

> Bản tiếng Việt của [`blog-qwen-cloud.md`](blog-qwen-cloud.md) — đăng LinkedIn/Facebook/blog
> cho cộng đồng SME & luật sư VN. Mọi con số bên dưới đều là số đo thật.

Hãy hình dung một xưởng nội thất nhỏ ở Bình Dương. Đối tác Đức gửi sang bản hợp đồng 12 trang
tiếng Anh. Ở trang 7 có một dòng: *"phạt chậm giao hàng: 15% giá trị hợp đồng."*

Chủ xưởng ký. Không ai nói với chị rằng Luật Thương mại Việt Nam chặn trần mức phạt ở **8%** —
phần vượt trần đơn giản là vô hiệu trước tòa. Chị vừa đồng ý một điều khoản thậm chí không hợp
pháp, và sẽ đàm phán ba hợp đồng tiếp theo mà không hề biết mình đang cầm lá bài đó trong tay.

Đó là bài toán tôi xây **Legal Guard** để giải, trong cuộc thi Qwen Cloud Hackathon (track
Autopilot Agent): một AI agent đọc hợp đồng của bạn, chỉ ra điều khoản nào chỉ *bất lợi* và điều
khoản nào *trái luật thật sự*, rồi giúp bạn phản đề — và mọi tin nhắn gửi đối tác đều phải có
con người duyệt trước khi rời khỏi cửa.

Dùng thử: https://legalguard.duckdns.org · Mã nguồn (mở): https://github.com/trungnguyen1618033/legal-guard-PH

Dưới đây là những gì tôi học được, kể bằng ngôn ngữ thường.

## Bài học 1: Đừng nhờ luật sư trưởng đi photo tài liệu

Các model AI giống nhân sự trong một hãng luật. Luật sư trưởng (`qwen3.7-max`) cực giỏi nhưng
chậm. Trợ lý (`qwen-flash`) nhanh và làm rất tốt những việc kiểm tra đơn giản, rõ ràng.

Bản đầu tiên của tôi gửi *mọi thứ* cho luật sư trưởng. Phân tích một hợp đồng mất mấy phút, mà
phần lớn thời gian dành cho những câu đơn giản kiểu: *"điều luật này có thật sự nói điều chúng
ta đang trích không — có hay không?"*

Nên tôi chia việc như một hãng luật thật:

- **Việc khó** (phân tích hợp đồng, vạch chiến lược đàm phán) → model lớn.
- **Kiểm tra có/không** → model nhanh: **0,5 giây thay vì 23 giây** — nhanh hơn ~46 lần, kết
  quả y hệt.
- **Tra cứu luật nhanh** → model cỡ vừa: 4–6 giây thay vì ~48.

Một khâu của hệ thống giảm từ **~4 phút xuống ~7 giây**. Không có gì "thông minh hơn" —
chỉ là việc được đưa đúng bàn.

## Bài học 2: Câu trả lời AI nguy hiểm nhất là câu SAI mà nghe TỰ TIN

Ai cũng lo AI "bịa" (hallucinate). Trong ngành luật, lỗi còn tinh vi hơn: AI trích một điều
luật **có thật**, nhưng điều luật đó **không hề nói** điều AI khẳng định. Kiểm tra số hiệu thì
đúng; kiểm tra ý nghĩa thì sai. Người đọc vội sẽ không bao giờ phát hiện.

Ba lớp chắn giải quyết chuyện này:

1. **Đôi mắt thứ hai.** Sau khi agent gắn cờ một rủi ro, một AI kiểm tra riêng chỉ làm đúng một
   việc: *"Đọc điều luật này. Nó có thật sự hậu thuẫn khẳng định kia không — có hay không?"*
   Trả lời mập mờ → tính là **không**. Trong ngành luật, hô nhầm "điều khoản này trái luật!"
   tệ hơn nhiều so với lặng lẽ chuyển cho luật sư xem lại.
2. **Không trích "luật zombie".** Luật bị thay thế liên tục. Legal Guard chỉ trích văn bản
   **còn hiệu lực** — và nếu bạn hỏi "quy định năm 2020 thế nào?", nó trả lời theo đúng luật
   *tại thời điểm 2020*.
3. **Biết nói "tôi chưa đủ căn cứ".** Hỏi ngoài kho tri thức, nó từ chối trả lời — như một luật
   sư tử tế nói "để tôi kiểm tra lại" thay vì đoán bừa. Trong bộ chấm điểm, từ chối đúng lúc
   được tính là trả lời đúng.

Chúng tôi kiểm tra tất cả bằng 54 câu hỏi có đáp án chuẩn, trải 12 lĩnh vực pháp luật Việt Nam.
Điểm hiện tại: **98,1% (53/54)** — từ mức 87% lúc khởi đầu. Ca cuối cùng dao động do độ ngẫu
nhiên của dịch vụ AI hosted, và chúng tôi nói thẳng điều đó thay vì làm tròn lên 100%. Toàn bộ
phương pháp công bố tại https://legalguard.duckdns.org/trust — vì một AI đụng đến rủi ro pháp lý
thì phải dám trưng bảng điểm của mình.

## Bài học 3: Nếu model rẻ gác cổng, phải sát hạch người gác cổng

Nhớ "trợ lý" nhanh làm việc kiểm tra có/không chứ? Một khi nó quyết định trích dẫn nào được
sống sót, nó trở thành mắt xích an toàn quan trọng nhất. Nên nó có bài thi riêng: 16 khẳng định
hóc búa ghép với nguyên văn điều luật — gồm cả bẫy kiểu *"thỏa thuận phạt 10% là hợp lệ theo
điều này"* đặt cạnh chính điều luật ghi trần 8%. Chúng tôi chấm model nhanh so với cả đáp án
chuẩn lẫn model lớn. Kết quả: **16/16 đúng, đồng thuận 100% với model lớn, nhanh hơn ~5 lần**
(`evaluation/nli_report.json`). Bài thi đó là thứ cho phép đánh đổi lấy tốc độ mà lương tâm
vẫn yên ổn.

## Bài học 4: "Autopilot" nghĩa là làm việc khi bạn ngủ

Track cuộc thi tên là *Autopilot Agent* — và tôi hiểu theo nghĩa đen. Trên máy chủ production
(một máy Alibaba Cloud nhỏ chạy mọi thứ trong Docker), một bộ hẹn giờ đánh thức agent lúc
**5 giờ sáng mỗi ngày**. Nó rà xem luật nào vừa có hiệu lực, rồi đối chiếu với **mọi hợp đồng
từng được rà soát**: có nghị định mới nào vừa sửa đúng điều luật mà hợp đồng của bạn đang dựa
vào không?

Và nó chính xác: nghị định sửa Điều 9 chỉ báo động những hợp đồng viện dẫn Điều 9 — không spam.
Bấm bỏ qua một báo động giả một lần, lần sau nó im. Khi thử nghiệm, nó đã nổ trên dữ liệu thật:
một nghị định về trọng tài gắn cờ 8 hợp đồng có điều khoản trọng tài nước ngoài. Không ai yêu
cầu nó làm. Đó chính là ý nghĩa của autopilot.

## Những gì THẤT BẠI (đáng giá ngang những gì thành công)

- Một phương pháp truy xuất "cây thông minh" thời thượng thua phương pháp lai cổ điển trong bài
  đo của chúng tôi. Cái nhàm chán thắng.
- Một ý tưởng rerank bằng đồ thị không tạo khác biệt đo được. Vẫn nằm trong code, tắt mặc định.
- Chỉnh tay ngưỡng để vá từng ca sai → hỏng ca khác, như đập chuột chũi. Cách sửa cấu trúc
  (ngưỡng tự động, không chỉnh tay) mới là thứ trụ lại.

## Tóm tắt một dòng

Dành ngân sách tốc độ cho suy luận, ngân sách an toàn cho kiểm chứng, và công bố đúng con số
mình đo được — chứ không phải con số trông đẹp.

*Xây bằng các model Qwen trên Qwen Cloud (DashScope), deploy trên Alibaba Cloud ECS. Mã nguồn
mở (MIT), 365 test tự động. Tag nộp bài: `v1.0-qwen`.*
