"""Domain-scoped retrieval — định tuyến truy vấn theo LĨNH VỰC pháp luật trước khi xếp hạng.

Vì sao (đo được, docs/internal/ingest-eval-gated-process.md): KB phẳng = mọi chunk cạnh tranh TOÀN CỤC
với mọi truy vấn → thêm 30 VB xây dựng làm rớt câu hỏi hôn nhân (không liên quan); thêm 250 VB → 98%→82%.
pgvector chỉ giải latency, KHÔNG giải cạnh-tranh-toàn-cục. Giải pháp gốc: câu hỏi CHỈ tìm trong nhóm văn
bản của lĩnh vực liên quan → domain mới về cấu trúc không thể pha loãng truy vấn domain cũ → mở khóa
scale KB (kb-expansion-plan.md trụ cột 1).

Thiết kế AN TOÀN-MẶC-ĐỊNH (bật qua `DOMAIN_SCOPED_RETRIEVAL`, default OFF):
- Router TẤT ĐỊNH (đếm keyword theo domain, không LLM, không network) → top-2 domain.
- KHÔNG match domain nào → trả nguyên kết quả base (hành vi cũ) — câu hỏi chung chung không thể tệ đi.
- File KHÔNG có nhãn `domain:` (vd fallback_matrix, overlay tactics) → luôn được giữ.
- Lọc trong-domain quá MỎNG (< top_k) → fallback kết quả gốc (không bao giờ trả ít/kém hơn hành vi cũ).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from legalguard.domain.models import Snippet
from legalguard.domain.ports import KnowledgeBasePort

# Router keyword theo domain — TẤT ĐỊNH, tiếng Việt thường gặp trong câu hỏi (so khớp substring trên
# text đã NFC+lower). Domain khớp = có ≥1 keyword; lấy top-2 theo SỐ keyword khớp (câu đa-lĩnh-vực
# vd "phạt vi phạm" chạm cả thương mại lẫn dân sự → giữ cả hai).
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "thuong_mai": ["phạt vi phạm", "chế tài", "thương mại", "buộc thực hiện", "tạm ngừng thực hiện",
                   "đình chỉ thực hiện", "hủy bỏ hợp đồng", "miễn trách nhiệm", "chậm thanh toán"],
    "dan_su": ["dân sự", "đặt cọc", "lãi suất", "vay", "phạt vi phạm", "bồi thường", "vô hiệu",
               "nghĩa vụ trả", "chậm trả", "hợp đồng"],
    "hoa_don": ["hóa đơn", "chứng từ", "xuất hóa đơn"],
    "lao_dong": ["lao động", "thử việc", "sa thải", "nghỉ việc", "làm thêm giờ", "tiền lương",
                 "trợ cấp thôi việc", "kỷ luật"],
    "doanh_nghiep": ["doanh nghiệp", "cổ phần", "góp vốn", "điều lệ", "trách nhiệm hữu hạn",
                     "người đại diện theo pháp luật", "cổ đông"],
    "dau_tu": ["đầu tư", "nhà đầu tư nước ngoài", "ưu đãi đầu tư", "ngành nghề kinh doanh có điều kiện"],
    "so_huu_tri_tue": ["sở hữu trí tuệ", "nhãn hiệu", "bản quyền", "quyền tác giả", "sáng chế",
                       "kiểu dáng công nghiệp"],
    "du_lieu_ca_nhan": ["dữ liệu cá nhân", "bảo vệ dữ liệu", "chủ thể dữ liệu"],
    "hon_nhan": ["hôn nhân", "ly hôn", "vợ chồng", "tài sản chung", "kết hôn"],
    "dat_dai": ["đất đai", "quyền sử dụng đất", "sổ đỏ", "thuê đất", "giấy chứng nhận quyền sử dụng"],
    "trong_tai": ["trọng tài", "phán quyết", "thỏa thuận trọng tài", "hội đồng trọng tài"],
    "xay_dung": ["xây dựng", "thi công", "nhà thầu", "xây lắp", "nghiệm thu công trình",
                 "giấy phép xây dựng", "công trình xây dựng"],
}


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", (s or "").lower())


def route(query: str, keywords: dict[str, list[str]] | None = None, top_n: int = 2) -> list[str]:
    """Truy vấn → top-N domain theo số keyword khớp. [] = không match (giữ hành vi cũ). Thuần, tất định."""
    q = _norm(query)
    hits = {d: sum(1 for k in kws if k in q) for d, kws in (keywords or DOMAIN_KEYWORDS).items()}
    ranked = sorted(((d, n) for d, n in hits.items() if n > 0), key=lambda x: (-x[1], x[0]))
    return [d for d, _ in ranked[:top_n]]


def load_file_domains(base_dir: str, tenant: str) -> dict[str, str]:
    """filename → domain (từ front-matter `domain:`). File không nhãn → vắng mặt (= luôn được giữ)."""
    out: dict[str, str] = {}
    tenant_dir = Path(base_dir) / tenant
    if not tenant_dir.exists():
        return out
    for md in sorted(tenant_dir.glob("*.md")):
        head = md.read_text(encoding="utf-8")[:600]
        m = re.search(r"^domain:\s*(\S+)", head, re.MULTILINE)
        if m:
            out[md.name] = m.group(1).strip()
    return out


class DomainScopedRetriever:
    """Bọc retriever base: lọc ứng viên theo domain của truy vấn (fetch rộng → lọc → top_k).

    Đặt NGAY TRÊN base hybrid (trước in_force/rerank/closure) — thu hẹp vũ trụ ứng viên theo lĩnh vực,
    các lớp trên (hiệu lực/rerank/dẫn chiếu) hoạt động bình thường trong vũ trụ đã thu hẹp."""

    def __init__(self, base: KnowledgeBasePort, base_dir: str, tenant: str,
                 fetch_mult: int = 6, keywords: dict[str, list[str]] | None = None) -> None:
        self._base = base
        self._file_domain = load_file_domains(base_dir, tenant)
        self._fetch_mult = fetch_mult
        self._keywords = keywords or DOMAIN_KEYWORDS

    @staticmethod
    def _file_of(source: str) -> str:
        return source.split("#", 1)[0]                     # 'file.md#Điều 5' → 'file.md'

    def retrieve(self, query: str, top_k: int = 4) -> list[Snippet]:
        domains = route(query, self._keywords)
        if not domains:                                    # câu chung chung → hành vi cũ nguyên vẹn
            return self._base.retrieve(query, top_k)
        hits = self._base.retrieve(query, top_k * self._fetch_mult)
        allowed = set(domains)
        scoped_idx: set[int] = set()
        scoped: list[Snippet] = []
        for i, h in enumerate(hits):
            fd = self._file_domain.get(self._file_of(h.source))     # None = file không nhãn → luôn giữ
            if fd in allowed or fd is None:
                scoped.append(h)
                scoped_idx.add(i)
        if not scoped:                                     # KHÔNG hit nào trong domain → fallback base (an toàn)
            return hits[:top_k]
        # In-domain LÊN ĐẦU; nếu chưa đủ top_k thì PAD bằng hit ngoài-domain (giữ recall, KHÔNG để crowder
        # ngoài-domain đẩy in-domain ra khỏi top_k — lỗi cũ: pool in-domain mỏng → trả nguyên hits chưa lọc).
        rest = [h for i, h in enumerate(hits) if i not in scoped_idx]
        return (scoped + rest)[:top_k]
