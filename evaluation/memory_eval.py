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

from legalguard.domain.memory_consolidation import consolidate_counterparty
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
    def ep(eid, org, cp, clause, content, when="2026-07-22"):
        return MemoryEpisode(id=eid, org_id=org, counterparty=cp, kind="outcome", clause=clause,
                             content=content, created_at=when, case_id=eid)

    episodes = [
        ep("a1", "orgA", "ACME", "Điều khoản Thanh toán", "ACME đòi phạt chậm thanh toán 15%, ta giữ trần 8% → accepted"),
        ep("a2", "orgA", "ACME", "Điều khoản Giao hàng", "ACME muốn giao hàng 30 ngày, ta chốt 45 ngày → partial"),
        ep("a3", "orgA", "ACME", "Điều khoản Bảo mật", "NDA đơn phương, ta đổi thành bảo mật song phương → accepted"),
        ep("a4", "orgA", "GLOBEX", "Điều khoản Trọng tài", "GLOBEX muốn trọng tài Singapore, ta chốt VIAC → accepted"),
        ep("b1", "orgB", "ACME", "Điều khoản Thanh toán", "bí mật orgB — phạt thanh toán 20%"),
        # Bi-temporal: DELTA "Lãi chậm trả" đổi vị thế — s_new SUPERSEDE s_old (cùng cp+clause; seed s_old TRƯỚC).
        ep("s_old", "orgA", "DELTA", "Điều khoản Lãi chậm trả", "DELTA đề xuất lãi chậm trả 25%", when="2026-07-01"),
        ep("s_new", "orgA", "DELTA", "Điều khoản Lãi chậm trả", "ta hạ lãi chậm trả về 20% → accepted", when="2026-07-20"),
        # BOOST-ranking: cùng org+chủ đề 'thanh toán' nhưng ĐỐI TÁC KHÁC (GLOBEX) → phải xếp DƯỚI a1 (ACME)
        # khi hỏi cp=ACME (boost cùng-đối-tác). Khác cp ⇒ KHÔNG supersede a1 dù cùng tên điều khoản.
        ep("g_pay", "orgA", "GLOBEX", "Điều khoản Thanh toán", "GLOBEX phạt thanh toán 10%", when="2026-07-10"),
        # RECENCY tie-break: 2 tình tiết OMEGA cùng chủ đề 'thanh toán', KHÁC điều khoản (không supersede).
        # Nội dung CHỈ chạm chủ đề 'thanh toán' (tránh từ chủ đề khác làm lệch vector embedder giả) → điểm
        # BẰNG nhau trên CẢ 2 backend → tie-break recency: episode MỚI HƠN (o2) phải đứng trước o1.
        ep("o1", "orgA", "OMEGA", "Thanh toán đợt 1", "OMEGA thanh toán trước 30%", when="2026-05-01"),
        ep("o2", "orgA", "OMEGA", "Thanh toán đợt 2", "OMEGA thanh toán nốt 70%", when="2026-06-01"),
    ]
    queries = [
        {"name": "recall-thanh-toán", "org": "orgA", "q": "phạt chậm thanh toán bao nhiêu phần trăm", "cp": "ACME", "expect": "a1"},
        {"name": "recall-giao-hàng", "org": "orgA", "q": "thời hạn giao hàng", "cp": "ACME", "expect": "a2"},
        {"name": "recall-trọng-tài", "org": "orgA", "q": "trọng tài ở đâu", "cp": "GLOBEX", "expect": "a4"},
        {"name": "recall-no-cp", "org": "orgA", "q": "phạt thanh toán", "cp": "", "expect": "a1"},
        {"name": "ưu-tiên-đối-tác", "org": "orgA", "q": "điều khoản trọng tài", "cp": "GLOBEX", "expect": "a4"},
        {"name": "cô-lập-org", "org": "orgA", "q": "phạt thanh toán 20%", "cp": "", "forbid": "b1"},
        {"name": "chống-nhiễu", "org": "orgA", "q": "thời tiết hôm nay thế nào", "cp": "", "expect_empty": True},
        # Bi-temporal: recall trả vị thế HIỆN TẠI (s_new), KHÔNG trả vị thế cũ đã superseded (s_old).
        {"name": "supersede-hiện-tại", "org": "orgA", "q": "mức lãi chậm trả", "cp": "DELTA", "expect": "s_new"},
        {"name": "supersede-bỏ-cũ", "org": "orgA", "q": "mức lãi chậm trả", "cp": "DELTA", "forbid": "s_old", "metric": "supersede"},
        # PROVENANCE: include_history=True → thấy CẢ vị thế đã superseded (s_old) LẪN hiện tại (s_new) → audit trail.
        {"name": "provenance-lịch-sử", "org": "orgA", "q": "mức lãi chậm trả", "cp": "DELTA", "history": True,
         "expect_all": ["s_new", "s_old"], "metric": "history"},
        # BOOST: cùng org+chủ đề, hỏi cp=ACME → a1 (ACME) phải đứng TRƯỚC g_pay (GLOBEX) nhờ counterparty-boost.
        {"name": "boost-đối-tác-lên-đầu", "org": "orgA", "q": "phạt thanh toán", "cp": "ACME",
         "expect_before": ["a1", "g_pay"], "metric": "boost"},
        # RECENCY: điểm bằng nhau (cùng cp OMEGA, cùng chủ đề) → tình tiết MỚI (o2) trước tình tiết cũ (o1).
        {"name": "recency-mới-trước", "org": "orgA", "q": "thanh toán", "cp": "OMEGA",
         "expect_before": ["o2", "o1"], "metric": "recency"},
    ]
    return episodes, queries


def evaluate(memory, queries: list[dict], k: int = 3) -> dict:  # noqa: ANN001
    """Chạy từng truy vấn qua memory.recall → tính Recall@k, MRR + các cổng boolean. THUẦN với memory đã seed.

    Loại truy vấn: `expect` (relevance top-k) · `expect_empty` (chống nhiễu) · `forbid` (cô lập/supersede) ·
    `expect_all` (provenance: TẤT CẢ id phải có khi include_history) · `expect_before` (thứ hạng a trước b:
    boost cùng-đối-tác / recency). `metric` gắn kết quả vào cổng tương ứng."""
    hits, mrr_sum, rel_total = 0, 0.0, 0
    flags = {"org_isolation": True, "noise_rejection": True, "supersede_ok": True,
             "history_ok": True, "boost_ok": True, "recency_ok": True}
    details = []
    for qc in queries:
        got = memory.recall(qc["org"], qc["q"], counterparty=qc.get("cp", ""), k=k,
                            include_history=qc.get("history", False))
        ids = [e.id for e in got]
        row = {"name": qc["name"], "got": ids}
        metric = qc.get("metric")
        if qc.get("expect_empty"):
            ok = len(ids) == 0
            flags["noise_rejection"] &= ok
        elif "forbid" in qc:
            ok = qc["forbid"] not in ids
            flags["supersede_ok" if metric == "supersede" else "org_isolation"] &= ok
        elif "expect_all" in qc:                                # provenance: mọi id (kể cả superseded) phải có mặt
            ok = all(x in ids for x in qc["expect_all"])
            flags["history_ok"] &= ok
        elif "expect_before" in qc:                             # thứ hạng: a đứng TRƯỚC b (b vắng cũng đạt)
            a, b = qc["expect_before"]
            ok = a in ids and (b not in ids or ids.index(a) < ids.index(b))
            flags["boost_ok" if metric == "boost" else "recency_ok"] &= ok
        else:                                                   # relevance query
            rel_total += 1
            exp = qc["expect"]
            ok = exp in ids
            if ok:
                hits += 1
                mrr_sum += 1.0 / (ids.index(exp) + 1)
            row["rank"] = ids.index(exp) + 1 if ok else None
        row["pass"] = ok
        details.append(row)
    # CONSOLIDATION: gộp hồ sơ DELTA → phải non-rỗng + phản ánh vị thế HIỆN TẠI (bi-temporal): chứa "20%"
    # (stance mới s_new) và KHÔNG chứa "25%" (s_old đã superseded, list_by_counterparty bỏ). Gate cả
    # consolidation LẪN tương tác consolidation×supersede.
    prof = consolidate_counterparty("DELTA", memory.list_by_counterparty("orgA", "DELTA"))
    consolidation_ok = bool(prof) and "20%" in prof and "25%" not in prof
    details.append({"name": "consolidation-vị-thế-hiện-tại", "got": prof[:90], "pass": consolidation_ok})
    return {
        "recall_at_k": round(hits / rel_total, 3) if rel_total else 0.0,
        "mrr": round(mrr_sum / rel_total, 3) if rel_total else 0.0,
        "org_isolation": flags["org_isolation"],   # PHẢI True (không rò org khác)
        "noise_rejection": flags["noise_rejection"],  # PHẢI True (truy vấn nhảm → rỗng)
        "supersede_ok": flags["supersede_ok"],      # PHẢI True (bi-temporal: không recall vị thế đã superseded)
        "history_ok": flags["history_ok"],          # PHẢI True (provenance: include_history thấy cả đã-superseded)
        "boost_ok": flags["boost_ok"],              # PHẢI True (episode cùng đối tác xếp trên đối tác khác)
        "recency_ok": flags["recency_ok"],          # PHẢI True (điểm bằng → tình tiết mới xếp trước)
        "consolidation_ok": consolidation_ok,       # PHẢI True (hồ sơ gộp = vị thế HIỆN TẠI, bỏ superseded)
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
        def _m(key: str) -> str:  # noqa: ANN001
            return "✅" if r[key] else "❌"
        print(f"  Recall@{r['k']} = {r['recall_at_k']:.0%} | MRR = {r['mrr']:.3f} | "
              f"cô-lập-org = {_m('org_isolation')} | chống-nhiễu = {_m('noise_rejection')} | "
              f"supersede = {_m('supersede_ok')} | provenance = {_m('history_ok')} | "
              f"boost = {_m('boost_ok')} | recency = {_m('recency_ok')} | consolidation = {_m('consolidation_ok')}")
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
