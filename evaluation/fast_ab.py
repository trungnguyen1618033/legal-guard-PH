"""A/B FAST-PATH model — đo THẬT chất lượng/latency của model dùng cho `mode=fast` (flagship vs plus vs flash).

Trả lời câu "đổi flagship→plus có giảm chính xác không" bằng SỐ thay vì n=1. Bộ HĐ có NHÃN đúng-sai
(neo luật VN: phạt >8% LTM Đ.301, lãi >20%/năm BLDS Đ.468 = illegal; 120-ngày/đơn phương/luật nước ngoài =
unfavorable hợp pháp). Đo 3 model × N lần (khử nhiễu LLM hosted stochastic) → đếm:
  - illegal_recall: trong các điều khoản TRÁI LUẬT thật, model gắn `illegal` = bao nhiêu (cao = tốt)
  - miss_illegal:   trái luật thật bị hạ xuống unfavorable / không bắt (THẤP = tốt — hướng NGUY HIỂM)
  - overflag:       unfavorable-hợp-pháp bị gắn illegal (thấp = tốt — hướng AN TOÀN, chấp nhận được hơn miss)
  - detect_recall:  bắt được điều khoản (bất kể nhãn) — đo độ "sót nguyên điều khoản"
KHÔNG cần KB (dùng fast_review + DummyKB) → chạy nhanh, không treo embedding. Cần QWEN_API_KEY.

Chạy: uv run python -m evaluation.fast_ab [--reps 2] [--models plus,flash,flagship] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field

from legalguard.adapters.outbound.qwen import QwenAdapter
from legalguard.config.settings import settings
from legalguard.domain.fast_review import fast_review
from legalguard.domain.models import AgentContext, NegotiationPosition


class _DummyKB:
    def retrieve(self, q: str, top_k: int = 4):  # noqa: ARG002 — fast không tra KB lúc trích
        return []


@dataclass
class Clause:
    anchor: str        # neo nhận diện trong risk.clause/evidence (vd "Điều 5", "30%")
    label: str         # "illegal" | "unfavorable"
    why: str


@dataclass
class Case:
    name: str
    text: str
    clauses: list[Clause]
    protected: str = "Bên B (SME Việt Nam)"


# Bộ có nhãn — mỗi HĐ trộn illegal + unfavorable để 1 call phủ nhiều nhãn (rẻ). Neo bằng điều + số đặc trưng.
CASES: list[Case] = [
    Case(
        name="thuong_mai",
        text=(
            "HỢP ĐỒNG CUNG CẤP HÀNG HÓA (thương mại)\n"
            "Điều 5. Phạt vi phạm: Bên B chịu phạt 30% giá trị hợp đồng nếu chậm giao quá 3 ngày.\n"
            "Điều 8. Thanh toán: Bên A thanh toán trong vòng 120 ngày kể từ ngày nhận hàng và hóa đơn.\n"
            "Điều 12. Chấm dứt: Bên A được đơn phương chấm dứt bất cứ lúc nào không cần lý do và không "
            "bồi thường; Bên B không có quyền tương ứng.\n"
        ),
        clauses=[
            Clause("Điều 5", "illegal", "phạt 30% > trần 8% LTM Đ.301"),
            Clause("Điều 8", "unfavorable", "120 ngày bất lợi dòng tiền nhưng hợp pháp"),
            Clause("Điều 12", "unfavorable", "đơn phương chấm dứt lệch — bất lợi, không đương nhiên trái luật"),
        ],
    ),
    Case(
        name="vay_dich_vu",
        text=(
            "HỢP ĐỒNG VAY VÀ DỊCH VỤ\n"
            "Điều 3. Lãi suất: Bên vay chịu lãi 60%/năm; lãi quá hạn bằng 200% lãi trong hạn.\n"
            "Điều 7. Luật áp dụng: Hợp đồng chịu điều chỉnh bởi luật Anh, giải quyết tranh chấp tại tòa "
            "án London.\n"
            "Điều 9. Bảo mật: Bên B không được tiết lộ thông tin trong 5 năm sau khi chấm dứt.\n"
        ),
        clauses=[
            Clause("Điều 3", "illegal", "lãi 60%/năm > trần 20%/năm BLDS Đ.468"),
            Clause("Điều 7", "unfavorable", "luật nước ngoài + tài phán London bất lợi SME VN, hợp pháp"),
            Clause("Điều 9", "unfavorable", "NDA 5 năm — khắt khe nhưng không trái luật"),
        ],
    ),
]


@dataclass
class ModelStat:
    model: str
    reps: int = 0
    latencies: list[float] = field(default_factory=list)
    illegal_hit: int = 0       # điều khoản illegal-thật được gắn illegal (cộng dồn qua rep)
    illegal_total: int = 0
    miss_illegal: int = 0      # illegal-thật KHÔNG được gắn illegal (hạ/không bắt)
    unfav_total: int = 0
    overflag: int = 0          # unfavorable-thật bị gắn illegal
    detect_hit: int = 0        # điều khoản (bất kể nhãn) được bắt
    detect_total: int = 0


def _find(risks: list, anchor: str):
    """Risk nào khớp neo (theo tên điều khoản hoặc evidence). None nếu không bắt được điều khoản đó."""
    for r in risks:
        hay = f"{getattr(r, 'clause', '')} {getattr(r, 'evidence', '')}"
        if anchor in hay:
            return r
    return None


def run(models: list[str], reps: int) -> dict:
    name_to_model = {
        "flagship": settings.qwen_model,
        "plus": settings.qwen_lookup_model,
        "flash": settings.qwen_fast_model,
    }
    pos = NegotiationPosition(leverage="balanced", urgency="low")
    stats: dict[str, ModelStat] = {}
    for key in models:
        model_id = name_to_model[key]
        st = ModelStat(model=f"{key} ({model_id})")
        adapter = QwenAdapter(api_key=settings.qwen_api_key, base_url=settings.qwen_base_url, model=model_id)
        if not adapter.available:
            raise SystemExit("QWEN_API_KEY chưa cấu hình — A/B cần LLM thật.")
        for _ in range(reps):
            for case in CASES:
                ctx = AgentContext(retriever=_DummyKB())
                pos.protected_party = case.protected
                t0 = time.time()
                fast_review(adapter, case.text, "Vietnam", "vi", pos, ctx)
                st.latencies.append(time.time() - t0)
                st.reps += 1
                for cl in case.clauses:
                    st.detect_total += 1
                    r = _find(ctx.risks, cl.anchor)
                    if r is not None:
                        st.detect_hit += 1
                    got = getattr(r, "legal_status", None) if r is not None else None
                    if cl.label == "illegal":
                        st.illegal_total += 1
                        if got == "illegal":
                            st.illegal_hit += 1
                        else:                      # bỏ sót/hạ trái luật = NGUY HIỂM
                            st.miss_illegal += 1
                    else:                          # unfavorable-thật
                        st.unfav_total += 1
                        if got == "illegal":
                            st.overflag += 1
        stats[key] = st

    def pct(a: int, b: int) -> float:
        return round(100 * a / b, 1) if b else 0.0

    report = {"reps": reps, "cases": [c.name for c in CASES], "models": {}}
    for key, st in stats.items():
        avg = round(sum(st.latencies) / len(st.latencies), 1) if st.latencies else 0.0
        report["models"][key] = {
            "model": st.model,
            "avg_latency_s": avg,
            "detect_recall_pct": pct(st.detect_hit, st.detect_total),
            "illegal_recall_pct": pct(st.illegal_hit, st.illegal_total),
            "miss_illegal": st.miss_illegal,
            "miss_illegal_pct": pct(st.miss_illegal, st.illegal_total),
            "overflag": st.overflag,
            "overflag_pct": pct(st.overflag, st.unfav_total),
            "n_illegal": st.illegal_total,
            "n_unfav": st.unfav_total,
        }
    return report


def _print(rep: dict) -> None:
    print(f"\n=== FAST-PATH A/B (reps={rep['reps']}, cases={rep['cases']}) ===")
    hdr = f"{'model':<10} {'lat(s)':>7} {'detect%':>8} {'illegal_recall%':>16} {'MISS_illegal%':>14} {'overflag%':>10}"
    print(hdr)
    print("-" * len(hdr))
    for key, m in rep["models"].items():
        print(f"{key:<10} {m['avg_latency_s']:>7} {m['detect_recall_pct']:>8} "
              f"{m['illegal_recall_pct']:>16} {m['miss_illegal_pct']:>14} {m['overflag_pct']:>10}")
    print("\nMISS_illegal = bỏ sót/hạ trái luật (THẤP tốt — hướng NGUY HIỂM); "
          "overflag = báo dư (thấp tốt nhưng AN TOÀN hơn miss).")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--models", default="flagship,plus,flash")
    ap.add_argument("--out", default="evaluation/fast_ab_report.json")
    args = ap.parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    rep = run(models, args.reps)
    _print(rep)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    print(f"\n→ {args.out}")


if __name__ == "__main__":
    main()
