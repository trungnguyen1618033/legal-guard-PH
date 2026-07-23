"""Gate reliability (fix e3195b7): ghi outcome kéo theo embed Qwen (agentic_memory DEFAULT ON) → PHẢI chạy
NỀN, KHÔNG chặn cửa sổ ack 3s của Slack interaction. Nếu inline lại `_record_deal_outcome(...)` đồng bộ →
~2N embed tuần tự trong handler → timeout → Slack retry → 'Chốt' TRÙNG.

Vì sao SOI NGUỒN (không phải test hành vi): FastAPI TestClient CHẠY background task TRƯỚC khi trả response
→ side-effect xuất hiện dù sync hay nền → KHÔNG phân biệt được bằng quan sát hành vi. Bất biến "phải nền"
là bất biến CẤU TRÚC → soi nguồn là cách TẤT ĐỊNH bắt regression inline-lại. Offline, không LLM/DB."""
from __future__ import annotations

import inspect
import re


def test_record_deal_outcome_only_scheduled_via_background():
    from legalguard.adapters.inbound import channels

    src = inspect.getsource(channels)
    # '_record_deal_outcome(' (tên + '(' liền) chỉ được xuất hiện ở DÒNG ĐỊNH NGHĨA `def _record_deal_outcome(`.
    # Mọi callsite phải truyền như THAM CHIẾU cho background.add_task → sau tên là ',' (không phải '(').
    direct_calls = re.findall(r"_record_deal_outcome\s*\(", src)
    assert len(direct_calls) == 1, (
        f"Chỉ được 1 '_record_deal_outcome(' (chính là `def`). Thấy {len(direct_calls)} → có callsite ĐỒNG BỘ "
        "trong handler? Ghi outcome phải qua background.add_task (embed Qwen off ack-path)."
    )
    # 3 callsite interaction ('Chốt' rv_confirm · rv_agree_all · oc_* legacy) đều phải qua background.add_task.
    scheduled = src.count("background.add_task(_record_deal_outcome")
    assert scheduled >= 3, (
        f"Kỳ vọng ≥3 callsite background.add_task(_record_deal_outcome, …); thấy {scheduled}."
    )
