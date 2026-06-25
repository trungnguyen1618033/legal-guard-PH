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

## Độ phủ hiện tại

**`VN/fallback_matrix.md`** — 12 nhóm điều khoản (ma trận chiến thuật, chunk theo block):
trọng tài · luật áp dụng · thanh toán T/T · đặt cọc · kiểm định · phạt một chiều · chấm dứt ·
bất khả kháng · bảo mật/độc quyền · khiếu nại/bảo hành · dung sai · tỷ giá.

**`VN/blds_2015_hop_dong.md`** — Bộ luật Dân sự 2015 (Luật 91/2015/QH13, còn hiệu lực), chế định hợp đồng:
đặt cọc (Đ.328), trách nhiệm vi phạm nghĩa vụ (Đ.351), lãi chậm trả (Đ.357), bồi thường (Đ.360), phạt vi phạm
(Đ.418 — *không* trần 8% như Luật TM), thiệt hại được bồi thường (Đ.419). Bổ trợ Luật TM 2005 cho phân tích HĐ.

**`VN/luat_thuong_mai_2005_che_tai.md`** — văn bản luật thật (Luật Thương mại 2005, Mục chế tài:
Đ.292/294/295/297/300/301/302/306/307). Đây là file **chunk theo Điều/Khoản** (`legal_chunker.py`):
mỗi Điều = 1 chunk, source mang nhãn `#Điều 300`; Điều dài tự tách theo khoản. Ground thẳng các mục
phạt-một-chiều / bất-khả-kháng của fallback_matrix; đồng thời chứa **dẫn chiếu chéo** (Đ.300→Đ.294,
Đ.301→Đ.266) — vật liệu cho Phase 2 citation-graph (`docs/internal/legal-search-expansion.md`).
> ⚠️ Nguyên văn từ Cổng TTĐT Chính phủ — luật sư cần đối chiếu bản chính thức trước khi dùng tư vấn.

**Lát cắt hóa đơn điện tử (mảng thuế) — có quan hệ thời gian THẬT để test in-force/temporal:**
- `VN/tt_39_2014_hoa_don_HET_HIEU_LUC.md` — **status: expired** (hết hiệu lực 1/7/2022, bị thay bởi NĐ 123/2020 + TT 78/2021).
- `VN/nd_123_2020_hoa_don.md` — status: in_force (nhưng `amended_by: 70/2025`).
- `VN/nd_70_2025_sua_doi_hoa_don.md` — status: in_force (`amends: 123/2020`, hiệu lực 1/6/2025).
> Đây là bộ minh chứng in-force filter: query "thời điểm lập hóa đơn" thì TT 39/2014 (hết hiệu lực)
> rank #1 khi tắt lọc → bị loại khi bật lọc. Đo bằng `evaluation/legal_eval.py` (still-good-law accuracy).

| Trạng thái | Ý nghĩa |
|---|---|
| ✅ Có | Thực tiễn thương mại quốc tế phổ biến (an toàn để demo) |
| ⚠️ Cần luật sư | Bổ sung **trích dẫn luật VN cụ thể** + nuance địa phương; chốt bộ **15 tình huống** curated (§8) |

## Front-matter cho file luật (lọc hiệu lực)

File văn bản luật nên mở đầu bằng khối metadata máy-đọc (giữa hai dòng `---`) để hệ thống lọc theo
hiệu lực. Thiếu khối này → coi như **còn hiệu lực** (`in_force`).

```
---
doc_id: 36/2005/QH11
title: Luật Thương mại 2005 — Chế tài
doc_type: luat            # luat | nghi_dinh | thong_tu ...
status: in_force          # in_force = còn hiệu lực; expired/replaced = ẩn khỏi kết quả mặc định
effective_date: 2006-01-01
source_url: <link nguồn chính thức>
---
```

Mặc định retriever **chỉ trả văn bản `in_force`** (`InForceRetriever`); văn bản `expired`/`replaced`
chỉ hiện khi câu hỏi có ý định lịch sử ("bản cũ", "trước đây"...). Đây là lớp chống trả nhầm điều
luật đã hết hiệu lực.

## Cách mở rộng

- **Thêm tình huống:** thêm 1 block `## N. <Tên> [severity]` vào `VN/fallback_matrix.md` theo đúng 4 dòng.
- **Thêm văn bản luật:** thêm file `.md` có front-matter ở trên + thân chia theo `Điều N` (tự chunk theo Điều/Khoản).
- **Thêm quốc gia:** tạo `knowledge_base/<CC>/` + entry trong `legalguard/domain/tenants.py`.
- **Nâng retrieval:** khi KB lớn, đổi `FileKnowledgeBaseProvider` → adapter vector DB (pgvector/Milvus),
  domain không đổi (Ports & Adapters).
