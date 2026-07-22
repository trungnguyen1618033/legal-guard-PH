"""Test recall-inject bộ nhớ vào đàm phán (3b): format_memory_context + memory_context vào prompt."""
from __future__ import annotations

from legalguard.domain.models import MemoryEpisode
from legalguard.domain.negotiation import format_memory_context, negotiate_round


class _LLM:
    name = "qwen"

    def __init__(self, available=True, out=""):
        self._a, self._out, self.last_prompt = available, out, ""

    @property
    def available(self):
        return self._a

    def complete(self, prompt, *, system=None):
        self.last_prompt = prompt
        return self._out


def _ep(clause, content):
    return MemoryEpisode(id="", org_id="o", counterparty="ACME", kind="outcome",
                         clause=clause, content=content, created_at="2026-07-21")


def test_format_empty():
    assert format_memory_context([]) == ""
    assert format_memory_context([_ep("X", "")]) == ""     # không content → rỗng


def test_format_has_clause_content_and_reference_framing():
    out = format_memory_context([_ep("Thanh toán", "giữ 8% → accepted")])
    assert "Thanh toán" in out and "8%" in out
    assert "THAM KHẢO" in out and "KHÔNG phải luật" in out   # định vị tham khảo, không phải căn cứ


def test_format_respects_limit():
    eps = [_ep(f"C{i}", f"nội dung {i}") for i in range(10)]
    out = format_memory_context(eps, limit=3)
    assert "nội dung 0" in out and "nội dung 2" in out and "nội dung 5" not in out


def test_memory_context_injected_into_prompt():
    llm = _LLM(available=True, out="")
    mc = format_memory_context([_ep("Thanh toán", "giữ 8% → accepted")])
    negotiate_round(llm, deal_context="deal", partner_message="giảm còn 12%", memory_context=mc)
    assert "BỘ NHỚ ĐỐI TÁC" in llm.last_prompt and "8%" in llm.last_prompt


def test_no_memory_context_prompt_unchanged_marker():
    llm = _LLM(available=True, out="")
    negotiate_round(llm, deal_context="deal", partner_message="giảm còn 12%")   # không memory
    assert "BỘ NHỚ ĐỐI TÁC" not in llm.last_prompt          # rỗng → prompt KHÔNG có block memory
