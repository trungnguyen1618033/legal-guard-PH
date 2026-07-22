"""Cache tra cứu (lookup): hỏi lặp → trả tức thì + không gọi LLM lần 2."""
from legalguard.domain.analysis import AnalysisService
from legalguard.domain.models import Snippet
from legalguard.domain.tenants import Organization


class _CountLLM:
    name = "qwen"

    def __init__(self):
        self.calls = 0
        self.last_prompt = ""

    @property
    def available(self):
        return True

    def complete(self, prompt, *, system=None):
        self.calls += 1
        self.last_prompt = prompt
        return f"**Trả lời:** đáp án {self.calls}"


class _Ret:
    def retrieve(self, query, top_k=5):
        return [Snippet(source="luat.md#Điều 1", text="nội dung điều luật", score=1.0)]


class _KB:
    def for_org(self, org, *, rerank=True, overlay=True):
        return _Ret()


def _svc(size=256):
    llm = _CountLLM()
    svc = AnalysisService(reasoner=llm, kb=_KB(),
                          nli_verification=False, lookup_cache_size=size)
    return svc, llm


_ORG = Organization(id="acme", country="VN")


def test_cache_hit_skips_second_llm_call():
    svc, llm = _svc()
    a1, _ = svc.lookup("Mức phạt vi phạm tối đa bao nhiêu?", _ORG)
    a2, _ = svc.lookup("Mức phạt vi phạm tối đa bao nhiêu?", _ORG)
    assert llm.calls == 1              # lần 2 lấy từ cache
    assert a1 == a2                    # cache hit trả y hệt (kèm cả dòng độ tin cậy)
    assert a1.startswith("**Trả lời:** đáp án 1")   # đáp án lần 1 (không tính lại)


def test_cache_normalizes_question():
    svc, llm = _svc()
    svc.lookup("Mức Phạt Vi Phạm?", _ORG)
    svc.lookup("  mức phạt vi phạm?  ", _ORG)   # khác hoa/khoảng trắng → cùng key
    assert llm.calls == 1


def test_cache_distinct_questions_each_computed():
    svc, llm = _svc()
    svc.lookup("Câu hỏi một?", _ORG)
    svc.lookup("Câu hỏi hai?", _ORG)
    assert llm.calls == 2


def test_cache_disabled_size_zero():
    svc, llm = _svc(size=0)
    svc.lookup("Cùng một câu?", _ORG)
    svc.lookup("Cùng một câu?", _ORG)
    assert llm.calls == 2              # tắt cache → gọi LLM mỗi lần


def test_cache_lru_evicts_oldest():
    svc, llm = _svc(size=1)
    svc.lookup("Câu A?", _ORG)         # cache: A
    svc.lookup("Câu B?", _ORG)         # vượt size 1 → đẩy A ra, cache: B
    svc.lookup("Câu A?", _ORG)         # A đã bị evict → tính lại
    assert llm.calls == 3


def test_cache_isolated_per_org():
    svc, llm = _svc()
    svc.lookup("Cùng câu hỏi?", Organization(id="acme", country="VN"))
    svc.lookup("Cùng câu hỏi?", Organization(id="other", country="VN"))
    assert llm.calls == 2              # khác org → cache riêng


def test_lookup_redacts_pii_before_llm():
    # Câu hỏi chứa PII (email/sđt) → prompt gửi LLM phải đã REDACT (không lọt PII).
    svc, llm = _svc()
    svc.lookup("Hợp đồng với a@example.com sđt 0912345678 có hợp lệ không?", _ORG)
    assert "a@example.com" not in llm.last_prompt and "0912345678" not in llm.last_prompt
    assert "[EMAIL]" in llm.last_prompt and "[SỐ]" in llm.last_prompt


class _SemLLM(_CountLLM):
    """Reasoner CÓ embed: vector theo TỪ KHÓA → câu diễn đạt khác nhưng cùng ý → cosine cao (semantic hit)."""
    _KWS = ["phạt", "thương mại", "giao hàng", "lãi"]

    def embed(self, texts):
        out = []
        for t in texts:
            tl = t.lower()
            out.append([1.0 if k in tl else 0.0 for k in self._KWS] or [0.0])
        return out


def _sem_svc(size=256):
    llm = _SemLLM()
    return AnalysisService(reasoner=llm, kb=_KB(), nli_verification=False, lookup_cache_size=size), llm


def test_semantic_cache_hit_near_duplicate():
    svc, llm = _sem_svc()
    svc.lookup("Mức phạt vi phạm hợp đồng thương mại tối đa?", _ORG)
    # câu diễn đạt KHÁC (khác key exact) nhưng cùng ý 'phạt/thương mại' → cosine=1.0 ≥ 0.95 → hit
    a2, _ = svc.lookup("Phạt hợp đồng thương mại cao nhất là bao nhiêu phần trăm?", _ORG)
    assert llm.calls == 1                 # KHÔNG gọi LLM lần 2 (semantic hit)
    assert a2.startswith("**Trả lời:** đáp án 1")


def test_semantic_cache_isolated_per_org():
    svc, llm = _sem_svc()
    svc.lookup("Mức phạt thương mại tối đa?", Organization(id="acme", country="VN"))
    # org KHÁC, câu gần trùng → PHẢI KHÔNG hit (cô lập scope) → gọi LLM lại
    svc.lookup("Phạt thương mại cao nhất?", Organization(id="other", country="VN"))
    assert llm.calls == 2


def test_semantic_cache_distinct_topics_no_hit():
    svc, llm = _sem_svc()
    svc.lookup("Mức phạt thương mại tối đa?", _ORG)        # vector [1,1,0,0]
    svc.lookup("Thời hạn giao hàng bao lâu?", _ORG)        # vector [0,0,1,0] → cosine 0 → không hit
    assert llm.calls == 2


def test_lookup_keeps_year_for_point_in_time():
    # Năm KHÔNG bị redact → câu point-in-time vẫn giữ "2020" để LLM suy luận đúng.
    svc, llm = _svc()
    svc.lookup("Năm 2020 văn bản nào về hóa đơn còn hiệu lực?", _ORG)
    assert "2020" in llm.last_prompt


def test_hybrid_routes_point_in_time_to_flagship():
    # Câu có mốc thời gian (năm/ngày) → dùng reasoner (flagship); câu thường → lookup_llm (nhanh).
    fast = _CountLLM()
    flagship = _CountLLM()
    svc = AnalysisService(reasoner=flagship, kb=_KB(),
                          nli_verification=False, lookup_llm=fast)
    svc.lookup("Mức phạt vi phạm tối đa?", _ORG)          # thường → fast
    svc.lookup("Năm 2020 văn bản nào còn hiệu lực?", _ORG)  # point-in-time → flagship
    svc.lookup("Quy định tại 01/06/2022 ra sao?", _ORG)    # có ngày → flagship
    assert fast.calls == 1 and flagship.calls == 2
