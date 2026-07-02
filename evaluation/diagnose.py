"""Chẩn đoán TỪNG CA golden — mổ xẻ pipeline để tìm ROOT CAUSE ca fail/flaky (không đoán).

Với mỗi ca (lọc theo --grep hoặc --fail-only), chạy `repeat` lần và in đủ chuỗi:
  retrieve (nguồn+score) → elbow keep → cổng relevance (sources_answer_question) → lookup answer → judge.
→ Phân loại root cause: RETRIEVAL-MISS (không ra điều đúng) · GATE-ABSTAIN (cổng từ chối oan) ·
  ANSWER-WRONG (ra điều đúng nhưng LLM trả sai) · JUDGE-STRICT (đúng nhưng must_say/must_cite lệch) · FLAKY.

Chạy: uv run python -m evaluation.diagnose --grep "nhãn hiệu,ly hôn" --repeat 2   (cần QWEN key)
      uv run python -m evaluation.diagnose --fail-only --repeat 2                 (quét toàn bộ, chỉ hiện ca có lần fail)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.accuracy_eval import judge_case

_GOLDEN = Path("evaluation/accuracy_golden.json")


def _classify(case: dict, retrieved_srcs: list[str], gate_ok, answered: bool, judged_ok: bool) -> str:
    """Gán nhãn root cause từ tín hiệu pipeline (tất định)."""
    must_cite = [c.lower() for c in case.get("must_cite", [])]
    hit_src = all(any(mc in s.lower() for s in retrieved_srcs) for mc in must_cite) if must_cite else True
    if judged_ok:
        return "PASS"
    if not hit_src:
        return "RETRIEVAL-MISS (điều/văn bản đúng KHÔNG trong top-k)"
    if gate_ok is False or not answered:
        return "GATE-ABSTAIN (retrieve đúng nhưng cổng relevance từ chối → abstain oan)"
    return "ANSWER/JUDGE (ra điều đúng, answer thiếu must_say hoặc LLM diễn giải lệch)"


def run(grep: str | None, fail_only: bool, repeat: int) -> None:
    from legalguard.config.container import build_service
    from legalguard.domain.tenants import default_org
    from legalguard.domain.verification import elbow_cutoff, sources_answer_question

    svc, org = build_service(), default_org("VN")
    cases = json.loads(_GOLDEN.read_text(encoding="utf-8"))["cases"]
    terms = [t.strip().lower() for t in (grep or "").split(",") if t.strip()]
    if terms:
        cases = [c for c in cases if any(t in c["question"].lower() for t in terms)]

    for c in cases:
        votes, diag = [], None
        for _ in range(max(1, repeat)):
            svc._lookup_cache.clear()                          # mỗi lần chạy THẬT (không cache)
            snips = svc.kb.for_org(org, overlay=False).retrieve(c["question"], 5)
            srcs = [s.source for s in snips]
            keep = elbow_cutoff([s.score for s in snips]) if snips else 0
            gate_src = "\n---\n".join(f"[nguồn: {s.source}] {s.text}" for s in snips[:keep])
            gate_ok = sources_answer_question(c["question"], gate_src, svc.judge) if snips else None
            ans, asnips = svc.lookup(c["question"], org, lang="vi")
            answered = "chưa đủ căn cứ" not in ans.lower()
            ok, why = judge_case(c, ans, [s.source for s in asnips])
            votes.append(ok)
            diag = (srcs, [round(s.score, 3) for s in snips], keep, gate_ok, answered, why)
        srcs, scores, keep, gate_ok, answered, why = diag
        if fail_only and all(votes):
            continue
        tag = "⚠️FLAKY" if 0 < sum(votes) < len(votes) else ("✅PASS" if sum(votes) else "❌FAIL")
        root = _classify(c, srcs, gate_ok, answered, sum(votes) == len(votes))
        print(f"\n{tag} votes={sum(votes)}/{len(votes)} — {c['category']}")
        print(f"  Q: {c['question']}")
        print(f"  must_cite={case_must(c)} must_say={c.get('must_say')}")
        print(f"  retrieve: {list(zip([s.split('#')[0].replace('.md','')+('#'+s.split('#')[1] if '#' in s else '') for s in srcs[:4]], scores[:4]))}")
        print(f"  elbow keep={keep} · gate={gate_ok} · answered={answered}")
        print(f"  → ROOT: {root}")
        print(f"  why: {why}")


def case_must(c: dict) -> list:
    return c.get("must_cite", [])


def main() -> None:
    ap = argparse.ArgumentParser(description="Chẩn đoán từng ca golden (root cause)")
    ap.add_argument("--grep", default=None, help="lọc câu hỏi chứa từ (phẩy = OR)")
    ap.add_argument("--fail-only", action="store_true", help="chỉ hiện ca có ít nhất 1 lần fail")
    ap.add_argument("--repeat", type=int, default=2)
    args = ap.parse_args()
    run(args.grep, args.fail_only, args.repeat)


if __name__ == "__main__":
    main()
