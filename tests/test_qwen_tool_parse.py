"""Bóc tool_calls phòng thủ: model trả thiếu id/name KHÔNG được làm crash vòng agent."""
from legalguard.adapters.outbound import qwen as qwen_mod
from legalguard.adapters.outbound.qwen import QwenAdapter, _parse_tool_calls


def test_parse_well_formed():
    calls = _parse_tool_calls([
        {"id": "c1", "function": {"name": "flag_risk", "arguments": '{"clause":"A"}'}}])
    assert len(calls) == 1
    assert calls[0].id == "c1" and calls[0].name == "flag_risk"
    assert calls[0].arguments == {"clause": "A"}


def test_parse_missing_id_synthesizes():
    # Thiếu id (hay gặp ở parallel tool calls) → tự sinh, KHÔNG KeyError.
    calls = _parse_tool_calls([{"function": {"name": "flag_risk", "arguments": "{}"}}])
    assert len(calls) == 1 and calls[0].id == "call_0"


def test_parse_skips_missing_name():
    # tool_call thiếu function/name → bỏ qua, không crash.
    calls = _parse_tool_calls([
        {"id": "x"},                                   # không có function
        {"id": "y", "function": {}},                   # function rỗng (không name)
        {"id": "z", "function": {"name": "propose_fallback", "arguments": "{}"}}])
    assert [c.name for c in calls] == ["propose_fallback"]


def test_parse_bad_arguments_json_becomes_empty():
    calls = _parse_tool_calls([{"id": "c", "function": {"name": "flag_risk", "arguments": "{bad json"}}])
    assert calls[0].arguments == {}                    # JSON hỏng → {} (downstream tự bỏ qua mục thiếu field)


def test_parse_none_and_nonlist():
    assert _parse_tool_calls(None) == []
    assert _parse_tool_calls([42, "x", None]) == []    # phần tử không phải dict → bỏ


def test_chat_malformed_response_degrades_not_crash(monkeypatch):
    # Phản hồi có tool_call thiếu id → chat() KHÔNG ném KeyError (degrade thay vì crash analyze).
    adapter = QwenAdapter("sk-fake", "https://x/v1", "qwen3.7-max")
    monkeypatch.setattr(qwen_mod, "post_json", lambda *a, **k: {
        "choices": [{"message": {"content": None,
                                 "tool_calls": [{"function": {"name": "flag_risk", "arguments": "{}"}}]}}]})
    turn = adapter.chat([{"role": "user", "content": "x"}], tools=[])
    assert len(turn.tool_calls) == 1 and turn.tool_calls[0].id == "call_0"
