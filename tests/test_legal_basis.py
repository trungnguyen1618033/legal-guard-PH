import pytest

from legalguard.adapters.outbound.knowledge_base import build_retriever
from legalguard.domain.analysis import _attach_legal_basis, _legal_citation
from legalguard.domain.models import Fallback, Risk
from legalguard.domain.verification import nli_supports

# --- Mini-KB cố định (trích VERBATIM) — cô lập test khỏi corpus thật.
# Lý do: các test _legal_citation từng VỠ 2 lần khi nạp thêm luật (ranking đổi). Pin vào
# mini-KB này → đo ĐÚNG hành vi grounding bất kể corpus lớn cỡ nào.
_LTM = """---
doc_id: 36/2005/QH11
title: Luật Thương mại 2005 — Chế tài trong thương mại
doc_type: luat
status: in_force
effective_date: 2006-01-01
---
Điều 301. Mức phạt vi phạm
Mức phạt đối với vi phạm nghĩa vụ hợp đồng hoặc tổng mức phạt đối với nhiều vi phạm do các bên thoả thuận trong hợp đồng, nhưng không quá 8% giá trị phần nghĩa vụ hợp đồng bị vi phạm, trừ trường hợp quy định tại Điều 266 của Luật này.

Điều 302. Bồi thường thiệt hại
1. Bồi thường thiệt hại là việc bên vi phạm bồi thường những tổn thất do hành vi vi phạm hợp đồng gây ra cho bên bị vi phạm.
2. Giá trị bồi thường thiệt hại bao gồm giá trị tổn thất thực tế, trực tiếp mà bên bị vi phạm phải chịu do bên vi phạm gây ra và khoản lợi trực tiếp mà bên bị vi phạm đáng lẽ được hưởng nếu không có hành vi vi phạm.
"""

_HOA_DON = """---
doc_id: 123/2020/NĐ-CP
title: Nghị định 123/2020/NĐ-CP — quy định về hóa đơn, chứng từ
doc_type: nghi_dinh
status: in_force
effective_date: 2022-07-01
---
Điều 9. Thời điểm lập hóa đơn
1. Thời điểm lập hóa đơn đối với bán hàng hóa (bao gồm cả bán tài sản nhà nước, tài sản tịch thu, sung quỹ nhà nước và bán hàng dự trữ quốc gia) là thời điểm chuyển giao quyền sở hữu hoặc quyền sử dụng hàng hóa cho người mua, không phân biệt đã thu được tiền hay chưa thu được tiền.
2. Thời điểm lập hóa đơn đối với cung cấp dịch vụ là thời điểm hoàn thành việc cung cấp dịch vụ không phân biệt đã thu được tiền hay chưa thu được tiền.
"""


@pytest.fixture(scope="module")
def mini_kb(tmp_path_factory):
    """Retriever trên mini-KB cố định (không dùng knowledge_base thật → không vỡ khi nạp luật)."""
    root = tmp_path_factory.mktemp("kb")
    vn = root / "VN"
    vn.mkdir()
    (vn / "luat_thuong_mai_2005_che_tai.md").write_text(_LTM, encoding="utf-8")
    (vn / "nd_123_2020_hoa_don.md").write_text(_HOA_DON, encoding="utf-8")
    return build_retriever(str(root), "VN", strategy="keyword", in_force=True)


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


def test_legal_citation_nli_rejects_unsupported(mini_kb):
    # judge nói NO → KHÔNG gắn dù có điều luật khớp thuật ngữ (chống citation không hậu thuẫn)
    assert _legal_citation("phạt vi phạm hợp đồng thương mại 15% giá trị", mini_kb, _Judge("NO")) == ""
    # judge nói YES → vẫn gắn Điều 301
    assert "Điều 301" in _legal_citation("phạt vi phạm hợp đồng thương mại 15% giá trị", mini_kb, _Judge("YES"))


def test_legal_basis_grounds_relevant_article(mini_kb):
    # Rủi ro phạt vi phạm → căn cứ Điều 301 Luật TM 2005 (mức phạt không quá 8%).
    assert "Điều 301" in _legal_citation("Điều khoản phạt vi phạm 15% giá trị hợp đồng", mini_kb)


def test_legal_basis_grounds_fallback_topic(mini_kb):
    # Đề nghị về bồi thường → Điều 302; về hóa đơn → điều luật hóa đơn.
    assert "Điều 302" in _legal_citation("bồi thường thiệt hại tổn thất thực tế trực tiếp", mini_kb)
    assert "hoa_don" in _legal_citation("thời điểm lập hóa đơn khi bán hàng hóa", mini_kb)


def test_legal_basis_skips_irrelevant_no_spurious_citation(mini_kb):
    # Không có điều luật khớp trong KB → KHÔNG gắn căn cứ bừa (tránh "căn cứ lạc" = sai như bịa).
    # Chủ đề thực sự ngoài KB (mini-KB không có luật đăng kiểm phương tiện giao thông).
    assert _legal_citation("đăng kiểm ô tô chở khách", mini_kb) == ""


def test_legal_basis_only_law_articles_in_force(mini_kb):
    # Căn cứ phải là chunk cấp điều luật (#Điều), không phải ma trận chiến thuật.
    basis = _legal_citation("phạt vi phạm hợp đồng bồi thường thiệt hại", mini_kb)
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
