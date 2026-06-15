"""Observability → implement ObservabilityPort.

- NoOpObserver: mặc định (tắt).
- LangfuseObserver: gửi trace/event lên Langfuse (cần keys + `pip install langfuse`).
  Best-effort: lỗi/thiếu SDK → im lặng, không làm hỏng request.
"""
from __future__ import annotations


class NoOpObserver:
    def event(self, name: str, data: dict) -> None:
        pass


class LangfuseObserver:
    def __init__(self, public_key: str, secret_key: str, host: str = "") -> None:
        self._lf = None
        try:
            from langfuse import Langfuse  # lazy

            self._lf = Langfuse(public_key=public_key, secret_key=secret_key,
                                **({"host": host} if host else {}))
        except Exception:  # noqa: BLE001 — thiếu SDK/keys → coi như NoOp
            self._lf = None

    def event(self, name: str, data: dict) -> None:
        if self._lf is None:
            return
        try:
            self._lf.create_event(name=name, metadata=data)
        except Exception:  # noqa: BLE001 — telemetry không được làm hỏng nghiệp vụ
            pass
