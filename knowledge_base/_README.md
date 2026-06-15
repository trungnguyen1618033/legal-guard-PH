# Knowledge Base — thiết kế & độ phủ

KB là **nguồn tri thức pháp lý** mà agent truy xuất (RAG) để grounding phân tích.
Đây là **moat** của sản phẩm (`docs/internal/legal-guard.md` §1) — chất lượng KB quyết định chất lượng output.

## Nguyên tắc thiết kế

1. **Theo tenant (quốc gia):** mỗi tenant một thư mục `knowledge_base/<CC>/` (VN, ID, TH...).
   Thêm nước = thêm thư mục, không sửa code (xem `docs/architecture.md`).
2. **KB là tiếng Việt (nguồn), output song ngữ:** ngôn ngữ KB ≠ ngôn ngữ trả lời. Agent đọc KB
   tiếng Việt và xuất EN (mặc định) hoặc VI tùy `lang`. Câu `EN:` trong mỗi mục là mẫu gửi đối tác.
3. **Mỗi tình huống = 1 đơn vị retrieval hoàn chỉnh:** `Dấu hiệu → Rủi ro → Fallback → EN`.
   Retriever chunk theo block (cách nhau bằng dòng trống) nên giữ nguyên 1 mục = 1 chunk.
4. **Mức độ rủi ro `[high|medium|low]`** ghi ngay tiêu đề mục để agent quyết định human-review.

## Độ phủ hiện tại (`VN/fallback_matrix.md`)

12 nhóm điều khoản: trọng tài · luật áp dụng · thanh toán T/T · đặt cọc · kiểm định ·
phạt một chiều · chấm dứt · bất khả kháng · bảo mật/độc quyền · khiếu nại/bảo hành ·
dung sai · tỷ giá.

| Trạng thái | Ý nghĩa |
|---|---|
| ✅ Có | Thực tiễn thương mại quốc tế phổ biến (an toàn để demo) |
| ⚠️ Cần luật sư | Bổ sung **trích dẫn luật VN cụ thể** + nuance địa phương; chốt bộ **15 tình huống** curated (§8) |

## Cách mở rộng

- **Thêm tình huống:** thêm 1 block `## N. <Tên> [severity]` vào `VN/fallback_matrix.md` theo đúng 4 dòng.
- **Thêm quốc gia:** tạo `knowledge_base/<CC>/` + entry trong `legalguard/domain/tenants.py`.
- **Nâng retrieval:** khi KB lớn, đổi `FileKnowledgeBaseProvider` → adapter vector DB (pgvector/Milvus),
  domain không đổi (Ports & Adapters).
