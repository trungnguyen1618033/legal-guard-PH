from legalguard.config.container import build_service
from legalguard.domain.models import NegotiationPosition
from legalguard.domain.negotiation import _parse_round, negotiate_round
from legalguard.domain.tenants import default_org

ORG = default_org("VN")
SAMPLE = "Trọng tài tại Bắc Kinh. Thanh toán T/T sau 60 ngày. Kiểm định tại cảng đến."


def test_analyze_assigns_priority_and_strategy():
    res = build_service().analyze(SAMPLE, ORG, lang="vi",
                                  position=NegotiationPosition(leverage="weak", urgency="high"))
    # Mỗi rủi ro có priority hợp lệ (theo vị thế đàm phán).
    assert all(r["priority"] in ("must_fix", "negotiate", "acceptable") for r in res.risks)
    # Điều khoản trọng tài là must_fix (sống còn).
    assert any(r["priority"] == "must_fix" for r in res.risks)
    # Có chiến lược tổng thể (final message của agent).
    assert res.strategy and "vị thế" in res.strategy.lower()


def test_strategy_mentions_leverage():
    res = build_service().analyze(SAMPLE, ORG, lang="vi",
                                  position=NegotiationPosition(leverage="strong"))
    assert "strong" in res.strategy.lower()      # chiến lược phản ánh vị thế đầu vào


# ---- Đàm phán đa phiên (multi-turn) ----
class _LLM:
    name = "qwen"

    def __init__(self, available=True, out=""):
        self._a, self._out = available, out

    @property
    def available(self):
        return self._a

    def complete(self, prompt, *, system=None):
        return self._out


def test_parse_round_json_block_and_coerce_status():
    raw = '```json\n{"assessment":"đối tác giữ phạt 12%","strategy":"ép về 8%","reply_vi":"Chào","reply_en":"Hi","status":"continue"}\n```'
    d = _parse_round(raw)
    assert d["assessment"].startswith("đối tác giữ") and d["reply_en"] == "Hi" and d["status"] == "continue"
    assert _parse_round('{"assessment":"x","status":"bừa"}')["status"] == "continue"   # ép enum
    assert _parse_round("không phải json")["assessment"] == "không phải json"           # fallback


def test_negotiate_round_offline_safe():
    r = negotiate_round(_LLM(available=False), deal_context="phạt 15%", partner_message="giảm còn 12%")
    assert r.grounded is False and r.status == "continue" and "HOÀN THIỆN" in r.assessment


def test_negotiate_round_parses_llm_and_status():
    out = '{"assessment":"đối tác nhượng phạt còn 8%","strategy":"chốt","reply_vi":"Đồng ý","reply_en":"Agreed","status":"close"}'
    r = negotiate_round(_LLM(out=out), deal_context="phạt 15% trái Đ.301", partner_message="OK giảm 8%",
                        position=NegotiationPosition(protected_party="Bên Mua", leverage="weak"))
    assert r.grounded is True and r.status == "close" and r.reply_en == "Agreed"
