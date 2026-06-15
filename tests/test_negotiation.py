from legalguard.config.container import build_service
from legalguard.domain.models import NegotiationPosition
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
