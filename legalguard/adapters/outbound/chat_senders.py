"""Outbound adapter: gửi reply + tải file trên Slack / Zalo OA → implement ChatSenderPort.

Không có token → available=False (router sẽ fallback trả reply trong HTTP response).
"""
from __future__ import annotations

import logging

import httpx

_log = logging.getLogger(__name__)


class SlackSender:
    name = "slack"

    def __init__(self, bot_token: str) -> None:
        self.bot_token = bot_token

    @property
    def available(self) -> bool:
        return bool(self.bot_token)

    def send(self, conversation_id: str, text: str, thread_ts: str | None = None) -> None:
        payload: dict = {"channel": conversation_id, "text": text}
        if thread_ts:                       # trả lời đúng thread nếu khách hỏi trong thread
            payload["thread_ts"] = thread_ts
        resp = httpx.post("https://slack.com/api/chat.postMessage",
                          headers={"Authorization": f"Bearer {self.bot_token}"},
                          json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Slack trả HTTP 200 kể cả khi fail — lỗi nằm trong body {"ok": false, "error": ...}.
        if not data.get("ok"):
            _log.error("Slack chat.postMessage lỗi: %s (channel=%s)",
                       data.get("error"), conversation_id)

    def download(self, url: str) -> bytes:
        resp = httpx.get(url, headers={"Authorization": f"Bearer {self.bot_token}"},
                         timeout=60, follow_redirects=True)
        resp.raise_for_status()   # 4xx/5xx → lỗi rõ, không trả trang lỗi làm "nội dung file"
        return resp.content


class ZaloSender:
    name = "zalo"

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    @property
    def available(self) -> bool:
        return bool(self.access_token)

    def send(self, conversation_id: str, text: str, thread_ts: str | None = None) -> None:
        resp = httpx.post("https://openapi.zalo.me/v3.0/oa/message/cs",
                          headers={"access_token": self.access_token},
                          json={"recipient": {"user_id": conversation_id},
                                "message": {"text": text}}, timeout=30)
        resp.raise_for_status()
        if resp.json().get("error"):     # Zalo: error != 0 là fail
            _log.error("Zalo gửi tin lỗi: %s (user=%s)", resp.json().get("message"),
                       conversation_id)

    def download(self, url: str) -> bytes:
        resp = httpx.get(url, timeout=60, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
