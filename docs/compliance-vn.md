# Tuân thủ pháp lý Việt Nam — Legal Guard (compliance-by-design)

> Posture tuân thủ của sản phẩm với khung pháp lý VN 2026. Các biện pháp dưới đây **đã có trong sản phẩm**
> (dẫn vị trí code). Phần hồ sơ nộp cơ quan (A05/DPIA) = **draft, hoàn thiện + luật sư rà khi onboard khách thật**.

## 1. Chống hành nghề luật sư trái phép (UPL) — Luật Luật sư
**Nguyên tắc:** "tư vấn pháp luật" là đặc quyền luật sư; "thông tin pháp luật có trích nguồn" thì tự do.
→ Legal Guard định vị là **công cụ PHÂN TÍCH & THÔNG TIN pháp luật có trích nguồn + lớp SÀNG LỌC cho luật sư**,
KHÔNG phải dịch vụ tư vấn pháp luật.
- **Không** bề mặt nào tự nhận là "tư vấn/dịch vụ pháp luật" (đã audit web/help/reply).
- **Disclaimer** ở mọi kênh: *"…công cụ hỗ trợ phân tích… KHÔNG thay thế tư vấn pháp luật chính thức… hãy đối
  chiếu bản gốc & hỏi luật sư"* (`_AI_DISCLOSURE_LEGAL` gắn idempotent; web footer; `domain/help.py`, `trust.py`).
- **Human-in-the-loop bắt buộc**: rủi ro cao → `needs_human_review` + human-checkpoint (khóa câu gửi đối tác tới
  khi chuyên gia duyệt) + escalation luật sư (`/escalate`). Fast-review LUÔN ép người duyệt.

## 2. Minh bạch AI — Luật AI 134/2025 (hiệu lực 1/3/2026) + NĐ 142/2026
- **Công bố "đang tương tác với AI"**: disclaimer AI ở mọi reply + web banner; marker "🤖/AI" trên kênh.
- **Giám sát của con người**: human-checkpoint + `needs_human_review` + escalation (đúng yêu cầu human-oversight).
- **Tự phân loại rủi ro (draft)**: hệ hỗ-trợ-quyết-định pháp lý → có thể rơi nhóm rủi ro trung bình/cao (chờ
  Nghị định hướng dẫn phân loại). Biện pháp giảm thiểu ĐÃ có: minh bạch AI · human oversight · grounding +
  trích nguồn · verify NLI 2 lớp (chống bịa) · audit trail (`/cases/{id}/audit`) · công bố độ tin cậy (`/trust`).
- **Không tự ý quyết định pháp lý**: mọi output là đề xuất, người quyết cuối.

## 3. Bảo vệ dữ liệu cá nhân — PDPL 91/2025 + NĐ 356/2025 (hiệu lực 1/1/2026)
- **Redact PII TRƯỚC khi gửi mô hình** (`domain/redaction.py`): dữ liệu cá nhân trong HĐ/câu hỏi được che
  trước khi gọi LLM → giảm mạnh dữ liệu cá nhân rời hệ. (USP: "PII không rời VN dạng nhận-dạng-được".)
- **Chuyển dữ liệu xuyên biên giới**: LLM qua Qwen DashScope Singapore (**no-training**). → cần **hồ sơ đánh giá
  tác động chuyển dữ liệu ra nước ngoài (A05/DPIA)** nộp Bộ Công an trong 60 ngày kể từ khi có khách thật
  → **DRAFT + luật sư rà** (chưa nộp vì chưa có khách production). Phương án thay: self-host LLM trong VN
  (kiến trúc model-agnostic — xem `docs/model-portability.md` — đổi `base_url` sang endpoint nội địa, 0 code).
- **Quyền xóa (right-to-erasure) CASCADE**: `delete_case` xóa case + outcomes + feedback + memory (không để
  orphan dữ liệu cá nhân) → đáp ứng quyền xóa PDPL/GDPR.
- **Cô lập theo công ty** (`org_id` mọi bảng) + **audit trail** (vân tay SHA-256, không lưu toàn văn HĐ).
- **DPA** (Data Processing Agreement) chuẩn PDPL trong Terms → draft khi onboard.

## 4. Tổng kết trạng thái
| Khung | Đã có trong sản phẩm | Còn (khi có khách thật) |
|---|---|---|
| Chống-UPL | ✅ định vị + disclaimer + human-checkpoint | rà ngôn từ marketing |
| Luật AI 134/2025 | ✅ minh bạch AI + human oversight + grounding/verify/audit | hồ sơ tự-phân-loại chính thức |
| PDPL 91/2025 | ✅ PII-redact + cascade erasure + org-isolation + no-training | A05/DPIA + DPA (luật sư rà) |

**Kết luận:** compliance-by-design — biện pháp kỹ thuật ĐÃ tích hợp; phần hồ sơ pháp lý là draft, kích hoạt khi
onboard khách production. Đây vừa là nghĩa vụ vừa là **rào cản cạnh tranh** (ít đối thủ VN công bố posture này).
