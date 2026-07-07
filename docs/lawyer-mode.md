# Chế độ luật sư — Dùng Legal Guard đúng quy tắc nghề

> Legal Guard là **công cụ phân tích & thông tin pháp luật có trích nguồn** để hỗ trợ luật sư —
> KHÔNG phải dịch vụ tư vấn pháp luật độc lập, KHÔNG thay thế phán quyết của luật sư. Tài liệu này
> hướng dẫn dùng công cụ đúng nghĩa vụ nghề nghiệp + bảo vệ dữ liệu.

## Nguyên tắc: AI hỗ trợ, luật sư chịu trách nhiệm cuối cùng
Chuẩn nghề thế giới đang hội tụ (ABA Formal Op. 512 · Singapore MinLaw Guide 2026): luật sư **phải
verify mọi output AI** và **lưu bằng chứng đã verify**. Legal Guard thiết kế theo đúng tinh thần đó:

- **Human-in-the-loop bắt buộc**: câu gửi đối tác bị **khóa** tới khi người duyệt Approve; Reject →
  escalate. AI không tự gửi gì ra ngoài.
- **Grounded, biết từ chối**: mọi phát hiện gắn nguồn (Điều/Khoản còn hiệu lực) + xác minh NLI; ngoài
  cơ sở tri thức → **"chưa đủ căn cứ"** thay vì đoán. Kết quả là điểm khởi đầu để luật sư đối chiếu, không phải kết luận.
- **Minh bạch AI** (Luật AI 134/2025): mọi trả lời gắn nhãn "🤖 AI".

## Quy trình 3 bước cho một vụ việc

### 1. Lấy đồng ý của khách trước khi đưa tài liệu vào công cụ
Nghĩa vụ bảo mật (điểm c khoản 1 Điều 9 Luật Luật sư + Quy tắc 7) + Luật BVDLCN 91/2025 (khách =
chủ thể dữ liệu). Sinh mẫu văn bản đồng ý điền sẵn:

```
GET /lawyer/consent?party_a=<khách>&party_b=<luật sư>&date=07/07/2026&matter=<vụ việc>
```
→ trả bản **draft** để luật sư rà, điều chỉnh, ký với khách. *(Dữ liệu gửi mô hình đã được che định
danh liên hệ — email/điện thoại/mã số/tên — trước khi rời máy; nội dung gốc không bị lưu.)*

### 2. Rà soát — luật sư đối chiếu, không giao khoán
Dùng `/analyze` (hoặc chat). AI gắn cờ rủi ro (⚖️ trái luật vs bất lợi) + căn cứ + đề xuất. **Luật sư
đối chiếu từng phát hiện với văn bản gốc & pháp luật hiện hành** rồi quyết Approve/Reject ở human checkpoint.

### 3. Xuất hồ sơ kiểm chứng — lưu bằng chứng đã verify
```
GET /cases/{case_id}/audit?reviewer=<tên luật sư>&note=<ghi chú đối chiếu>
```
→ memo markdown gồm: vân tay tài liệu (SHA-256, không lưu nội dung) · phát hiện AI + căn cứ · dấu vết
tác nhân (AI đã làm gì) · ô ký kiểm chứng của luật sư. **Đính kèm hồ sơ vụ việc** để chứng minh đã đối chiếu.

## Dữ liệu & tuân thủ
- **Không lưu toàn văn**: DB chỉ giữ trích đoạn ngắn + vân tay hash phục vụ audit.
- **Che định danh** trước khi gửi mô hình (rule-based; nâng cấp NER Presidio khi cần).
- **Chuyển dữ liệu xuyên biên giới**: xử lý qua hạ tầng AI tại Singapore, cam kết không dùng để huấn
  luyện. Khi triển khai có khách thật: lập hồ sơ đánh giá tác động + thông báo theo PDPL 91/2025.
- **Quyền khách**: rút đồng ý · truy cập/sửa/xóa dữ liệu (`DELETE /cases/{id}` xóa cascade case +
  outcomes + feedback).

## Giới hạn (nói thẳng)
- Cơ sở tri thức phủ một số lĩnh vực luật VN — ngoài phạm vi, công cụ **từ chối** thay vì đoán.
- Số liệu chính xác (`/trust`) đo trên bộ đề nội bộ, **chưa được cơ quan/hội nghề xác nhận**.
- Công cụ **không tạo quan hệ luật sư–khách hàng** và không thay thế tư vấn pháp lý chính thức.
