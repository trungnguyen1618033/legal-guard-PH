"""Adapter Gemini (REST) → implement LLMPort.

Provider thứ hai (tóm tắt). Lỗi → LLMError sạch (có retry).
"""
from __future__ import annotations

from legalguard.adapters.outbound._http import post_json
from legalguard.domain.ports import LLMError, LLMPort

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiAdapter(LLMPort):
    name = "gemini"

    def __init__(self, api_key: str, model: str, temperature: float = 0.1) -> None:
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        if not self.available:
            return f"[GEMINI_STUB] {prompt[:120]}…"
        text = f"{system}\n\n{prompt}" if system else prompt
        data = post_json(f"{_BASE}/{self.model}:generateContent", provider=self.name,
                         params={"key": self.api_key},
                         json={"contents": [{"parts": [{"text": text}]}],
                               "generationConfig": {"temperature": self.temperature}}, timeout=60)
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            # Gemini block nội dung / trả rỗng → không để KeyError thành 500.
            raise LLMError(self.name, "phản hồi không hợp lệ (có thể bị chặn)") from None
