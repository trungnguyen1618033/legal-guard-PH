"""Eval NLI: so các model `judge` (flash vs flagship) trên tác vụ entailment pháp lý.

Vì sao: latency tối ưu bằng cách cho việc NLI/verify yes/no chạy `qwen-flash` thay vì `qwen3.7-max`.
File này KIỂM CHỨNG quyết định đó bằng số: flash có khớp flagship + đúng gold không, trên bộ ca có
nhãn (rõ-hỗ-trợ / rõ-không / lạc đề / KHÓ: số học, mập mờ). Evidence = trích NGUYÊN VĂN điều luật trong
KB (không bịa); gold = phán đoán entailment từ chính đoạn evidence đó.

Chạy (gọi LLM thật):
    uv run python -m evaluation.nli_eval                          # mặc định: qwen-flash vs qwen3.7-max
    uv run python -m evaluation.nli_eval --models qwen-flash,qwen-plus,qwen3.7-max
Lưu ý: qwen3.7-max ~23s/call → ~7 phút cho cả bộ; flash/plus ~0.5s.
"""
from __future__ import annotations

import argparse
import time

from legalguard.adapters.outbound.qwen import QwenAdapter
from legalguard.config.settings import settings
from legalguard.domain.verification import nli_supports

# Evidence = nguyên văn điều luật (KB). gold=True: evidence HẬU THUẪN claim; False: không/ngược lại.
_E301 = ("Điều 301. Mức phạt vi phạm. Mức phạt đối với vi phạm nghĩa vụ hợp đồng hoặc tổng mức phạt đối "
         "với nhiều vi phạm do các bên thoả thuận trong hợp đồng, nhưng không quá 8% giá trị phần nghĩa "
         "vụ hợp đồng bị vi phạm, trừ trường hợp quy định tại Điều 266 của Luật này.")
_E294 = ("Điều 294. Các trường hợp miễn trách nhiệm. 1. Bên vi phạm được miễn trách nhiệm khi: a) trường "
         "hợp các bên đã thoả thuận; b) sự kiện bất khả kháng; c) hành vi vi phạm hoàn toàn do lỗi của bên "
         "kia; d) do thực hiện quyết định của cơ quan nhà nước có thẩm quyền mà các bên không thể biết. "
         "2. Bên vi phạm có nghĩa vụ chứng minh các trường hợp miễn trách nhiệm.")
_E302 = ("Điều 302. Bồi thường thiệt hại. Giá trị bồi thường bao gồm giá trị tổn thất thực tế, trực tiếp "
         "mà bên bị vi phạm phải chịu và khoản lợi trực tiếp đáng lẽ được hưởng nếu không có vi phạm.")
_E306 = ("Điều 306. Quyền yêu cầu tiền lãi do chậm thanh toán. Bên bị vi phạm có quyền yêu cầu trả tiền "
         "lãi trên số tiền chậm trả theo lãi suất nợ quá hạn trung bình trên thị trường tại thời điểm "
         "thanh toán, trừ trường hợp có thoả thuận khác hoặc pháp luật có quy định khác.")
_E297 = ("Điều 297. Buộc thực hiện đúng hợp đồng. Trường hợp giao hàng kém chất lượng thì phải loại trừ "
         "khuyết tật hoặc giao hàng khác thay thế. Bên vi phạm KHÔNG được dùng tiền hoặc hàng khác chủng "
         "loại để thay thế nếu không được bên bị vi phạm chấp thuận.")

GOLDEN: list[tuple[str, str, str, bool]] = [
    # (id, evidence, claim, gold)
    ("301-cap-yes", _E301, "Mức phạt vi phạm tối đa không quá 8% giá trị phần nghĩa vụ bị vi phạm.", True),
    ("301-total-yes", _E301, "Tổng mức phạt cho nhiều vi phạm cũng không vượt quá 8%.", True),
    ("301-free-no", _E301, "Các bên được tự do thỏa thuận mức phạt không bị giới hạn.", False),
    ("301-offtopic-no", _E301, "Tranh chấp được giải quyết bằng trọng tài tại Bắc Kinh theo quy tắc CIETAC.", False),
    ("301-num-no", _E301, "Thỏa thuận mức phạt 10% giá trị hợp đồng là hợp lệ theo điều này.", False),
    ("294-fm-yes", _E294, "Sự kiện bất khả kháng là một trường hợp được miễn trách nhiệm.", True),
    ("294-otherfault-yes", _E294, "Vi phạm hoàn toàn do lỗi của bên kia thì được miễn trách nhiệm.", True),
    ("294-proof-no", _E294, "Bên vi phạm không cần chứng minh trường hợp miễn trách nhiệm.", False),
    ("294-finance-no", _E294, "Khó khăn tài chính của bên vi phạm là căn cứ được miễn trách nhiệm.", False),
    ("302-scope-yes", _E302, "Bồi thường gồm tổn thất thực tế trực tiếp và khoản lợi đáng lẽ được hưởng.", True),
    ("302-indirect-no", _E302, "Bồi thường bao gồm cả thiệt hại gián tiếp và tổn thất tinh thần.", False),
    ("306-interest-yes", _E306, "Bên bị vi phạm có quyền yêu cầu tiền lãi trên số tiền chậm trả theo lãi suất "
                                "nợ quá hạn trung bình thị trường.", True),
    ("306-noright-no", _E306, "Chậm thanh toán tiền hàng không làm phát sinh quyền yêu cầu tiền lãi.", False),
    ("306-fixed-no", _E306, "Lãi suất chậm trả được ấn định cố định 8%/năm theo điều luật này.", False),
    ("297-replace-yes", _E297, "Giao hàng kém chất lượng thì phải loại trừ khuyết tật hoặc giao hàng thay thế.", True),
    ("297-money-no", _E297, "Bên vi phạm được dùng tiền để thay thế hàng mà không cần bên kia đồng ý.", False),
]


def _eval_model(model: str) -> dict:
    judge = QwenAdapter(settings.qwen_api_key, settings.qwen_base_url, model)
    verdicts: dict[str, bool | None] = {}
    t0 = time.perf_counter()
    correct = wrong = abstain = 0
    for cid, ev, claim, gold in GOLDEN:
        v = nli_supports(claim, ev, judge)
        verdicts[cid] = v
        if v is None:
            abstain += 1
        elif v == gold:
            correct += 1
        else:
            wrong += 1
    ms = round((time.perf_counter() - t0) * 1000 / len(GOLDEN))
    return {"model": model, "correct": correct, "wrong": wrong, "abstain": abstain,
            "ms_per_call": ms, "verdicts": verdicts}


def main() -> None:
    ap = argparse.ArgumentParser(description="Eval NLI judge: flash vs flagship trên ca pháp lý có nhãn")
    ap.add_argument("--models", default="qwen-flash,qwen3.7-max")
    args = ap.parse_args()
    if not settings.qwen_api_key:
        raise SystemExit("Cần QWEN_API_KEY (gọi LLM thật).")

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    n = len(GOLDEN)
    print(f"NLI eval — {n} ca (evidence = điều luật KB thật). Models: {', '.join(models)}\n")
    results = [_eval_model(m) for m in models]

    print(f"{'model':16} {'đúng':>7} {'sai':>5} {'abstain':>8} {'acc':>6} {'ms/call':>9}")
    for r in results:
        acc = r["correct"] / n
        print(f"{r['model']:16} {r['correct']:>5}/{n} {r['wrong']:>5} {r['abstain']:>8} {acc:>6.0%} {r['ms_per_call']:>8}ms")

    if len(results) >= 2:
        ref = results[-1]   # model cuối (thường flagship) làm tham chiếu
        print(f"\nĐồng thuận với '{ref['model']}' (tham chiếu):")
        for r in results[:-1]:
            agree = sum(1 for cid, _, _, _ in GOLDEN if r["verdicts"][cid] == ref["verdicts"][cid])
            print(f"  {r['model']:16} {agree}/{n} ({agree/n:.0%})")
        # Liệt kê ca lệch để soi (model đầu vs tham chiếu).
        first = results[0]
        diffs = [(cid, first["verdicts"][cid], ref["verdicts"][cid], gold)
                 for cid, _, _, gold in GOLDEN if first["verdicts"][cid] != ref["verdicts"][cid]]
        if diffs:
            print(f"\nCa lệch ({first['model']} vs {ref['model']}; gold):")
            for cid, a, b, gold in diffs:
                print(f"  {cid:18} {first['model']}={a}  {ref['model']}={b}  gold={gold}")


if __name__ == "__main__":
    main()
