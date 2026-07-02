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
    {
        "pat": r"phạt|penalty|vi phạm.*%|%.*vi phạm",
        "severity": "high", "priority": "must_fix",
        "legal_status": "illegal", "violated_law": "Điều 301 Luật Thương mại 2005",
        "clause": {"en": "Penalty clause", "vi": "Điều khoản phạt vi phạm"},
        "risk": {"en": "Penalty likely exceeds the 8% statutory cap (Art.301) — may be void",
                 "vi": "Mức phạt có thể vượt trần 8% (Điều 301) — có nguy cơ vô hiệu"},
        "suggestion": {"en": "Cap the penalty at 8% of the breached obligation per Art.301.",
                       "vi": "Đưa mức phạt về tối đa 8% phần nghĩa vụ bị vi phạm theo Điều 301."},
        "english_reply": "We propose capping the penalty at 8% of the breached obligation, per Vietnamese law.",
    },
]
_HR_REASON = {"en": "High-severity clause requires expert review",
              "vi": "Có điều khoản rủi ro cao cần chuyên gia duyệt"}


class QwenAdapter(LLMPort):
    name = "qwen"

    def __init__(self, api_key: str, base_url: str, model: str, embed_model: str = "text-embedding-v4",
                 temperature: float = 0.1, rerank_model: str = "qwen3-rerank") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.embed_model = embed_model
        self.temperature = temperature
        self.rerank_model = rerank_model

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
        return ChatTurn(content=msg.get("content"), tool_calls=_parse_tool_calls(msg.get("tool_calls")))

    _EMBED_BATCH = 10       # DashScope giới hạn 10 texts / request embeddings
    _EMBED_MAX_CHARS = 6000  # cắt mỗi input (chunk dài/VB không cấu trúc Điều) → tránh vượt token limit (HTTP 400)

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not self.available:
            return None
        # Cắt input dài + thay rỗng = ' ' (API từ chối input rỗng / quá token) → bền với corpus lớn auto-ingest.
        safe = [(t or " ")[: self._EMBED_MAX_CHARS] or " " for t in texts]
        vectors: list[list[float]] = []
        for i in range(0, len(safe), self._EMBED_BATCH):
            data = post_json(f"{self.base_url}/embeddings", provider=self.name,
                             headers={"Authorization": f"Bearer {self.api_key}"},
                             json={"model": self.embed_model,
                                   "input": safe[i:i + self._EMBED_BATCH]}, timeout=60)
            try:
                vectors += [item["embedding"] for item in data["data"]]
            except (KeyError, IndexError, TypeError):
                raise LLMError(self.name, "phản hồi embeddings không hợp lệ") from None
        return vectors

    def rerank(self, query: str, docs: list[str]) -> list[float] | None:
        """Cross-encoder rerank qua DashScope text-rerank (qwen3-rerank; gte-rerank v1 đã khai tử 30/5/2026). Trả điểm/doc theo
        đúng thứ tự `docs`; None khi chưa có key (→ retriever passthrough)."""
        if not self.available or not docs:
            return None
        # Endpoint rerank là native DashScope (không nằm ở compatible-mode/v1).
        url = self.base_url.replace("/compatible-mode/v1",
                                    "/api/v1/services/rerank/text-rerank/text-rerank")
        data = post_json(url, provider=self.name,
                         headers={"Authorization": f"Bearer {self.api_key}"},
                         json={"model": self.rerank_model,
                               "input": {"query": query, "documents": docs},
                               "parameters": {"return_documents": False, "top_n": len(docs)}},
                         timeout=60)
        try:
            scores = [0.0] * len(docs)
            for r in data["output"]["results"]:
                scores[r["index"]] = float(r["relevance_score"])
            return scores
        except (KeyError, IndexError, TypeError, ValueError):
            raise LLMError(self.name, "phản hồi rerank không hợp lệ") from None

    def _post_chat(self, payload: dict) -> dict:
        return post_json(f"{self.base_url}/chat/completions", provider=self.name,
                         headers={"Authorization": f"Bearer {self.api_key}"},
                         json=payload, timeout=90)

    def _stub_chat(self, messages: list[dict]) -> ChatTurn:
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        lang = "vi" if "rà soát hợp đồng" in system else "en"   # cụm chỉ có trong system prompt tiếng Việt
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
                                                 "legal_status": p.get("legal_status", "unfavorable"),
                                                 "violated_law": p.get("violated_law", ""),
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


def _parse_tool_calls(raw: list | None) -> list[ToolCall]:
    """Bóc tool_calls PHÒNG THỦ từ phản hồi LLM. Một số model (đặc biệt parallel tool calls) trả thiếu
    `id` hoặc `function.name` → KHÔNG được để KeyError lọt ra (sẽ crash vòng phân tích thay vì degrade).
    Bỏ tool_call thiếu tên; id rỗng → tự sinh (tránh trùng/ánh xạ sai → 400 ở request kế)."""
    calls: list[ToolCall] = []
    for i, tc in enumerate(raw or []):
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        name = fn.get("name")
        if not name:                                   # tool_call rác (thiếu tên) → bỏ
            continue
        calls.append(ToolCall(id=tc.get("id") or f"call_{i}",
                              name=name, arguments=_loads(fn.get("arguments") or "")))
    return calls
