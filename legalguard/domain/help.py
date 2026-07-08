"""Hướng dẫn sử dụng + xử lý sự cố — nguồn CHUNG cho Slack (_is_help_query) và web (/help).

THUẦN (test offline), không phụ thuộc adapter. Mẫu như `domain/trust.py`: một hàm sinh nội dung,
Slack render text, web render HTML. Giữ nội dung NGƯỜI-DÙNG (cách dùng + gỡ sự cố), không lộ chi tiết
kỹ thuật nội bộ. `support_contact` cấu hình được (mặc định để trống → ẩn dòng liên hệ).
"""
from __future__ import annotations

# Các mục hướng dẫn — dùng chung, chỉ khác cách NHẬP theo kênh (Slack vs web).
_USAGE = [
    ("📄", "Rà soát hợp đồng",
     "{how_contract} → nhận bảng rủi ro (🔴 bắt buộc sửa · 🟠 thương lượng · 🟢 chấp nhận được) "
     "kèm căn cứ điều luật + gợi ý điều khoản thay thế. Nêu VỊ THẾ (bên mình bảo vệ, đòn bẩy) để phân tích sát hơn."),
    ("🔎", "Tra cứu luật",
     "Hỏi một câu pháp lý (có dấu ?) — ví dụ “Phạt vi phạm hợp đồng tối đa bao nhiêu %?”. "
     "Trả lời dẫn đúng Điều/Khoản + nguồn; không đủ căn cứ thì TỪ CHỐI thay vì đoán."),
    ("💬", "Đàm phán đa vòng",
     "Sau khi rà hợp đồng, dán phản hồi/đề nghị của đối tác — hệ nhớ đã nhượng/chốt gì, "
     "đề xuất nước đi trao đổi, cảnh báo khi chạm điểm sống còn (walk-away)."),
    ("📊", "Độ tin cậy",
     "Hỏi “độ chính xác/đáng tin không” — hệ công bố số đo + phương pháp đảm bảo (trang /trust)."),
]

_TROUBLE = [
    ("⏳", "Lâu chưa thấy trả lời",
     "Rà soát hợp đồng mất vài phút (hợp đồng dài lâu hơn) — kết quả trả vào cùng chỗ hỏi. "
     "Câu hỏi tra cứu thường vài giây; nếu quá 1 phút, gửi lại."),
    ("📎", "“Không đọc được file”",
     "Hỗ trợ PDF, DOCX, TXT và ảnh/PDF-scan (tự OCR). File hỏng/khóa mật khẩu → mở khóa rồi gửi lại, "
     "hoặc dán thẳng nội dung dạng chữ."),
    ("🤔", "Trả lời “chưa đủ căn cứ”",
     "Câu hỏi ngoài phạm vi dữ liệu luật hiện có → hệ TỪ CHỐI để không bịa (an toàn). "
     "Hãy hỏi cụ thể hơn, hoặc thuộc lĩnh vực đã phủ (hợp đồng/chế tài/lãi vay/hóa đơn/lao động/doanh nghiệp…)."),
    ("⚖️", "Kết quả cần người thật quyết",
     "Mọi khuyến nghị là HỖ TRỢ, không thay tư vấn chính thức — luật sư/người duyệt quyết cuối. "
     "Trên web: câu nhắn đối tác bị khóa tới khi reviewer Duyệt; Từ chối = chuyển chuyên gia."),
]


def format_help_text(channel: str = "slack", support_contact: str = "") -> str:
    """Sinh hướng dẫn dạng text (Slack/Zalo). channel đổi cách mô tả bước NHẬP."""
    how_contract = ("Dán nội dung hợp đồng vào đây, hoặc kéo-thả file (PDF/DOCX/ảnh)"
                    if channel == "slack"
                    else "Mở trang Rà soát (/app), dán nội dung hoặc tải file hợp đồng lên")
    lines = ["🤝 *LEGAL GUARD — HƯỚNG DẪN NHANH*", "", "*Dùng để làm gì:*"]
    for icon, title, desc in _USAGE:
        lines.append(f"{icon} *{title}* — {desc.format(how_contract=how_contract)}")
    lines += ["", "*Gặp sự cố:*"]
    for icon, title, desc in _TROUBLE:
        lines.append(f"{icon} *{title}:* {desc}")
    if support_contact.strip():
        lines += ["", f"🆘 Cần hỗ trợ thêm: {support_contact.strip()}"]
    lines += ["", "_🤖 AI hỗ trợ — không thay thế tư vấn pháp lý chính thức._"]
    return "\n".join(lines)


def help_sections() -> dict:
    """Dữ liệu có cấu trúc cho web (render HTML). Cách nhập mô tả kiểu web."""
    how = "Mở trang Rà soát, dán nội dung hoặc tải file hợp đồng lên"
    return {
        "usage": [(i, t, d.format(how_contract=how)) for i, t, d in _USAGE],
        "trouble": [(i, t, d) for i, t, d in _TROUBLE],
    }
