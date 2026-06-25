from legalguard.adapters.outbound.knowledge_base import build_retriever
from legalguard.domain.analysis import _attach_legal_basis, _legal_citation
from legalguard.domain.models import Fallback, Risk
from legalguard.domain.verification import nli_supports


class _Judge:
    name = "qwen"

    def __init__(self, out="YES", available=True):
        self._out, self._a = out, available

    @property
    def available(self):
        return self._a

    def complete(self, prompt, *, system=None):
        return self._out


def test_nli_supports_yes_no_none():
    assert nli_supports("claim", "evidence", _Judge("YES")) is True
    assert nli_supports("claim", "evidence", _Judge("NO")) is False
    assert nli_supports("claim", "evidence", _Judge("xyzabc")) is None      # đáp mơ hồ → None
    assert nli_supports("claim", "evidence", _Judge("YES", available=False)) is None  # offline → None


def test_legal_citation_nli_rejects_unsupported():
    r = build_retriever("knowledge_base", "VN", strategy="keyword", in_force=True)
    # judge nói NO → KHÔNG gắn dù có điều luật khớp thuật ngữ (chống citation không hậu thuẫn)
    assert _legal_citation("phạt vi phạm 15% giá trị", r, _Judge("NO")) == ""
    # judge nói YES → vẫn gắn Điều 301
    assert "Điều 301" in _legal_citation("phạt vi phạm 15% giá trị", r, _Judge("YES"))


def _r():
    return build_retriever("knowledge_base", "VN", strategy="keyword", in_force=True)


def test_legal_basis_grounds_relevant_article():
    # Rủi ro phạt vi phạm → căn cứ Điều 301 Luật TM 2005 (mức phạt không quá 8%).
    assert "Điều 301" in _legal_citation("Điều khoản phạt vi phạm 15% giá trị hợp đồng", _r())


def test_legal_basis_grounds_fallback_topic():
    # Đề nghị về bồi thường → Điều 302; về hóa đơn → điều luật hóa đơn.
    assert "Điều 302" in _legal_citation("bồi thường thiệt hại tổn thất thực tế trực tiếp", _r())
    assert "hoa_don" in _legal_citation("thời điểm lập hóa đơn khi bán hàng hóa", _r())


def test_legal_basis_skips_irrelevant_no_spurious_citation():
    # Không có điều luật khớp trong KB → KHÔNG gắn căn cứ bừa (tránh "căn cứ lạc" = sai như bịa).
    assert _legal_citation("trọng tài tại Bắc Kinh nước ngoài", _r()) == ""


def test_legal_basis_only_law_articles_in_force():
    # Căn cứ phải là chunk cấp điều luật (#Điều), không phải ma trận chiến thuật.
    basis = _legal_citation("phạt vi phạm hợp đồng bồi thường thiệt hại", _r())
    assert basis == "" or "#Điều" in basis


class _CountingRetriever:
    def __init__(self):
        self.calls = 0

    def retrieve(self, query, top_k=4):
        self.calls += 1
        return []


def test_attach_legal_basis_caches_per_clause():
    # Risk + fallback CÙNG clause → chỉ tra KB 1 lần (cache), không 2 (giảm cost embedding).
    risks = [Risk(clause="Phạt vi phạm", risk="phạt 15%", severity="high")]
    fbs = [Fallback(clause="Phạt vi phạm", suggestion="giảm về 8%")]
    r = _CountingRetriever()
    _attach_legal_basis(risks, fbs, r)
    assert r.calls == 1                      # 2 mục cùng clause → 1 lần tra


def test_attach_legal_basis_distinct_clauses_each_queried():
    risks = [Risk(clause="A", risk="x", severity="low"),
             Risk(clause="B", risk="y", severity="low")]
    r = _CountingRetriever()
    _attach_legal_basis(risks, [], r)
    assert r.calls == 2                       # 2 clause khác nhau → 2 lần


def test_overlay_respects_in_force(tmp_path):
    # Overlay riêng công ty có văn bản hết hiệu lực → cũng bị lọc khi in_force bật.
    from legalguard.adapters.outbound.knowledge_base import FileKnowledgeBaseProvider
    from legalguard.domain.tenants import Organization
    vn = tmp_path / "VN"
    vn.mkdir()
    (vn / "nuoc.md").write_text("Quy định quốc gia về thuế suất ưu đãi.", encoding="utf-8")
    orgdir = tmp_path / "_orgs" / "acme"
    orgdir.mkdir(parents=True)
    (orgdir / "noi_bo.md").write_text(
        "---\nstatus: expired\n---\nĐiều 1. Chính sách thuế suất cũ\nĐã hết hiệu lực.", encoding="utf-8")
    prov = FileKnowledgeBaseProvider(str(tmp_path), in_force=True)
    hits = prov.for_org(Organization(id="acme", country="VN")).retrieve("thuế suất", top_k=5)
    assert not any("noi_bo" in h.source for h in hits)      # overlay hết hiệu lực bị lọc
