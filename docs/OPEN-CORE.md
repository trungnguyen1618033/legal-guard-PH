# Open-Core — Public (MIT) vs Private boundary

*English summary (Vietnamese full version below.)*

Legal Guard is **open-core**. The entire **engine is MIT-licensed and open** (this repo) and runs
end-to-end on the included public legal corpus + a 12-situation sample fallback matrix — this is the
hackathon deliverable. The **proprietary layer** is the startup's moat and is gitignored, layering onto
the engine at deploy time **with no code change**:

| Asset | Location (gitignored) | How it applies |
|---|---|---|
| Deep party-aware tactics, premium/per-client KB | `knowledge_base/_orgs/<org_id>/*.md` | auto-overlaid by `for_org(org)` during `/analyze` |
| Full lawyer-verified evaluation set | `evaluation/_private/` | private eval run |
| Strategy / GTM / pitch / lawyer kit | `docs/internal/` | internal docs |
| Deal-outcome flywheel data | runtime DB (`data/`, Postgres) | accumulates with use |

**Why**: the RAG engine is commodity (open it → transparency + technical credit, lose nothing); the KB
is public law (keeping it private protects little); the real moat is the *data that grows* (flywheel,
curated tactics, lawyer-verified answers), GTM, and execution — none of which a competitor can clone
from the code alone. Git history was scanned: **no secrets or internal docs were ever committed**, so
the repo is safe to make public without a history rewrite.

To deploy the full (business) build: clone the public repo, drop private data into the gitignored paths
above, run as usual — the engine loads the overlay automatically.

---

# Open-Core — ranh giới Public (MIT) vs Private (moat)

Legal Guard theo mô hình **open-core**: toàn bộ **engine** mã nguồn mở (MIT) — đủ chạy end-to-end,
là deliverable cho Qwen Cloud Hackathon. Phần **dữ liệu cao cấp + vận hành** là tài sản riêng của
startup, phủ lên engine qua cơ chế overlay sẵn có (KHÔNG cần sửa code).

## ✅ PUBLIC (MIT — trong repo này)
- **Engine**: `legalguard/` (domain hexagonal, agent ReAct, RAG, verification, regulatory, runs…),
  adapters (Qwen/Gemini/KB/parser), HTTP API, MCP, observability.
- **Frontend**: `frontend/` (Next.js) + `web/*.html`.
- **Hạ tầng**: Docker, Alembic migrations, `scripts/` (backup/restore), CI.
- **Tri thức nền**: `knowledge_base/VN/*` — văn bản **luật công khai** (verbatim) + đồ thị hiệu lực;
  `knowledge_base/VN/fallback_matrix.md` — **12 tình huống generic** (thực tiễn thương mại phổ biến).
- **Eval mẫu**: `evaluation/*_golden.json` — bộ kiểm thử minh chứng kỷ luật đo lường.

## 🔒 PRIVATE (moat — gitignored, KHÔNG commit)
Phủ lên public khi deploy startup; lớn dần theo thời gian. Mất public ≠ mất moat — moat là phần dưới:

| Tài sản | Vị trí (gitignored) | Cơ chế áp dụng |
|---|---|---|
| **Tactic SÂU party-aware** (dẫn điều luật VN cụ thể, fallback nhiều tầng theo vị thế) | `knowledge_base/_orgs/<org_id>/*.md` | `for_org(org)` tự overlay khi `/analyze` (OverlayRetriever) |
| **KB cao cấp / theo khách** | `knowledge_base/_orgs/<org_id>/*.md` | như trên |
| **Golden lawyer-verified ĐẦY ĐỦ** (đáp án đã thẩm định = đòn bẩy lòng tin) | `evaluation/_private/` | eval riêng trỏ vào |
| **Chiến lược / GTM / pitch / gói luật sư** | `docs/internal/` | tài liệu nội bộ |
| **Dữ liệu flywheel** (win-rate deal thật) | DB runtime (`data/`, Postgres) | tích lũy khi dùng |

## Vì sao tách thế này
- **RAG/engine đã commodity** → công khai để minh bạch + ăn điểm kỹ thuật cuộc thi, không mất gì.
- **KB là luật công khai** → giữ riêng bảo vệ rất ít, lại giảm độ tin demo.
- **Moat thật = dữ liệu lớn dần** (flywheel, tactic curated, golden lawyer-verified) + GTM + thực thi —
  những thứ đối thủ KHÔNG clone được dù có toàn bộ code.

## Cách deploy bản startup (đầy đủ moat)
1. Clone repo (public).
2. Đặt dữ liệu private vào các đường dẫn gitignored ở trên (vd `knowledge_base/_orgs/default/premium_tactics.md`).
3. Chạy như thường — engine tự nạp overlay; không sửa dòng code nào.

> Lịch sử git đã được kiểm: KHÔNG chứa secret/tài liệu nội bộ → repo an toàn để public.
