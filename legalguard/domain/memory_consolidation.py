"""Consolidation bộ nhớ agent — gộp NHIỀU tình tiết rời (episodic) của MỘT đối tác thành 1 HỒ SƠ cô đọng
(semantic profile), đúng tinh thần A-MEM/Mem0 nhưng TẤT ĐỊNH (không LLM) → test offline + không nhiễu.

Vì sao: recall trả N tình tiết thô càng ngày càng dài/loãng; consolidation nén thành hồ sơ ("đối tác này
hay chốt/nhượng điều gì") → prompt ngắn + tín hiệu đậm. Thuần: KHÔNG I/O, KHÔNG LLM → gọi ở đâu cũng an toàn.
"""
from __future__ import annotations

from collections import Counter, defaultdict


def consolidate_counterparty(counterparty: str, episodes: list, max_clauses: int = 8) -> str:
    """Gộp `episodes` của 1 đối tác → chuỗi hồ sơ tổng hợp. Bỏ episode `kind=profile` (không gộp hồ sơ cũ).
    Rỗng nếu không có tình tiết. TẤT ĐỊNH (sắp theo số lần giảm dần rồi tên điều khoản)."""
    eps = [e for e in (episodes or []) if getattr(e, "kind", "") != "profile"]
    if not eps:
        return ""
    by_clause: dict[str, list] = defaultdict(list)
    for e in eps:
        key = (getattr(e, "clause", "") or "").strip() or "(chung)"
        by_clause[key].append(e)
    items = sorted(by_clause.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:max_clauses]
    parts = []
    for clause, group in items:
        kinds = Counter(getattr(g, "kind", "") or "note" for g in group)
        kind_str = ", ".join(f"{k}×{n}" for k, n in kinds.most_common())
        parts.append(f"{clause} ({kind_str})")
    latest = max(eps, key=lambda e: getattr(e, "created_at", "") or "")
    body = "; ".join(parts)
    return (f"HỒ SƠ ĐỐI TÁC {counterparty} — tổng hợp {len(eps)} tình tiết deal/vòng trước: {body}. "
            f"Gần nhất: {(getattr(latest, 'content', '') or '')[:160]}")
