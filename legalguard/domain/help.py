"""Hướng dẫn sử dụng + xử lý sự cố — nguồn CHUNG cho Slack (_is_help_query) và web (/help).

THUẦN (test offline), không phụ thuộc adapter. Mẫu như `domain/trust.py`: một hàm sinh nội dung,
Slack render text, web render HTML. 4 phần NGƯỜI-DÙNG: (1) giới thiệu, (2) chức năng, (3) cách dùng,
(4) gỡ sự cố — không lộ chi tiết kỹ thuật nội bộ. `support_contact` cấu hình được (trống → ẩn dòng liên hệ).
VĂN PHONG PHÁP LÝ, KHÔNG icon (đồng bộ với reply rà soát/tra cứu/đàm phán). Tuple giữ dạng
("", tiêu đề, mô tả) — cột icon để rỗng nhưng GIỮ 3 phần để tương thích web/test.
"""
from __future__ import annotations

# (1) Giới thiệu ngắn — Legal Guard là gì / cho ai.
_INTRO = ("Legal Guard là trợ lý pháp lý AI cho hợp đồng thương mại Việt Nam — rà soát rủi ro, tra cứu luật "
          "CÓ DẪN CHỨNG kiểm chứng được, và gợi ý đàm phán theo vị thế của bên bạn. AI làm phần nặng, "
          "bạn (hoặc luật sư) quyết phần rủi ro cao.")

# (2) Chức năng chính — hệ LÀM ĐƯỢC GÌ (danh sách năng lực).
_FEATURES = [
    ("", "Rà soát hợp đồng party-aware",
     "Chấm rủi ro từng điều khoản (bắt buộc sửa · thương lượng · chấp nhận), phân biệt điều khoản "
     "TRÁI LUẬT (có thể vô hiệu) với điều khoản chỉ bất lợi, kèm căn cứ điều luật."),
    ("", "Gợi ý & điều khoản phản-đề",
     "Mỗi rủi ro có hướng xử lý + điều khoản thay thế song ngữ (Việt/Anh) dán-được-ngay vào hợp đồng."),
    ("", "Đàm phán đa vòng",
     "Nhớ đã nhượng/chốt gì qua các vòng, đề xuất nước đi trao đổi, cảnh báo khi chạm điểm sống còn (walk-away)."),
    ("", "Bản ghi nhớ sửa đổi (Word)",
     "Tổng hợp rủi ro + đề xuất thành memo tải về .docx (trên web)."),
    ("", "Tra cứu luật có nguồn",
     "Trả lời câu hỏi pháp lý dẫn đúng Điều/Khoản văn bản CÒN hiệu lực; hỏi theo mốc thời gian cũng được."),
    ("", "Kiểm tra hiệu lực & theo dõi thay đổi văn bản",
     "Kiểm tra một văn bản còn hiệu lực hay đã bị thay thế; tự cảnh báo luật mới ảnh hưởng hợp đồng nào."),
    ("", "Độ tin cậy minh bạch",
     "Công bố số đo độ chính xác + phương pháp đảm bảo không bịa luật (trang /trust)."),
    ("", "Chốt chặn con người",
     "Khuyến nghị quan trọng bị KHÓA tới khi người duyệt Duyệt; Từ chối = chuyển chuyên gia."),
]

# (3) Bắt đầu thế nào — bước NHẬP thực tế (khác theo kênh).
_USAGE = [
    ("", "Rà soát hợp đồng",
     "{how_contract}. Nêu VỊ THẾ (bên mình bảo vệ, đòn bẩy) để phân tích sát hơn."),
    ("", "Tra cứu luật",
     "Hỏi một câu pháp lý (có dấu ?) — ví dụ “Phạt vi phạm hợp đồng tối đa bao nhiêu %?”."),
    ("", "Đàm phán",
     "Sau khi rà hợp đồng, dán phản hồi/đề nghị của đối tác để nhận nước đi vòng tiếp."),
    ("", "Xem độ tin cậy",
     "Hỏi “độ chính xác/đáng tin không” (Slack) hoặc mở trang /trust (web)."),
]

# (4) Gỡ sự cố.
_TROUBLE = [
    ("", "Lâu chưa thấy trả lời",
     "Rà soát hợp đồng mất vài phút (hợp đồng dài lâu hơn) — kết quả trả vào cùng chỗ hỏi. "
     "Câu hỏi tra cứu thường vài giây; quá 1 phút thì gửi lại."),
    ("", "“Không đọc được file”",
     "Hỗ trợ PDF, DOCX, TXT và ảnh/PDF-scan (tự OCR). File hỏng/khóa mật khẩu → mở khóa rồi gửi lại, "
     "hoặc dán thẳng nội dung dạng chữ."),
    ("", "Trả lời “chưa đủ căn cứ”",
     "Câu hỏi ngoài phạm vi dữ liệu luật hiện có → hệ TỪ CHỐI để không bịa (an toàn). "
     "Hãy hỏi cụ thể hơn, hoặc thuộc lĩnh vực đã phủ (hợp đồng/chế tài/lãi vay/hóa đơn/lao động/doanh nghiệp…)."),
    ("", "Kết quả cần người thật quyết",
     "Mọi khuyến nghị là HỖ TRỢ, không thay tư vấn chính thức — luật sư/người duyệt quyết cuối."),
    ("", "Lỗi giữa chừng / muốn chạy lại",
     "Khi báo lỗi (kể cả lỗi tải file), bấm nút Thử lại — hệ chạy lại đúng nội dung bạn đã gửi, KHỎI "
     "gõ/tải lại. Nút dùng trong ~15 phút; quá hạn (“hết hạn”) thì gửi lại tin. Sửa (edit) một CÂU TRA "
     "CỨU → tự chạy lại; tin phân tích hợp đồng thì gửi tin MỚI. File quá lớn → nút không giúp, "
     "hãy gửi bản gọn hơn."),
]


def format_help_text(channel: str = "slack", support_contact: str = "") -> str:
    """Sinh hướng dẫn dạng text (Slack/Zalo): giới thiệu → chức năng → cách dùng → sự cố. Không icon."""
    how_contract = ("Dán nội dung hợp đồng vào đây, hoặc kéo-thả file (PDF/DOCX/ảnh)"
                    if channel == "slack"
                    else "Mở trang Rà soát (/app), dán nội dung hoặc tải file hợp đồng lên")
    out = ["*LEGAL GUARD — HƯỚNG DẪN*", "", _INTRO, "", "*Chức năng chính:*"]
    out += [f"- *{t}* — {d}" for _i, t, d in _FEATURES]
    out += ["", "*Cách sử dụng (bắt đầu thế nào):*"]
    out += [f"- *{t}* — {d.format(how_contract=how_contract)}" for _i, t, d in _USAGE]
    out += ["", "*Gặp sự cố:*"]
    out += [f"- *{t}:* {d}" for _i, t, d in _TROUBLE]
    if support_contact.strip():
        out += ["", f"Cần hỗ trợ thêm: {support_contact.strip()}"]
    out += ["", "_Nội dung do AI hỗ trợ — không thay thế tư vấn pháp lý chính thức._"]
    return "\n".join(out)


def help_sections() -> dict:
    """Dữ liệu có cấu trúc cho web (render HTML). Tuple ("", tiêu đề, mô tả) — cột icon rỗng."""
    how = "Mở trang Rà soát, dán nội dung hoặc tải file hợp đồng lên"
    return {
        "intro": _INTRO,
        "features": [(i, t, d) for i, t, d in _FEATURES],
        "usage": [(i, t, d.format(how_contract=how)) for i, t, d in _USAGE],
        "trouble": [(i, t, d) for i, t, d in _TROUBLE],
    }
