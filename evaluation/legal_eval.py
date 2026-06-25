"""Eval harness cho TRA CỨU LUẬT (retrieval) — đo các kỹ thuật Phase 0/2 + in-force có thật sự cải thiện.

Khác `run_eval.py` (đo phát hiện rủi ro hợp đồng): module này đo RETRIEVAL trên corpus luật VN:
- Recall@k / MRR / Hit@k ở mức Điều (cổng an toàn chính cho tra cứu pháp lý).
- Closure-recall: recall trên cụm điều dẫn chiếu chéo, closure OFF vs ON → giá trị của citation-closure.
- Still-good-law accuracy: % kết quả còn hiệu lực (đo in-force filter; xây corpus tạm có 1 bản hết hiệu lực).

Chạy:  uv run python -m evaluation.legal_eval
Offline hoàn toàn (retriever keyword, tất định — không cần API key). Golden: `evaluation/legal_golden.json`
(bootstrap synthetic-query từ chính văn bản luật; CẦN LUẬT SƯ DUYỆT trước khi coi là chuẩn).
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from legalguard.adapters.outbound.knowledge_base import (
    _is_in_force,
    _load_doc_status,
    build_retriever,
)
from legalguard.adapters.outbound.legal_chunker import article_key
from legalguard.config.settings import settings


def _load_golden(path: str | None = None) -> list[dict]:
    p = Path(path) if path else Path(__file__).parent / "legal_golden.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _art_id(source: str) -> str:
    """Chuẩn hóa source về mức ĐIỀU: 'file.md#Điều 297 khoản 2' → 'file.md#Điều 297'.

    Tra cứu pháp lý đo ở mức điều luật (khớp dù chunk là khoản con của điều đúng)."""
    if "#" not in source:
        return source
    fn, label = source.split("#", 1)
    key = article_key(label)
    return f"{fn}#{key}" if key else source


def _retrieved_arts(retriever, query: str, top_k: int) -> list[str]:
    seen: list[str] = []
    for h in retriever.retrieve(query, top_k):
        a = _art_id(h.source)
        if a not in seen:
            seen.append(a)
    return seen


def eval_retrieval(top_k: int = 5, strategy: str = "keyword", closure: bool = False,
                   in_force: bool = False, golden: list[dict] | None = None) -> dict:
    """Recall@k / MRR / Hit@k trung bình ở mức điều, trên toàn bộ golden."""
    cases = golden or _load_golden()
    r = build_retriever(settings.knowledge_base_dir, "VN", strategy=strategy,
                        closure=closure, in_force=in_force)
    recall_sum = mrr_sum = hit_sum = 0.0
    for c in cases:
        expected = {_art_id(e) for e in c["expected"]}
        got = _retrieved_arts(r, c["query"], top_k)
        got_set = set(got)
        recall_sum += len(expected & got_set) / len(expected)
        hit_sum += 1.0 if expected & got_set else 0.0
        rank = next((i + 1 for i, a in enumerate(got) if a in expected), 0)
        mrr_sum += 1.0 / rank if rank else 0.0
    n = len(cases) or 1
    return {"cases": len(cases), "recall@k": round(recall_sum / n, 3),
            "mrr": round(mrr_sum / n, 3), "hit@k": round(hit_sum / n, 3), "top_k": top_k}


def eval_closure(top_k: int = 1, golden: list[dict] | None = None) -> dict:
    """Trên các ca type=closure: recall của cụm điều khi closure OFF vs ON. Delta = giá trị closure.

    Đo ở top_k nhỏ (mặc định 1) để CÔ LẬP giá trị closure: base chỉ lấy điều gốc, điều dẫn chiếu phải
    do closure kéo. (Corpus càng lớn, base càng khó lấy đủ cụm → giá trị closure càng tăng ở top_k thường.)"""
    cases = [c for c in (golden or _load_golden()) if c.get("type") == "closure"]
    base = build_retriever(settings.knowledge_base_dir, "VN", strategy="keyword")
    clo = build_retriever(settings.knowledge_base_dir, "VN", strategy="keyword", closure=True)
    off = on = 0.0
    for c in cases:
        expected = {_art_id(e) for e in c["expected"]}
        off += len(expected & set(_retrieved_arts(base, c["query"], top_k))) / len(expected)
        on += len(expected & set(_retrieved_arts(clo, c["query"], top_k))) / len(expected)
    n = len(cases) or 1
    return {"closure_cases": len(cases), "recall_off": round(off / n, 3),
            "recall_on": round(on / n, 3), "delta": round((on - off) / n, 3), "top_k": top_k}


def eval_in_force() -> dict:
    """Still-good-law accuracy: dựng corpus tạm (1 bản còn + 1 bản hết hiệu lực cùng chủ đề),
    đo % kết quả còn hiệu lực ở query thường, và việc bản cũ hiện lại ở query lịch sử."""
    with tempfile.TemporaryDirectory() as d:
        vn = Path(d) / "VN"
        vn.mkdir()
        (vn / "moi.md").write_text(
            "---\nstatus: in_force\n---\nĐiều 1. Thuế suất\nÁp dụng thuế suất ưu đãi mới.\n\n"
            "Điều 2. Hiệu lực\nCó hiệu lực thi hành.", encoding="utf-8")
        (vn / "cu.md").write_text(
            "---\nstatus: expired\n---\nĐiều 1. Thuế suất\nÁp dụng thuế suất ưu đãi cũ.\n\n"
            "Điều 2. Hiệu lực\nĐã hết hiệu lực.", encoding="utf-8")
        r = build_retriever(d, "VN", strategy="keyword", in_force=True)
        normal = r.retrieve("thuế suất ưu đãi", top_k=5)
        in_force_n = sum(1 for h in normal if h.source.startswith("moi.md"))
        accuracy = in_force_n / len(normal) if normal else 1.0
        hist = r.retrieve("thuế suất ưu đãi quy định cũ trước đây", top_k=5)
        hist_has_old = any(h.source.startswith("cu.md") for h in hist)
    return {"still_good_law_accuracy": round(accuracy, 3),
            "expired_shown_default": any(h.source.startswith("cu.md") for h in normal),
            "expired_surfaced_on_historical": hist_has_old}


def eval_in_force_real(query: str = "thời điểm lập hóa đơn bán hàng hóa cung cấp dịch vụ",
                       top_k: int = 4) -> dict:
    """Still-good-law accuracy trên CORPUS THẬT: query về hóa đơn (KB có TT 39/2014 đã hết hiệu lực
    + NĐ 123/2020 còn hiệu lực). Đo % kết quả còn hiệu lực khi lọc OFF vs ON — chứng minh lọc loại
    đúng văn bản đã hết hiệu lực (lỗi 'inapplicable authority')."""
    status = _load_doc_status(settings.knowledge_base_dir, "VN")

    def accuracy(retriever) -> tuple[float, list[str]]:
        hits = retriever.retrieve(query, top_k)
        if not hits:
            return 1.0, []
        files = [h.source.split("#", 1)[0] for h in hits]
        ok = sum(1 for f in files if _is_in_force(status.get(f, "in_force")))
        return ok / len(hits), files

    off = build_retriever(settings.knowledge_base_dir, "VN", strategy="keyword")
    on = build_retriever(settings.knowledge_base_dir, "VN", strategy="keyword", in_force=True)
    a_off, files_off = accuracy(off)
    a_on, _ = accuracy(on)
    return {"accuracy_off": round(a_off, 3), "accuracy_on": round(a_on, 3),
            "expired_in_off": [f for f in files_off if not _is_in_force(status.get(f, "in_force"))]}


def query_demo(query: str, top_k: int = 4) -> None:
    """Tra cứu thử 1 câu hỏi: so sánh baseline vs +in_force vs +in_force+closure (offline, keyword)."""
    configs = [
        ("baseline (không lọc, không closure)", {}),
        ("+in_force (chỉ văn bản còn hiệu lực)", {"in_force": True}),
        ("+in_force +closure (đi theo dẫn chiếu)", {"in_force": True, "closure": True}),
    ]
    print(f'\nQuery: "{query}"  (top_k={top_k}, keyword/offline)\n')
    for label, kw in configs:
        r = build_retriever(settings.knowledge_base_dir, "VN", strategy="keyword", **kw)
        print(f"── {label}")
        hits = r.retrieve(query, top_k)
        if not hits:
            print("   (không có kết quả)")
        for h in hits:
            print(f"   [{h.score:>5.1f}] {h.source}")
        print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Eval/tra cứu thử hệ thống tra cứu luật (offline)")
    ap.add_argument("--query", help="tra cứu thử 1 câu hỏi (so sánh in_force/closure)")
    ap.add_argument("--top-k", type=int, default=4)
    args = ap.parse_args()
    if args.query:
        query_demo(args.query, args.top_k)
        raise SystemExit(0)

    print("== Retrieval (keyword, offline) — closure/in-force OFF vs ON ==")
    print(f"{'config':28} {'recall@k':>9} {'mrr':>6} {'hit@k':>6}")
    for label, kw in (("baseline", {}), ("+closure", {"closure": True}),
                      ("+in_force", {"in_force": True}),
                      ("+closure+in_force", {"closure": True, "in_force": True})):
        m = eval_retrieval(top_k=5, **kw)
        print(f"{label:28} {m['recall@k']:>9} {m['mrr']:>6} {m['hit@k']:>6}")

    c = eval_closure()
    print(f"\n== Closure value (ca dẫn chiếu chéo, top_k={c['top_k']}) ==")
    print(f"  recall OFF={c['recall_off']}  ON={c['recall_on']}  delta=+{c['delta']}  ({c['closure_cases']} ca)")

    print("\n== In-force filter (corpus tạm: 1 còn + 1 hết hiệu lực) ==")
    f = eval_in_force()
    print(f"  still-good-law accuracy={f['still_good_law_accuracy']}  "
          f"expired ẩn mặc định={not f['expired_shown_default']}  "
          f"hiện lại khi hỏi lịch sử={f['expired_surfaced_on_historical']}")

    print("\n== In-force filter (CORPUS THẬT: TT 39/2014 hết hiệu lực vs NĐ 123/2020 còn hiệu lực) ==")
    g = eval_in_force_real()
    print(f"  still-good-law accuracy: OFF={g['accuracy_off']} → ON={g['accuracy_on']}  "
          f"(văn bản hết hiệu lực lọt khi OFF: {g['expired_in_off'] or 'không'})")
