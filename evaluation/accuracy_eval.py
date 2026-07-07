"""Eval ĐỘ CHÍNH XÁC CÂU TRẢ LỜI tra cứu luật — golden set có đáp án đã biết.

Khác `legal_eval.py` (đo RETRIEVAL: recall/MRR điều luật) — đây đo CÂU TRẢ LỜI: dẫn đúng điều luật
(`must_cite`) + đúng dữ kiện (`must_say`) + BIẾT TỪ CHỐI khi ngoài KB (`abstain`, chống bịa).
Chấm theo NỘI DUNG nguồn (không khớp cứng tên file). Ghi `accuracy_report.json` → trang /trust đọc số THẬT.

Chạy (cần QWEN key): uv run python -m evaluation.accuracy_eval
`judge_case` thuần → test offline; runner gọi LLM thật.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

_GOLDEN = Path("evaluation/accuracy_golden.json")
_REPORT = Path("evaluation/accuracy_report.json")


# Số-chữ tiếng Việt 10-99 → số. Văn bản luật viết CHỮ ("hết hai mươi năm") còn golden ghi SỐ ("20 năm")
# → chuẩn hóa để so công bằng. Điểm tinh tế: sau 'mươi', 5 viết là 'lăm/nhăm' (25='hai mươi lăm'), nên 'năm'
# đứng sau 'mươi' là ĐƠN VỊ THỜI GIAN (year), KHÔNG phải 5 → 'hai mươi năm' = '20 năm' (không nhầm thành 25).
_VN_TENS_W = {"hai": "2", "ba": "3", "bốn": "4", "năm": "5", "sáu": "6", "bảy": "7", "tám": "8", "chín": "9"}
# Đơn vị SAU 'mươi/mười' (CỐ Ý loại 'năm' để tránh nuốt 'năm'=year; 5 chỉ nhận qua 'lăm/nhăm').
_VN_UNIT = {"một": "1", "mốt": "1", "hai": "2", "ba": "3", "bốn": "4", "tư": "4", "lăm": "5", "nhăm": "5",
            "sáu": "6", "bảy": "7", "tám": "8", "chín": "9"}
_TENS = "|".join(_VN_TENS_W)
_UNIT = "|".join(_VN_UNIT)


def _vn_num_to_digits(s: str) -> str:
    """Số-chữ VN → số. 21-99 ('X mươi Y') → trước 10,20..90 ('X mươi') → 11-19 ('mười Y') → 10 ('mười').
    'hai mươi năm'→'20 năm' (không thành 25); 'hai mươi lăm'→'25'; 'chín mươi chín'→'99'; 'mười lăm'→'15'."""
    s = re.sub(rf"\b({_TENS})\s+mươi\s+({_UNIT})\b",
               lambda m: _VN_TENS_W[m.group(1)] + _VN_UNIT[m.group(2)], s)   # 21-99
    s = re.sub(rf"\b({_TENS})\s+mươi\b", lambda m: _VN_TENS_W[m.group(1)] + "0", s)  # 20,30..90
    s = re.sub(rf"\bmười\s+({_UNIT})\b", lambda m: "1" + _VN_UNIT[m.group(1)], s)    # 11-19
    return re.sub(r"\bmười\b", "10", s)                                             # 10


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", (s or "").lower())


def judge_case(case: dict, answer: str, sources: list[str]) -> tuple[bool, str]:
    """Chấm 1 ca: True/False + lý do. THUẦN (test offline). sources = list[str] nguồn (file#Điều)."""
    a, src = _norm(answer), _norm(" ".join(sources))
    if case.get("abstain"):
        ok = ("chưa đủ căn cứ" in a or "không đủ" in a or not sources)
        return ok, ("từ chối đúng (ngoài KB)" if ok else "BỊA — lẽ ra phải từ chối")
    has_cite = all(_norm(c) in src for c in case.get("must_cite", []))
    a_num = _vn_num_to_digits(a)   # 'hai mươi năm' ↔ '20 năm': so dữ-kiện số công bằng dù luật viết chữ
    # Mỗi must_say là 1 dữ-kiện BẮT BUỘC (AND giữa các item). Trong 1 item, '|' = CHẤP mọi cách diễn đạt
    # ĐỒNG NGHĨA đúng-luật (vd 'từ chối|trả lại đơn|không thụ lý' — Đ.6 TTTM cùng ý) → khử nhiễu wording,
    # KHÔNG hạ chuẩn (vẫn phải nói đúng ý). Item không có '|' hoạt động y như trước.
    def _fact_ok(f: str) -> bool:
        return any(_norm(alt) in a or _norm(alt) in a_num for alt in f.split("|") if alt.strip())
    has_fact = all(_fact_ok(f) for f in case.get("must_say", []))
    why = (f"dẫn-nguồn={'✓' if has_cite else '✗ '+str(case.get('must_cite'))} "
           f"dữ-kiện={'✓' if has_fact else '✗ '+str(case.get('must_say'))}")
    return (has_cite and has_fact), why


def run(write: bool = True, repeat: int = 1, golden_path: str | None = None) -> dict:
    """`repeat` > 1: chạy MỖI ca `repeat` lần, lấy ĐA SỐ (majority-vote) → chống nhiễu LLM hosted
    (dải 52-54 do stochastic ngay ở temp 0). Số ổn định hơn → đo được thay đổi nhỏ (điều kiện tiên
    quyết THẬT để mở rộng KB an toàn — xem kb-expansion-plan.md)."""
    from legalguard.config.container import build_service
    from legalguard.domain.tenants import default_org

    gp = Path(golden_path) if golden_path else _GOLDEN   # --golden: chạy bộ khác (vd regression mở rộng)
    cases = json.loads(gp.read_text(encoding="utf-8"))["cases"]
    svc, org = build_service(), default_org("VN")
    # QUAN TRỌNG: repeat>1 = majority-vote chống nhiễu → PHẢI tắt cache lookup, nếu không mỗi vote KHÔNG độc
    # lập: abstain KHÔNG được cache còn câu THÀNH CÔNG thì CÓ → ca borderline chỉ cần đậu 1 lần là bị khóa PASS
    # các vote sau → thổi phồng accuracy + giấu FLAKY (đo được: ca 'Năm 2020' no-cache 1/6 nhưng eval cache 3/3).
    if repeat > 1:
        svc._lookup_cache_size = 0
        svc._lookup_cache.clear()
    results, passed = [], 0
    cat: dict[str, list[int]] = {}                       # lĩnh vực → [passed, total]
    for c in cases:
        votes, last_why, last_src, last_ans = [], "", [], ""
        for _ in range(max(1, repeat)):
            ans, snips = svc.lookup(c["question"], org, lang="vi")
            ok, why = judge_case(c, ans, [s.source for s in snips])
            votes.append(ok)
            last_why, last_src, last_ans = why, [s.source for s in snips[:2]], ans
        ok = sum(votes) * 2 >= len(votes)                # ĐA SỐ (hòa → đậu)
        flaky = 0 < sum(votes) < len(votes)              # dao động giữa các lần = ca borderline
        passed += ok
        cc = c.get("category", "Khác")
        cat.setdefault(cc, [0, 0])
        cat[cc][0] += ok
        cat[cc][1] += 1
        results.append({"q": c["question"], "category": cc, "ok": ok, "why": last_why,
                        "flaky": flaky, "votes": f"{sum(votes)}/{len(votes)}",
                        "sources": last_src, "answer": last_ans[:160]})
        tag = "⚠️FLAKY" if flaky else ("✅" if ok else "❌")
        print(f"[{tag}] ({cc}) {c['question'][:46]}  votes={sum(votes)}/{len(votes)}\n     {last_why}")
    acc = round(passed / len(cases), 3) if cases else 0.0
    by_category = {k: {"passed": v[0], "total": v[1], "accuracy": round(v[0] / v[1], 3)}
                   for k, v in cat.items()}
    flaky_n = sum(1 for r in results if r.get("flaky"))
    report = {"answer_accuracy": acc, "passed": passed, "total": len(cases),
              "repeat": repeat, "flaky_cases": flaky_n,
              "by_category": by_category, "cases": results}
    print("\n--- Theo lĩnh vực ---")
    for k, v in by_category.items():
        print(f"  {k}: {v['passed']}/{v['total']} = {v['accuracy']:.0%}")
    print(f"\n=== ĐỘ CHÍNH XÁC CÂU TRẢ LỜI: {passed}/{len(cases)} = {acc:.0%} "
          f"(repeat={repeat}, flaky={flaky_n}) ===")
    if write:
        _REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Đã ghi {_REPORT} → trang /trust sẽ hiện số này.")
    return report


if __name__ == "__main__":
    import re
    import sys
    # --no-write: chạy THÍ NGHIỆM (vd KNOWLEDGE_BASE_DIR override để thử KB mở rộng) mà KHÔNG ghi đè
    # accuracy_report.json production (tránh làm bẩn số /trust). Mặc định vẫn ghi (đo chính thức).
    # --repeat N: majority-vote N lần/ca → số ổn định, hiện ca FLAKY (chống nhiễu LLM hosted).
    rep = next((int(m.group(1)) for a in sys.argv if (m := re.match(r"--repeat=(\d+)", a))), 1)
    gpath = next((m.group(1) for a in sys.argv if (m := re.match(r"--golden=(.+)", a))), None)
    run(write="--no-write" not in sys.argv, repeat=rep, golden_path=gpath)
