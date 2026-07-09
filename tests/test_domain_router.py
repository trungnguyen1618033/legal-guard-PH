"""Domain-scoped retrieval: router tất định + wrapper an-toàn-mặc-định (kb-expansion-plan trụ cột 1).

Hợp đồng an toàn PHẢI giữ: (1) câu không match domain → hành vi cũ nguyên vẹn; (2) file không nhãn
`domain:` luôn được giữ; (3) trong-domain quá mỏng → fallback kết quả gốc (không bao giờ trả kém hơn cũ)."""
from legalguard.adapters.outbound.domain_router import (
    DomainScopedRetriever,
    load_file_domains,
    route,
)
from legalguard.domain.models import Snippet


def test_route_picks_matching_domains_top2():
    # câu đa-lĩnh-vực: cả thương mại lẫn dân sự cùng match → giữ CẢ HAI (thứ tự hòa-điểm không quan trọng)
    assert set(route("Mức phạt vi phạm hợp đồng thương mại tối đa?")) == {"thuong_mai", "dan_su"}
    assert route("Thời hạn thử việc tối đa bao lâu?") == ["lao_dong"]
    assert route("Ly hôn thì tài sản chung chia thế nào?") == ["hon_nhan"]


def test_route_no_match_returns_empty():
    assert route("Thời tiết hôm nay thế nào?") == []       # câu ngoài pháp lý → [] → hành vi cũ


def test_load_file_domains_reads_frontmatter(tmp_path):
    kb = tmp_path / "VN"
    kb.mkdir()
    (kb / "a.md").write_text("---\ndomain: lao_dong\ntitle: x\n---\nĐiều 1. Nội dung", encoding="utf-8")
    (kb / "b.md").write_text("---\ntitle: y\n---\nĐiều 1. Nội dung", encoding="utf-8")   # không nhãn
    m = load_file_domains(str(tmp_path), "VN")
    assert m == {"a.md": "lao_dong"}                        # b.md vắng mặt = luôn được giữ


class _FakeBase:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def retrieve(self, query, top_k=4):
        self.calls.append(top_k)
        return self.hits[:top_k]


def _kb(tmp_path):
    kb = tmp_path / "VN"
    kb.mkdir()
    (kb / "ld.md").write_text("---\ndomain: lao_dong\n---\nĐiều 1.", encoding="utf-8")
    (kb / "hn.md").write_text("---\ndomain: hon_nhan\n---\nĐiều 1.", encoding="utf-8")
    (kb / "matrix.md").write_text("---\n---\n## tình huống", encoding="utf-8")           # không nhãn
    return str(tmp_path)


def test_scoped_filters_other_domains_keeps_unlabeled(tmp_path):
    hits = [Snippet("hn.md#Điều 5", "hôn nhân", 0.9), Snippet("ld.md#Điều 111", "nghỉ", 0.8),
            Snippet("matrix.md#1", "tactic", 0.7), Snippet("ld.md#Điều 35", "nghỉ việc", 0.6),
            Snippet("hn.md#Điều 7", "x", 0.5)]
    r = DomainScopedRetriever(_FakeBase(hits), _kb(tmp_path), "VN", fetch_mult=2)
    got = r.retrieve("Thời hạn thử việc và tiền lương?", top_k=2)   # → lao_dong
    assert [g.source for g in got] == ["ld.md#Điều 111", "matrix.md#1"]  # bỏ hn.md; giữ file không nhãn


def test_scoped_no_domain_match_passthrough(tmp_path):
    base = _FakeBase([Snippet("hn.md#Điều 5", "x", 0.9)])
    r = DomainScopedRetriever(base, _kb(tmp_path), "VN")
    got = r.retrieve("câu hỏi chung chung không lĩnh vực", top_k=3)
    assert base.calls == [3] and [g.source for g in got] == ["hn.md#Điều 5"]   # gọi thẳng top_k gốc


def test_scoped_thin_indomain_leads_then_pads(tmp_path):
    # Pool in-domain mỏng (chỉ 1 hit lao_dong < top_k=2): in-domain LÊN ĐẦU, PAD đuôi bằng hit ngoài-domain
    # → KHÔNG trả mỏng hơn top_k, NHƯNG crowder ngoài-domain KHÔNG đẩy in-domain ra (lỗi cũ: trả nguyên hits).
    hits = [Snippet("hn.md#Điều 5", "a", 0.9), Snippet("hn.md#Điều 7", "b", 0.8),
            Snippet("ld.md#Điều 111", "c", 0.7)]
    r = DomainScopedRetriever(_FakeBase(hits), _kb(tmp_path), "VN", fetch_mult=2)
    got = r.retrieve("Thời hạn thử việc?", top_k=2)          # lao_dong chỉ có 1 hit
    assert [g.source for g in got] == ["ld.md#Điều 111", "hn.md#Điều 5"]   # in-domain đầu, rồi pad
