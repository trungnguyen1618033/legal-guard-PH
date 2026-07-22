"""Eval CHẤT LƯỢNG RECALL của bộ nhớ agent (MemoryPort) — offline, tất định (không LLM/CRDB).

Mạch B (S2). Đo trên golden tình tiết đàm phán pháp lý có đáp án:
- **Recall@k / MRR@k**: recall() có đưa tình tiết ĐÚNG lên top-k không.
- **Cô lập org (no-leak)**: recall org A KHÔNG bao giờ trả tình tiết org B (yêu cầu privacy PDPD/GDPR — TỐI QUAN TRỌNG cho pháp lý).
- **Chống nhiễu**: truy vấn không liên quan → RỖNG (không inject nhiễu vào prompt).
- **Ưu tiên đối tác**: có counterparty → tình tiết cùng đối tác lên đầu.

Chạy trên 2 backend: InMemoryMemory (lexical) + SqlMemory (semantic, embedder GIẢ tất định) → so hành vi.
`evaluate()`/`build_golden()` THUẦN (test offline). CLI: `uv run python -m evaluation.memory_eval`.
LƯU Ý: chất lượng semantic trên embedding THẬT (Qwen) là eval LIVE riêng — đây đo LOGIC recall (ranking/
cô lập/nhiễu) tất định, làm cổng regression khi sửa MemoryPort.
"""
from __future__ import annotations

import json
import tempfile
import unicodedata
from pathlib import Path

from legalguard.domain.models import MemoryEpisode

_REPORT = Path("evaluation/memory_report.json")

# Embedder GIẢ tất định: 5 chiều theo CHỦ ĐỀ (thanh toán/giao hàng/bảo mật/trọng tài/lãi) → semantic path
# tái hiện được offline. Query & tình tiết cùng chủ đề → vector gần nhau.
_TOPICS = ["thanh toán|phạt", "giao hàng|giao", "bảo mật|nda", "trọng tài", "lãi|lãi suất"]


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", (s or "").lower())


def fake_embed(texts: list[str]) -> list[list[float]]:
    out = []
    for t in texts:
        tl = _norm(t)
        out.append([1.0 if any(k in tl for k in topic.split("|")) else 0.0 for topic in _TOPICS])
    return out


def build_golden() -> tuple[list[MemoryEpisode], list[dict]]:
    """Tình tiết (nhiều org/đối tác) + truy vấn có đáp án. `expect`: id phải nằm top-k; `expect_empty`:
    phải rỗng; `forbid`: id KHÔNG được xuất hiện (cô lập org)."""
    def ep(eid, org, cp, clause, content):
        return MemoryEpisode(id=eid, org_id=org, counterparty=cp, kind="outcome", clause=clause,
                             content=content, created_at="2026-07-22", case_id=eid)

    episodes = [
        ep("a1", "orgA", "ACME", "Điều khoản Thanh toán", "ACME đòi phạt chậm thanh toán 15%, ta giữ trần 8% → accepted"),
        ep("a2", "orgA", "ACME", "Điều khoản Giao hàng", "ACME muốn giao hàng 30 ngày, ta chốt 45 ngày → partial"),
        ep("a3", "orgA", "ACME", "Điều khoản Bảo mật", "NDA đơn phương, ta đổi thành bảo mật song phương → accepted"),
        ep("a4", "orgA", "GLOBEX", "Điều khoản Trọng tài", "GLOBEX muốn trọng tài Singapore, ta chốt VIAC → accepted"),
        ep("b1", "orgB", "ACME", "Điều khoản Thanh toán", "bí mật orgB — phạt thanh toán 20%"),
    ]
    queries = [
        {"name": "recall-thanh-toán", "org": "orgA", "q": "phạt chậm thanh toán bao nhiêu phần trăm", "cp": "ACME", "expect": "a1"},
        {"name": "recall-giao-hàng", "org": "orgA", "q": "thời hạn giao hàng", "cp": "ACME", "expect": "a2"},
        {"name": "recall-trọng-tài", "org": "orgA", "q": "trọng tài ở đâu", "cp": "GLOBEX", "expect": "a4"},
        {"name": "recall-no-cp", "org": "orgA", "q": "phạt thanh toán", "cp": "", "expect": "a1"},
        {"name": "ưu-tiên-đối-tác", "org": "orgA", "q": "điều khoản trọng tài", "cp": "GLOBEX", "expect": "a4"},
        {"name": "cô-lập-org", "org": "orgA", "q": "phạt thanh toán 20%", "cp": "", "forbid": "b1"},
        {"name": "chống-nhiễu", "org": "orgA", "q": "thời tiết hôm nay thế nào", "cp": "", "expect_empty": True},
    ]
    return episodes, queries


def evaluate(memory, queries: list[dict], k: int = 3) -> dict:  # noqa: ANN001
    """Chạy từng truy vấn qua memory.recall → tính Recall@k, MRR, cô lập, chống nhiễu. THUẦN với memory đã seed."""
    hits, mrr_sum, rel_total = 0, 0.0, 0
    isolation_ok = noise_ok = True
    details = []
    for qc in queries:
        got = memory.recall(qc["org"], qc["q"], counterparty=qc.get("cp", ""), k=k)
        ids = [e.id for e in got]
        row = {"name": qc["name"], "got": ids}
        if qc.get("expect_empty"):
            ok = len(ids) == 0
            noise_ok = noise_ok and ok
            row["pass"] = ok
        elif "forbid" in qc:
            ok = qc["forbid"] not in ids
            isolation_ok = isolation_ok and ok
            row["pass"] = ok
        else:                                                   # relevance query
            rel_total += 1
            exp = qc["expect"]
            if exp in ids:
                hits += 1
                mrr_sum += 1.0 / (ids.index(exp) + 1)
            row["pass"] = exp in ids
            row["rank"] = ids.index(exp) + 1 if exp in ids else None
        details.append(row)
    return {
        "recall_at_k": round(hits / rel_total, 3) if rel_total else 0.0,
        "mrr": round(mrr_sum / rel_total, 3) if rel_total else 0.0,
        "org_isolation": isolation_ok,       # PHẢI True (không rò org khác)
        "noise_rejection": noise_ok,         # PHẢI True (truy vấn nhảm → rỗng)
        "k": k, "relevance_queries": rel_total, "details": details,
    }


def _seed(memory, episodes):  # noqa: ANN001
    for e in episodes:
        memory.remember(e)
    return memory


def run(write: bool = True) -> dict:
    from legalguard.adapters.outbound.memory_store import InMemoryMemory
    from legalguard.adapters.outbound.sql_memory_store import SqlMemory

    episodes, queries = build_golden()
    results = {}
    # Backend 1: InMemory (lexical + counterparty + recency)
    results["inmemory_lexical"] = evaluate(_seed(InMemoryMemory(), episodes), queries)
    # Backend 2: SqlMemory (semantic, embedder GIẢ tất định) — sqlite tạm, brute-force cosine
    with tempfile.TemporaryDirectory() as d:
        sm = SqlMemory(f"sqlite:///{Path(d) / 'mem_eval.db'}", embed_fn=fake_embed)
        results["sqlmemory_semantic"] = evaluate(_seed(sm, episodes), queries)

    report = {"backends": results}
    for name, r in results.items():
        print(f"\n=== {name} ===")
        print(f"  Recall@{r['k']} = {r['recall_at_k']:.0%} | MRR = {r['mrr']:.3f} | "
              f"cô-lập-org = {'✅' if r['org_isolation'] else '❌'} | chống-nhiễu = {'✅' if r['noise_rejection'] else '❌'}")
        for row in r["details"]:
            tag = "✅" if row.get("pass") else "❌"
            print(f"   [{tag}] {row['name']}: {row['got']}")
    if write:
        _REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nĐã ghi {_REPORT}")
    return report


if __name__ == "__main__":
    import sys
    run(write="--no-write" not in sys.argv)
