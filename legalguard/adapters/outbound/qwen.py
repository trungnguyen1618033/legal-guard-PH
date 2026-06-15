"""Adapter Qwen Cloud / DashScope (tương thích OpenAI) → implement LLMPort.

Hỗ trợ complete / chat (tool-calling) / embed. Không key → chế độ STUB để demo
offline (mô phỏng agent quét từ khóa). Lỗi HTTP → LLMError đã làm sạch.
"""
from __future__ import annotations

import json
import re

from legalguard.adapters.outbound._http import post_json
from legalguard.domain.models import ChatTurn, ToolCall
from legalguard.domain.ports import LLMError, LLMPort

# Bilingual stub (chỉ dùng khi KHÔNG có API key). english_reply luôn tiếng Anh.
_STUB_PATTERNS = [
    {
        "pat": r"bắc kinh|trọng tài|arbitrat|beijing",
        "severity": "high", "priority": "must_fix",
        "clause": {"en": "Arbitration clause", "vi": "Điều khoản trọng tài"},
        "risk": {"en": "Arbitration seated in a venue unfavorable to the VN SME",
                 "vi": "Trọng tài tại nơi bất lợi cho SME VN"},
        "suggestion": {"en": "Propose SIAC (Singapore) or HKIAC — a neutral third party.",
                       "vi": "Đề xuất SIAC (Singapore) hoặc HKIAC — bên thứ 3 trung lập."},
        "english_reply": "We propose resolving disputes through SIAC in Singapore as a neutral venue for both parties.",
    },
    {
        "pat": r"t/t|trả sau|60 ngày|30 ngày|deferred",
        "severity": "medium", "priority": "negotiate",
        "clause": {"en": "Payment terms", "vi": "Điều khoản thanh toán"},
        "risk": {"en": "T/T deferred payment — risk of non-payment",
                 "vi": "Thanh toán T/T trả sau, rủi ro quỵt tiền"},
        "suggestion": {"en": "Propose an L/C backed by a major bank; advance capped at 30%.",
                       "vi": "Đề xuất L/C bảo lãnh bởi ngân hàng lớn; tối đa 30% trả trước."},
        "english_reply": "We would prefer payment by irrevocable L/C at sight, which protects both sides.",
    },
    {
        "pat": r"cảng đến|kiểm định|inspection|destination",
        "severity": "medium", "priority": "acceptable",
        "clause": {"en": "Inspection clause", "vi": "Điều khoản kiểm định"},
        "risk": {"en": "Inspection at destination port — risk of transit damage",
                 "vi": "Kiểm định tại cảng đến, rủi ro hàng hư trong vận chuyển"},
        "suggestion": {"en": "Use SGS/Bureau Veritas inspection at the port of loading (FOB).",
                       "vi": "Thuê SGS/Bureau Veritas kiểm định tại cảng đi (FOB)."},
        "english_reply": "We suggest quality inspection by SGS/Bureau Veritas at the port of loading (FOB).",
    },
]
_HR_REASON = {"en": "High-severity clause requires expert review",
              "vi": "Có điều khoản rủi ro cao cần chuyên gia duyệt"}


class QwenAdapter(LLMPort):
    name = "qwen"

    def __init__(self, api_key: str, base_url: str, model: str, embed_model: str = "text-embedding-v4",
                 temperature: float = 0.1) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.embed_model = embed_model
        self.temperature = temperature

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        if not self.available:
            return f"[QWEN_STUB] {prompt[:120]}…"
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        data = self._post_chat({"model": self.model, "messages": messages,
                                "temperature": self.temperature})
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError(self.name, "phản hồi không hợp lệ") from None

    def chat(self, messages: list[dict], *, tools: list[dict] | None = None) -> ChatTurn:
        if not self.available:
            return self._stub_chat(messages)
        payload: dict = {"model": self.model, "messages": messages, "temperature": self.temperature}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            msg = self._post_chat(payload)["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise LLMError(self.name, "phản hồi không hợp lệ") from None
        calls = [
            ToolCall(id=tc["id"], name=tc["function"]["name"],
                     arguments=_loads(tc["function"]["arguments"]))
            for tc in msg.get("tool_calls") or []
        ]
        return ChatTurn(content=msg.get("content"), tool_calls=calls)

    _EMBED_BATCH = 10   # DashScope giới hạn 10 texts / request embeddings

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not self.available:
            return None
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self._EMBED_BATCH):
            data = post_json(f"{self.base_url}/embeddings", provider=self.name,
                             headers={"Authorization": f"Bearer {self.api_key}"},
                             json={"model": self.embed_model,
                                   "input": texts[i:i + self._EMBED_BATCH]}, timeout=60)
            try:
                vectors += [item["embedding"] for item in data["data"]]
            except (KeyError, IndexError, TypeError):
                raise LLMError(self.name, "phản hồi embeddings không hợp lệ") from None
        return vectors

    def _post_chat(self, payload: dict) -> dict:
        return post_json(f"{self.base_url}/chat/completions", provider=self.name,
                         headers={"Authorization": f"Bearer {self.api_key}"},
                         json=payload, timeout=90)

    def _stub_chat(self, messages: list[dict]) -> ChatTurn:
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        lang = "vi" if "pháp chế thương mại" in system else "en"
        lev = (re.search(r"leverage=(\w+)", system) or [None, "balanced"])[1]
        if any(m.get("role") == "tool" for m in messages):
            strat = (f"[QWEN_STUB] Chiến lược (vị thế {lev}): GIỮ CỨNG điều khoản trọng tài (must_fix); "
                     "CÓ THỂ NHƯỢNG về kiểm định để chốt deal; điểm RÚT: nếu không đạt trọng tài trung lập "
                     "và bạn có đối tác thay thế (BATNA)." if lang == "vi"
                     else f"[QWEN_STUB] Strategy (leverage {lev}): INSIST on arbitration venue (must_fix); "
                     "CONCEDE on inspection to close; WALK AWAY if no neutral arbitration and you have a BATNA.")
            return ChatTurn(content=strat)
        contract = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        low = contract.lower()
        calls: list[ToolCall] = [ToolCall(id="stub-0", name="search_legal_knowledge",
                                          arguments={"query": "rủi ro hợp đồng ngoại thương"})]
        has_high = False
        for i, p in enumerate(_STUB_PATTERNS, 1):
            m = re.search(p["pat"], low)
            if m:
                src = "fallback_matrix.md"
                evidence = contract[m.start():m.end()]   # trích nguyên văn từ hợp đồng
                calls.append(ToolCall(id=f"stub-r{i}", name="flag_risk",
                                      arguments={"clause": p["clause"][lang], "risk": p["risk"][lang],
                                                 "severity": p["severity"], "priority": p["priority"],
                                                 "source": src, "evidence": evidence}))
                calls.append(ToolCall(id=f"stub-f{i}", name="propose_fallback",
                                      arguments={"clause": p["clause"][lang],
                                                 "suggestion": p["suggestion"][lang],
                                                 "english_reply": p["english_reply"], "source": src}))
                has_high = has_high or p["severity"] == "high"
        if has_high:
            calls.append(ToolCall(id="stub-hr", name="request_human_review",
                                  arguments={"reason": _HR_REASON[lang]}))
        return ChatTurn(tool_calls=calls)


def _loads(s: str) -> dict:
    try:
        return json.loads(s) if s else {}
    except json.JSONDecodeError:
        return {}
