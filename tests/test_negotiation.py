from legalguard.config.container import build_service
from legalguard.domain.models import NegotiationPosition
from legalguard.domain.negotiation import (
    NegotiationState,
    _merge_unique,
    _move_list,
    _parse_round,
    format_tactics_context,
    negotiate_round,
    screen_moves,
    should_walk_away,
)
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
        self.last_prompt = ""

    @property
    def available(self):
        return self._a

    def complete(self, prompt, *, system=None):
        self.last_prompt = prompt
        if isinstance(self._out, list):          # nhiều vòng: trả lần lượt từng output
            return self._out.pop(0)
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


# ---- Sổ nhượng-bộ (concession ledger) + guardrail walk-away ----
def test_merge_unique_dedups_case_insensitive():
    assert _merge_unique(["Phạt 8%"], ["phạt 8%", "Giao FOB"]) == ["Phạt 8%", "Giao FOB"]
    assert _merge_unique([], ["  ", "x"]) == ["x"]      # bỏ rỗng/khoảng trắng


def test_should_walk_away_pure():
    assert should_walk_away(True, True) is True        # red-line bị chặn + có BATNA → rút
    assert should_walk_away(True, False) is False      # bị chặn nhưng KHÔNG có BATNA → giữ đàm phán
    assert should_walk_away(False, True) is False      # không bị chặn → tiếp tục


def test_ledger_accumulates_across_rounds_without_losing_secured():
    r1out = ('{"assessment":"đối tác đồng ý phạt 8%","strategy":"tiếp","reply_vi":"a","reply_en":"a",'
             '"newly_secured":["phạt 8%"],"newly_conceded":["gia hạn giao 5 ngày"],'
             '"still_open":["địa điểm trọng tài"],"status":"continue"}')
    r2out = ('{"assessment":"đối tác đồng ý trọng tài VN","strategy":"chốt","reply_vi":"b","reply_en":"b",'
             '"newly_secured":["trọng tài tại VN"],"newly_conceded":[],'
             '"still_open":[],"status":"close"}')
    llm = _LLM(out=[r1out, r2out])
    r1 = negotiate_round(llm, deal_context="deal", partner_message="giảm 8%")
    r2 = negotiate_round(llm, deal_context="deal", partner_message="ok trọng tài VN", state=r1.state)
    # secured vòng 1 KHÔNG mất khi sang vòng 2 (chống 'quên' do cắt cụt) + tích lũy mục mới.
    assert "phạt 8%" in r2.state.secured and "trọng tài tại VN" in r2.state.secured
    assert r2.state.conceded == ["gia hạn giao 5 ngày"]     # giữ nhượng-bộ cũ, không nhân đôi
    assert r2.status == "close"


def test_guardrail_escalates_to_walk_away_on_blocked_red_line_with_batna():
    out = ('{"assessment":"đối tác từ chối bỏ điều khoản trọng tài Bắc Kinh","strategy":"tiếp",'
           '"reply_vi":"x","reply_en":"x","still_open":["trọng tài"],"red_line_blocked":true,'
           '"status":"continue"}')
    st = NegotiationState(red_lines=["trọng tài tại VN, không Bắc Kinh"])
    r = negotiate_round(_LLM(out=out), deal_context="d", partner_message="giữ Bắc Kinh",
                        position=NegotiationPosition(alternatives=True), state=st)
    assert r.walk_away_recommended is True and r.status == "walk_away"      # LLM nói continue → guardrail GHI ĐÈ
    assert "GUARDRAIL" in r.strategy


def test_no_walk_away_when_blocked_but_no_batna():
    out = ('{"assessment":"đối tác giữ Bắc Kinh","strategy":"tiếp","reply_vi":"x","reply_en":"x",'
           '"red_line_blocked":true,"status":"continue"}')
    r = negotiate_round(_LLM(out=out), deal_context="d", partner_message="giữ Bắc Kinh",
                        position=NegotiationPosition(alternatives=False),
                        state=NegotiationState(red_lines=["trọng tài VN"]))
    assert r.walk_away_recommended is False and r.status == "continue"      # không BATNA → không tự hại


# ---- Thang nhượng-bộ (concession ladder) + bảo vệ red-line ----
def test_move_list_coerces_dict_and_str():
    ms = _move_list([{"offer": "gia hạn giao 5 ngày", "in_return_for": "chốt phạt 8%"}, "giảm đặt cọc", {}, 3])
    assert ms[0]["offer"] == "gia hạn giao 5 ngày" and ms[0]["in_return_for"] == "chốt phạt 8%"
    assert ms[1] == {"offer": "giảm đặt cọc", "in_return_for": "", "why": ""}
    assert len(ms) == 2                                    # {} và 3 (không có offer) bị bỏ


def test_screen_moves_flags_offer_touching_red_line():
    moves = [{"offer": "Nhượng địa điểm trọng tài sang Bắc Kinh", "in_return_for": "chốt giá"},
             {"offer": "Gia hạn giao hàng thêm 5 ngày", "in_return_for": "chốt phạt 8%"}]
    out = screen_moves(moves, red_lines=["Trọng tài phải tại Việt Nam (VIAC)"])
    assert out[0]["near_red_line"] is True                 # đụng red-line trọng tài → gắn cờ
    assert out[1]["near_red_line"] is False                # gia hạn giao hàng → an toàn
    assert screen_moves([], ["x"]) == []


def test_negotiate_round_screens_next_moves_against_red_line():
    out = ('{"assessment":"a","strategy":"s","reply_vi":"v","reply_en":"e","status":"continue",'
           '"next_moves":[{"offer":"nhượng trọng tài sang Bắc Kinh","in_return_for":"chốt giá","why":"x"},'
           '{"offer":"giảm đặt cọc còn 10%","in_return_for":"chốt thời hạn","why":"y"}]}')
    r = negotiate_round(_LLM(out=out), deal_context="d", partner_message="m",
                        state=NegotiationState(red_lines=["Trọng tài tại Việt Nam"]))
    assert len(r.next_moves) == 2
    assert r.next_moves[0]["near_red_line"] is True and r.next_moves[1]["near_red_line"] is False


# ---- Living flywheel: win-rate lịch sử → context đàm phán ----
def test_format_tactics_context_sorts_and_skips_empty():
    wr = {"phạt vi phạm": {"rate": 0.8, "total": 5}, "trọng tài nước ngoài": {"rate": 0.2, "total": 4},
          "chưa có mẫu": {"rate": 0.0, "total": 0}}
    out = format_tactics_context(wr)
    assert "phạt vi phạm' đạt 80% (5 vụ)" in out                 # điểm cao lên trước
    assert out.index("80%") < out.index("20%")                   # sắp giảm dần theo rate
    assert "chưa có mẫu" not in out                              # total=0 bị loại
    assert format_tactics_context({}) == ""                      # rỗng → không thêm gì


def test_negotiate_round_injects_tactics_context_into_prompt():
    llm = _LLM(out='{"assessment":"a","status":"continue"}')
    negotiate_round(llm, deal_context="d", partner_message="m",
                    tactics_context="WIN-RATE LỊCH SỬ: 'phạt' đạt 80% (5 vụ)")
    assert "WIN-RATE LỊCH SỬ" in llm.last_prompt and "'phạt' đạt 80%" in llm.last_prompt


def test_negotiate_prompt_treats_legal_cap_as_hard_red_line():
    # Regression: prompt phải CẤM nhượng TRÊN trần luật (12% vẫn > 8% Đ.301 → vô hiệu), kể cả HAI CHIỀU.
    from legalguard.domain.negotiation import _SYSTEM
    low = _SYSTEM.lower()
    assert "trần luật" in low                    # có khái niệm trần luật
    assert "hai chiều" in low                    # nêu rõ hai chiều KHÔNG cứu phần vượt
    assert "8%" in _SYSTEM and "301" in _SYSTEM  # ví dụ cụ thể trần 8% / Điều 301
