"""HTTP POST có retry/backoff + làm sạch lỗi cho các LLM adapter.

Retry trên lỗi tạm thời (timeout/connect/429/5xx); lỗi cuối → LLMError đã sanitize
(không lộ URL/key).
"""
from __future__ import annotations

import time

import httpx

from legalguard.domain.ports import LLMError

_TRANSIENT = {429, 500, 502, 503, 504}


def post_json(url: str, *, provider: str, json: dict, headers: dict | None = None,
              params: dict | None = None, timeout: float = 60, retries: int = 2) -> dict:
    for attempt in range(retries + 1):
        try:
            resp = httpx.post(url, headers=headers, params=params, json=json, timeout=timeout)
            if resp.status_code in _TRANSIENT and attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        except (httpx.TimeoutException, httpx.ConnectError):
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise LLMError(provider, "không kết nối được provider") from None
        except httpx.HTTPStatusError as exc:
            raise LLMError(provider, f"HTTP {exc.response.status_code}") from None
    raise LLMError(provider, "hết lượt thử lại")
