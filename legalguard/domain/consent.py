"""Chế độ luật sư — MẪU VĂN BẢN ĐỒNG Ý (consent) điền sẵn cho khách của luật sư.

Vì sao (business-upgrade-plan đòn bẩy 2): luật sư đưa thông tin khách vào công cụ AI phải có sự đồng ý
của khách — nghĩa vụ bảo mật (điểm c khoản 1 Điều 9 Luật Luật sư + Quy tắc 7 Bộ Quy tắc Đạo đức LS) +
Luật BVDLCN 91/2025 (khách = chủ thể dữ liệu) + chuẩn nghề thế giới (ABA Formal Op. 512 7/2024). Đây là
văn bản LUẬT SƯ ký với KHÁCH, không phải của Legal Guard — công cụ chỉ SINH bản điền sẵn để luật sư rà
& dùng. Đi kèm hồ sơ kiểm chứng (`domain/audit.py`) tạo bộ "chế độ luật sư" hoàn chỉnh.

`compile_consent` THUẦN (test offline). Nguồn: docs/internal/compliance-pdpl/03-mau-consent-*.md.
"""
from __future__ import annotations

_BLANK = "________________"


def compile_consent(party_a: str = "", party_b: str = "", org_name: str = "",
                    date: str = "", matter: str = "") -> str:
    """Sinh MẪU VĂN BẢN ĐỒNG Ý (markdown) điền sẵn tên các bên. Tham số rỗng → để ô trống cho ký tay.
    party_a = khách hàng; party_b = luật sư/tổ chức hành nghề; matter = vụ việc (tùy chọn)."""
    a = party_a.strip() or _BLANK
    b = party_b.strip() or (org_name.strip() or _BLANK)
    d = date.strip() or "____/____/________"
    scope = (f" trong phạm vi vụ việc: {matter.strip()}" if matter.strip()
             else " trong phạm vi vụ việc đã ký hợp đồng dịch vụ pháp lý")
    return f"""# VĂN BẢN ĐỒNG Ý SỬ DỤNG CÔNG CỤ TRÍ TUỆ NHÂN TẠO HỖ TRỢ

> ⚠️ **DRAFT do công cụ sinh — luật sư PHẢI rà & điều chỉnh trước khi dùng với khách.** Đáp ứng nghĩa vụ
> bảo mật (điểm c khoản 1 Điều 9 Luật Luật sư + Quy tắc 7) + Luật BVDLCN 91/2025. Đây là văn bản của
> LUẬT SƯ ký với KHÁCH, không phải của Legal Guard.

**Bên A (Khách hàng):** {a}  ·  **Bên B (Luật sư/Tổ chức hành nghề):** {b}

**Ngày:** {d}

1. **Phạm vi.** Bên A đồng ý để Bên B sử dụng công cụ AI hỗ trợ (Legal Guard — công cụ **phân tích &
   thông tin pháp luật có trích nguồn**, KHÔNG phải dịch vụ tư vấn pháp luật độc lập) nhằm hỗ trợ rà
   soát hợp đồng/tài liệu{scope}.

2. **Bản chất công cụ.** Bên A hiểu kết quả do AI tạo **mang tính hỗ trợ, tham khảo**, KHÔNG thay thế
   ý kiến chuyên môn của luật sư; **luật sư (Bên B) chịu trách nhiệm cuối cùng** và đã/đang đối chiếu
   kết quả AI với văn bản gốc và pháp luật hiện hành.

3. **Dữ liệu & bảo mật.** Bên A đồng ý để Bên B đưa nội dung tài liệu (đã che các định danh liên hệ như
   email/điện thoại/mã số/tên trước khi gửi mô hình) vào công cụ để phân tích. Dữ liệu xử lý theo Luật
   BVDLCN 91/2025; nội dung gốc **không bị lưu** (chỉ lưu vân tay/hash phục vụ audit). Việc xử lý có thể
   gồm **chuyển dữ liệu tới hạ tầng AI đặt tại nước ngoài** (Singapore) với cam kết không dùng để huấn luyện.

4. **Quyền của Bên A.** Bên A có quyền: rút lại sự đồng ý bất kỳ lúc nào (bằng văn bản); yêu cầu truy
   cập, chỉnh sửa, xóa dữ liệu cá nhân liên quan; yêu cầu Bên B KHÔNG dùng AI cho vụ việc.

5. **Lưu vết.** Mỗi lần rà soát, Bên B lưu **hồ sơ kiểm chứng** (nguồn dẫn + dấu vết xử lý + xác nhận
   luật sư đã đối chiếu — xuất từ `GET /cases/{{id}}/audit`) để phục vụ minh bạch & trách nhiệm nghề nghiệp.

**Bên A ký:** {_BLANK}    **Bên B (Luật sư) ký:** {_BLANK}

---
*Legal Guard — AI hỗ trợ, có luật sư duyệt; không thay thế tư vấn pháp lý chính thức.*
"""
