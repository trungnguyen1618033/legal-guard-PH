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
        self._names: dict[str, str] = {}   # cache users.info (tên hiển thị ít đổi; restart = làm mới)

    @property
    def available(self) -> bool:
        return bool(self.bot_token)

    def send(self, conversation_id: str, text: str, thread_ts: str | None = None,
             blocks: list | None = None) -> str | None:
        payload: dict = {"channel": conversation_id, "text": text}
        if blocks:                          # Block Kit (vd nút feedback); text vẫn giữ làm fallback
            payload["blocks"] = blocks
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
            return None
        return data.get("ts")               # ts tin đã gửi → cho phép chat.update (heartbeat A1)

    def update(self, conversation_id: str, ts: str, text: str,
               blocks: list | None = None) -> None:
        """Sửa TẠI CHỖ 1 tin đã gửi (chat.update) — dùng cho heartbeat tiến triển: cập nhật ack "đang phân
        tích… đã tìm N rủi ro" thay vì spam tin mới. Lỗi/thiếu ts → bỏ qua (tiến triển là phụ)."""
        if not ts:
            return
        payload: dict = {"channel": conversation_id, "ts": ts, "text": text}
        if blocks:
            payload["blocks"] = blocks
        try:
            resp = httpx.post("https://slack.com/api/chat.update",
                              headers={"Authorization": f"Bearer {self.bot_token}"},
                              json=payload, timeout=30)
            data = resp.json()
        except Exception:  # noqa: BLE001 — heartbeat phụ, không được làm hỏng luồng chính
            _log.exception("Slack chat.update lỗi (channel=%s)", conversation_id)
            return
        if not data.get("ok"):
            _log.warning("Slack chat.update từ chối: %s (channel=%s)",
                         data.get("error"), conversation_id)

    def upload_file(self, conversation_id: str, filename: str, data: bytes,
                    thread_ts: str | None = None, title: str = "", comment: str = "") -> bool:
        """Đăng FILE (vd .docx bản đối chiếu) vào kênh/thread — flow MỚI của Slack (files.upload cũ đã khai
        tử): getUploadURLExternal → PUT bytes → completeUploadExternal. Cần scope `files:write`. Trả True nếu
        OK; lỗi → log + False (best-effort, không raise). Zalo không hỗ trợ (no-op ở ZaloSender)."""
        hdr = {"Authorization": f"Bearer {self.bot_token}"}
        try:
            r1 = httpx.post("https://slack.com/api/files.getUploadURLExternal", headers=hdr,
                            data={"filename": filename, "length": len(data)}, timeout=30).json()
            if not r1.get("ok"):
                _log.error("Slack getUploadURLExternal lỗi: %s", r1.get("error"))
                return False
            httpx.post(r1["upload_url"], content=data, timeout=60).raise_for_status()   # 2) PUT bytes
            payload: dict = {"files": [{"id": r1["file_id"], "title": title or filename}],
                             "channel_id": conversation_id}
            if comment:
                payload["initial_comment"] = comment
            if thread_ts:
                payload["thread_ts"] = thread_ts
            r3 = httpx.post("https://slack.com/api/files.completeUploadExternal",
                            headers={**hdr, "Content-Type": "application/json; charset=utf-8"},
                            json=payload, timeout=30).json()
            if not r3.get("ok"):
                _log.error("Slack completeUploadExternal lỗi: %s (channel=%s)",
                           r3.get("error"), conversation_id)
                return False
            return True
        except Exception:  # noqa: BLE001 — upload là phụ; lỗi → False, caller báo text
            _log.exception("Slack upload_file lỗi (channel=%s)", conversation_id)
            return False

    def download(self, url: str) -> bytes:
        resp = httpx.get(url, headers={"Authorization": f"Bearer {self.bot_token}"},
                         timeout=60, follow_redirects=True)
        resp.raise_for_status()   # 4xx/5xx → lỗi rõ, không trả trang lỗi làm "nội dung file"
        return resp.content

    def fetch_thread(self, channel: str, thread_ts: str) -> list[dict]:
        """Đọc toàn bộ tin của 1 thread (conversations.replies, Tier 3) — catch-up ngữ cảnh khi bot được
        mention giữa hội thoại / user dán link thread. Tối đa 2 trang (400 tin); lỗi/không quyền → []
        (caller degrade, không crash). Cần scope channels:history/groups:history/im:history."""
        out: list[dict] = []
        cursor = ""
        for _ in range(2):                               # chặn phân trang vô hạn (thread cực dài → cắt)
            params: dict = {"channel": channel, "ts": thread_ts, "limit": 200}
            if cursor:
                params["cursor"] = cursor
            try:
                resp = httpx.get("https://slack.com/api/conversations.replies",
                                 headers={"Authorization": f"Bearer {self.bot_token}"},
                                 params=params, timeout=30)
                data = resp.json()
            except Exception:  # noqa: BLE001 — mạng/parse lỗi → degrade về [] (ngữ cảnh là phụ)
                _log.exception("Slack conversations.replies lỗi (channel=%s)", channel)
                return out
            if not data.get("ok"):                       # not_in_channel / thiếu scope → [] + log rõ
                _log.warning("Slack conversations.replies từ chối: %s (channel=%s)",
                             data.get("error"), channel)
                return out
            out += [{"user": m.get("user", ""), "bot_id": m.get("bot_id", ""),
                     "text": m.get("text", ""), "ts": m.get("ts", ""),
                     # file đính kèm (nếu có) → cho phép rà soát lại file HĐ đã có trong thread
                     "files": [{"url": fi.get("url_private", ""), "name": fi.get("name", "")}
                               for fi in (m.get("files") or []) if fi.get("url_private")]}
                    for m in data.get("messages", [])]
            cursor = (data.get("response_metadata") or {}).get("next_cursor", "")
            if not cursor:
                break
        return out

    def resolve_names(self, user_ids: list[str]) -> dict[str, str]:
        """Tên hiển thị của user (`users.info`, scope users:read) — attribution ai-nói-gì trong thread
        nhiều người. Cache in-process (tên ít đổi); id lỗi/thiếu scope → bỏ qua id đó (caller fallback
        nhãn ẩn danh). Danh tính là NGỮ CẢNH hội thoại (mọi người trong thread đều thấy tên nhau) —
        redact PII vẫn áp cho THÂN tin nhắn như cũ."""
        out: dict[str, str] = {}
        for uid in dict.fromkeys(u for u in user_ids if u):     # dedup, giữ thứ tự
            if uid in self._names:
                out[uid] = self._names[uid]
                continue
            try:
                data = httpx.get("https://slack.com/api/users.info",
                                 headers={"Authorization": f"Bearer {self.bot_token}"},
                                 params={"user": uid}, timeout=15).json()
            except Exception:  # noqa: BLE001 — tên là phụ: lỗi mạng → bỏ, caller dùng nhãn ẩn danh
                _log.exception("Slack users.info lỗi (user=%s)", uid)
                continue
            if not data.get("ok"):
                _log.warning("Slack users.info từ chối: %s (user=%s)", data.get("error"), uid)
                continue
            prof = (data.get("user") or {}).get("profile") or {}
            name = (prof.get("display_name") or prof.get("real_name")
                    or (data.get("user") or {}).get("real_name") or "").strip()
            if name:
                self._names[uid] = name
                out[uid] = name
        return out


class ZaloSender:
    name = "zalo"

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    @property
    def available(self) -> bool:
        return bool(self.access_token)

    def send(self, conversation_id: str, text: str, thread_ts: str | None = None,
             blocks: list | None = None) -> None:   # blocks: Zalo không hỗ trợ → bỏ qua
        resp = httpx.post("https://openapi.zalo.me/v3.0/oa/message/cs",
                          headers={"access_token": self.access_token},
                          json={"recipient": {"user_id": conversation_id},
                                "message": {"text": text}}, timeout=30)
        resp.raise_for_status()
        if resp.json().get("error"):     # Zalo: error != 0 là fail
            _log.error("Zalo gửi tin lỗi: %s (user=%s)", resp.json().get("message"),
                       conversation_id)

    def update(self, conversation_id: str, ts: str, text: str,
               blocks: list | None = None) -> None:
        return                         # Zalo OA không sửa được tin đã gửi → no-op (heartbeat bỏ qua)

    def upload_file(self, conversation_id: str, filename: str, data: bytes,
                    thread_ts: str | None = None, title: str = "", comment: str = "") -> bool:
        return False                   # Zalo OA: chưa hỗ trợ gửi file .docx → no-op (caller báo text/web)

    def download(self, url: str) -> bytes:
        resp = httpx.get(url, timeout=60, follow_redirects=True)
        resp.raise_for_status()
        return resp.content

    def fetch_thread(self, channel: str, thread_ts: str) -> list[dict]:
        return []                      # Zalo OA không có khái niệm thread — luôn rỗng (degrade an toàn)

    def resolve_names(self, user_ids: list[str]) -> dict[str, str]:
        return {}                      # Zalo OA: chat 1-1, không cần attribution — caller dùng nhãn mặc định
