"""BENCHMARK FAST-PATH TRÊN PROD THẬT — chứng minh latency + độ chính xác bằng SỐ (chuẩn ContractEval/CUAD).

Gọi /analyze (mode=fast) trên deploy THẬT với bộ HĐ CÓ NHÃN đa lĩnh vực (neo luật VN). Metric theo chuẩn
clause-level legal risk ID (ContractEval arXiv:2508.03080, CUAD arXiv:2103.06268):
  - PHÁT HIỆN RỦI RO (mọi điều khoản, gồm ca ÂM/clean): Precision / Recall / F1 / **F2** (ưu tiên recall vì
    bỏ sót nguy hiểm hơn báo dư) + Wilson 95% CI. TP=điều-khoản-rủi-ro được flag; FP=điều-khoản-clean bị flag
    (false alarm); FN=rủi-ro bị bỏ sót ("laziness").
  - PHÂN LOẠI TRÁI LUẬT: illegal_recall / miss_illegal (NGUY HIỂM) / over-flag (Miss↔Extra trade-off).
  - Latency: median/p95/p99 + mean ± CI. Per-domain. ⚡warning/human-review/counter_inline(fast phải 0).
TỰ DỌN case (DELETE /cases/{id}). --deep K để so latency deep.
LƯU Ý: nhãn do tác giả gán (neo luật VN rõ ràng), CHƯA luật-sư-verify → là smoke/regression, không phải golden.

Chạy: API_BASE=.. API_KEYS=.. uv run python -m scripts.fast_bench_live [--reps 3] [--deep 2] [--keep]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000").rstrip("/")
KEY = os.environ.get("API_KEY") or (
    os.environ.get("API_KEYS", "").strip('"').split(",")[0].split(":")[0] if os.environ.get("API_KEYS") else "")

ILLEGAL, UNFAV, CLEAN = "illegal", "unfavorable", "clean"


@dataclass
class Clause:
    anchor: str          # neo nhận diện trong risk.clause/evidence
    label: str           # illegal | unfavorable | clean
    why: str


@dataclass
class Case:
    name: str
    domain: str
    text: str
    clauses: list[Clause]
    protected: str = "Bên B (SME Việt Nam)"


# Bộ HĐ có NHÃN — đa lĩnh vực, mỗi HĐ trộn illegal/unfavorable/CLEAN (clean = không-nên-flag → đo false alarm).
CASES: list[Case] = [
    Case("tm_phat30", "thuong_mai", "HỢP ĐỒNG CUNG CẤP HÀNG HÓA\n"
         "Điều 5. Phạt vi phạm: Bên B chịu phạt 30% giá trị hợp đồng nếu chậm giao quá 3 ngày.\n"
         "Điều 8. Thanh toán: Bên A thanh toán trong vòng 120 ngày kể từ ngày nhận hàng.\n"
         "Điều 11. Thông báo: Mọi thông báo gửi bằng văn bản tới địa chỉ ghi trong hợp đồng.\n",
         [Clause("Điều 5", ILLEGAL, "phạt 30% > trần 8% LTM Đ.301"),
          Clause("Điều 8", UNFAV, "120 ngày bất lợi dòng tiền, hợp pháp"),
          Clause("Điều 11", CLEAN, "điều khoản thông báo tiêu chuẩn — vô hại")]),
    Case("vay_lai60", "lai_vay", "HỢP ĐỒNG VAY\n"
         "Điều 3. Lãi suất: 60%/năm; lãi quá hạn bằng 200% lãi trong hạn.\n"
         "Điều 6. Mục đích vay: Bên vay dùng vốn đúng mục đích kinh doanh đã khai.\n",
         [Clause("Điều 3", ILLEGAL, "lãi 60%/năm > trần 20%/năm BLDS Đ.468"),
          Clause("Điều 6", CLEAN, "cam kết mục đích vay — tiêu chuẩn")]),
    Case("dv_chamdut", "dich_vu", "HỢP ĐỒNG DỊCH VỤ\n"
         "Điều 10. Chấm dứt: Bên A đơn phương chấm dứt bất cứ lúc nào không cần lý do, không bồi thường; "
         "Bên B không có quyền tương ứng.\n"
         "Điều 12. Luật áp dụng: luật Anh, tranh chấp tại tòa London.\n",
         [Clause("Điều 10", UNFAV, "đơn phương lệch — bất lợi, không đương nhiên trái luật"),
          Clause("Điều 12", UNFAV, "luật nước ngoài + tài phán London bất lợi SME VN")]),
    Case("xd_phat15", "xay_dung", "HỢP ĐỒNG THI CÔNG XÂY DỰNG\n"
         "Điều 7. Phạt chậm tiến độ: 15% giá trị hợp đồng cho mỗi tuần chậm.\n"
         "Điều 9. Bảo hành: Bên B bảo hành công trình 24 tháng kể từ nghiệm thu.\n",
         [Clause("Điều 7", ILLEGAL, "phạt 15% vượt trần (LTM 8% / XD 12%)"),
          Clause("Điều 9", CLEAN, "bảo hành 24 tháng — điều kiện tiêu chuẩn, hợp lệ")]),
    Case("nda_shtt", "shtt", "HỢP ĐỒNG HỢP TÁC\n"
         "Điều 4. Bảo mật: Bên B không tiết lộ thông tin trong 10 năm sau chấm dứt.\n"
         "Điều 5. Sở hữu trí tuệ: Mọi sáng tạo của Bên B trong VÀ NGOÀI phạm vi hợp đồng đều thuộc Bên A.\n",
         [Clause("Điều 4", UNFAV, "NDA 10 năm khắt khe nhưng hợp pháp"),
          Clause("Điều 5", UNFAV, "giao SHTT quá rộng (ngoài phạm vi) — bất lợi")]),
    Case("mb_phat50", "thuong_mai", "HỢP ĐỒNG MUA BÁN\n"
         "Điều 6. Phạt vi phạm hợp đồng: 50% giá trị đơn hàng nếu hủy đơn.\n"
         "Điều 8. Giao hàng: giao tại kho Bên A trong 15 ngày kể từ đặt hàng.\n",
         [Clause("Điều 6", ILLEGAL, "phạt 50% > trần 8% LTM Đ.301"),
          Clause("Điều 8", CLEAN, "điều khoản giao hàng tiêu chuẩn")]),
    Case("ld_thuviec", "lao_dong", "HỢP ĐỒNG LAO ĐỘNG\n"
         "Điều 3. Thử việc: 6 tháng với lương 70% lương chính thức.\n"
         "Điều 7. Nghỉ phép: người lao động được 12 ngày phép năm.\n",
         [Clause("Điều 3", UNFAV, "thử việc 6 tháng/lương thấp — cần đối chiếu BLLĐ"),
          Clause("Điều 7", CLEAN, "12 ngày phép năm — đúng luật, vô hại")]),
    Case("thue_datcoc", "dan_su", "HỢP ĐỒNG THUÊ\n"
         "Điều 4. Đặt cọc: Bên B đặt cọc 6 tháng tiền thuê, KHÔNG hoàn lại trong mọi trường hợp.\n"
         "Điều 9. Thời hạn: hợp đồng thuê 2 năm, gia hạn theo thỏa thuận.\n",
         [Clause("Điều 4", UNFAV, "cọc không hoàn 'mọi trường hợp' bất lợi"),
          Clause("Điều 9", CLEAN, "thời hạn thuê 2 năm — tiêu chuẩn")]),
    Case("vay_phat25", "lai_vay", "HỢP ĐỒNG VAY VỐN\n"
         "Điều 2. Lãi suất: 15%/năm.\n"
         "Điều 5. Phạt trả chậm: phạt 25% số dư nợ mỗi kỳ chậm thanh toán.\n",
         [Clause("Điều 2", CLEAN, "lãi 15%/năm < trần 20% — hợp pháp, không nên flag"),
          Clause("Điều 5", ILLEGAL, "phạt 25% + lãi có thể vượt trần/chồng chế tài")]),
    Case("tm_batloi", "thuong_mai", "HỢP ĐỒNG PHÂN PHỐI\n"
         "Điều 6. Độc quyền: Bên B chỉ được bán sản phẩm của Bên A, cấm kinh doanh sản phẩm khác 5 năm.\n"
         "Điều 10. Sửa đổi: mọi sửa đổi phải lập thành văn bản có chữ ký hai bên.\n",
         [Clause("Điều 6", UNFAV, "độc quyền ràng buộc rộng/dài — bất lợi Bên B"),
          Clause("Điều 10", CLEAN, "điều khoản sửa đổi bằng văn bản — tiêu chuẩn")]),
    Case("dt_gopvon", "dau_tu", "HỢP ĐỒNG GÓP VỐN\n"
         "Điều 5. Rút vốn: Bên B không được rút vốn trong 10 năm, nếu rút mất toàn bộ lợi tức đã chia.\n"
         "Điều 8. Báo cáo: Bên A gửi báo cáo tài chính hằng quý cho Bên B.\n",
         [Clause("Điều 5", UNFAV, "khóa vốn 10 năm + phạt mất lợi tức — bất lợi"),
          Clause("Điều 8", CLEAN, "nghĩa vụ báo cáo quý — tiêu chuẩn")]),
    Case("dv_boithuong", "dich_vu", "HỢP ĐỒNG DỊCH VỤ TƯ VẤN\n"
         "Điều 7. Giới hạn trách nhiệm: Bên A không chịu trách nhiệm cho MỌI thiệt hại kể cả do lỗi cố ý.\n"
         "Điều 9. Phí: thanh toán theo giai đoạn nghiệm thu.\n",
         [Clause("Điều 7", ILLEGAL, "miễn trách kể cả lỗi cố ý — vô hiệu BLDS"),
          Clause("Điều 9", CLEAN, "thanh toán theo nghiệm thu — tiêu chuẩn")]),
    Case("mb_rui_ro", "thuong_mai", "HỢP ĐỒNG MUA BÁN QUỐC TẾ\n"
         "Điều 4. Chuyển rủi ro: Bên B (bán) chịu mọi rủi ro tới khi Bên A xác nhận nhận đủ, không theo Incoterms.\n"
         "Điều 12. Ngôn ngữ: hợp đồng lập bằng tiếng Việt và tiếng Anh, bản tiếng Anh ưu tiên.\n",
         [Clause("Điều 4", UNFAV, "chuyển rủi ro bất lợi bên bán"),
          Clause("Điều 12", CLEAN, "song ngữ, ưu tiên EN — phổ biến, không sai luật")]),
    Case("tm_sach", "thuong_mai", "HỢP ĐỒNG DỊCH VỤ CƠ BẢN\n"
         "Điều 3. Phạt vi phạm: phạt 6% giá trị phần nghĩa vụ vi phạm.\n"
         "Điều 5. Bảo mật: hai bên giữ bí mật thông tin trong thời hạn hợp đồng.\n",
         [Clause("Điều 3", CLEAN, "phạt 6% < trần 8% LTM — HỢP PHÁP, không nên flag illegal"),
          Clause("Điều 5", CLEAN, "bảo mật trong thời hạn — tiêu chuẩn")]),
    Case("ld_canhtranh", "lao_dong", "HỢP ĐỒNG LAO ĐỘNG CẤP CAO\n"
         "Điều 8. Không cạnh tranh: sau nghỉ việc, NLĐ không được làm cho đối thủ trong 3 năm, không bồi thường.\n"
         "Điều 10. Lương: trả qua tài khoản ngân hàng vào ngày 5 hằng tháng.\n",
         [Clause("Điều 8", UNFAV, "non-compete 3 năm không bồi thường — bất lợi/khó thực thi"),
          Clause("Điều 10", CLEAN, "cách trả lương — tiêu chuẩn")]),
    Case("vay_lai36", "lai_vay", "HỢP ĐỒNG VAY TIÊU DÙNG\n"
         "Điều 2. Lãi suất: 36%/năm tính trên dư nợ gốc.\n"
         "Điều 4. Kỳ hạn: vay 12 tháng, trả gốc và lãi hằng tháng.\n",
         [Clause("Điều 2", ILLEGAL, "lãi 36%/năm > trần 20%/năm BLDS Đ.468"),
          Clause("Điều 4", CLEAN, "kỳ hạn trả góp — tiêu chuẩn")]),
    Case("tm_phat20", "thuong_mai", "HỢP ĐỒNG GIA CÔNG\n"
         "Điều 6. Phạt vi phạm: 20% giá trị hợp đồng nếu giao sản phẩm không đạt chuẩn.\n"
         "Điều 9. Kiểm tra: Bên A kiểm tra chất lượng trong 7 ngày kể từ nhận hàng.\n",
         [Clause("Điều 6", ILLEGAL, "phạt 20% > trần 8% LTM Đ.301"),
          Clause("Điều 9", CLEAN, "thời hạn kiểm tra chất lượng — tiêu chuẩn")]),
    Case("hoadon_tron", "thue", "HỢP ĐỒNG DỊCH VỤ\n"
         "Điều 5. Hóa đơn: Hai bên thống nhất KHÔNG xuất hóa đơn cho phần thanh toán tiền mặt để giảm thuế.\n"
         "Điều 7. Nghiệm thu: hai bên ký biên bản nghiệm thu khi hoàn thành.\n",
         [Clause("Điều 5", ILLEGAL, "thỏa thuận không xuất hóa đơn trốn thuế — vi phạm luật quản lý thuế"),
          Clause("Điều 7", CLEAN, "biên bản nghiệm thu — tiêu chuẩn")]),
    Case("trongtai_sach", "to_tung", "HỢP ĐỒNG THƯƠNG MẠI\n"
         "Điều 11. Giải quyết tranh chấp: tranh chấp giải quyết tại Trung tâm Trọng tài Quốc tế Việt Nam "
         "(VIAC) theo Quy tắc tố tụng của VIAC.\n"
         "Điều 13. Hiệu lực: hợp đồng có hiệu lực kể từ ngày hai bên ký.\n",
         [Clause("Điều 11", CLEAN, "trọng tài VIAC theo quy tắc — tiêu chuẩn, hợp lệ"),
          Clause("Điều 13", CLEAN, "điều khoản hiệu lực — vô hại")]),
    Case("dat_thue", "dat_dai", "HỢP ĐỒNG THUÊ ĐẤT\n"
         "Điều 4. Tăng giá: Bên A được đơn phương tăng giá thuê tùy ý mỗi năm, Bên B không có quyền phản đối.\n"
         "Điều 8. Diện tích: thửa đất 500m2 theo giấy chứng nhận quyền sử dụng đất.\n",
         [Clause("Điều 4", UNFAV, "đơn phương tăng giá tùy ý — bất lợi Bên B"),
          Clause("Điều 8", CLEAN, "mô tả diện tích đất — vô hại")]),
]


def _post_analyze(text: str, protected: str, mode: str) -> tuple[dict, float]:
    parts = []
    for k, v in (("text", text), ("lang", "vi"), ("protected_party", protected), ("mode", mode)):
        parts.append(f'--B\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n')
    body = ("".join(parts) + "--B--\r\n").encode("utf-8")
    req = urllib.request.Request(f"{BASE}/analyze", data=body, method="POST", headers={
        "X-API-Key": KEY, "Content-Type": "multipart/form-data; boundary=B"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8")), time.time() - t0


def _delete_case(cid: str) -> bool:
    req = urllib.request.Request(f"{BASE}/cases/{cid}", method="DELETE", headers={"X-API-Key": KEY})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except urllib.error.URLError:
        return False


def _find(risks: list, anchor: str):
    for r in risks:
        if anchor in f"{r.get('clause', '')} {r.get('evidence', '')}":
            return r
    return None


def _wilson(k: int, n: int) -> tuple[float, float]:
    """Wilson 95% CI cho tỉ lệ k/n (chuẩn cho proportion, không vỡ ở biên 0%/100%)."""
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round(100 * (c - h) / d, 1), round(100 * (c + h) / d, 1))


@dataclass
class Stat:
    lat: list[float] = field(default_factory=list)
    tp: int = 0            # rủi-ro (illegal|unfavorable) được flag
    fn: int = 0            # rủi-ro bị bỏ sót (laziness)
    fp: int = 0            # điều-khoản CLEAN bị flag (false alarm)
    tn: int = 0            # clean không bị flag
    illegal_hit: int = 0
    illegal_total: int = 0
    miss_illegal: int = 0
    nonillegal_total: int = 0   # unfavorable + clean
    overflag: int = 0           # non-illegal bị gắn illegal
    warned: int = 0
    hr: int = 0
    counter_inline: int = 0
    runs: int = 0
    errors: int = 0
    per_domain: dict = field(default_factory=dict)   # domain -> [tp, fn, fp, tn]


def _score(st: Stat, case: Case, res: dict) -> None:
    st.runs += 1
    risks = res.get("risks", [])
    if any(n.startswith("⚡") for n in res.get("notes", [])):
        st.warned += 1
    if res.get("needs_human_review"):
        st.hr += 1
    st.counter_inline += sum(1 for r in risks if r.get("counter_clause"))
    dd = st.per_domain.setdefault(case.domain, [0, 0, 0, 0])
    for cl in case.clauses:
        r = _find(risks, cl.anchor)
        flagged = r is not None
        got = r.get("legal_status") if r else None
        if cl.label == CLEAN:
            if flagged:
                st.fp += 1
                dd[2] += 1
            else:
                st.tn += 1
                dd[3] += 1
            if got == ILLEGAL:
                st.overflag += 1
            st.nonillegal_total += 1
        else:                       # illegal | unfavorable = rủi ro THẬT
            if flagged:
                st.tp += 1
                dd[0] += 1
            else:
                st.fn += 1
                dd[1] += 1
            if cl.label == ILLEGAL:
                st.illegal_total += 1
                if got == ILLEGAL:
                    st.illegal_hit += 1
                else:
                    st.miss_illegal += 1
            else:                   # unfavorable
                st.nonillegal_total += 1
                if got == ILLEGAL:
                    st.overflag += 1


def _pctile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))], 1)


def _prf(st: Stat) -> dict:
    prec = st.tp / (st.tp + st.fp) if (st.tp + st.fp) else 0.0
    rec = st.tp / (st.tp + st.fn) if (st.tp + st.fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    f2 = 5 * prec * rec / (4 * prec + rec) if (4 * prec + rec) else 0.0   # ưu tiên recall
    return {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3), "f2": round(f2, 3),
            "recall_ci95": _wilson(st.tp, st.tp + st.fn), "tp": st.tp, "fp": st.fp, "fn": st.fn, "tn": st.tn}


def _summary(st: Stat) -> dict:
    lat = st.lat
    ci = (0.0, 0.0)
    if len(lat) > 1:
        m, sd = statistics.mean(lat), statistics.stdev(lat)
        h = 1.96 * sd / math.sqrt(len(lat))
        ci = (round(m - h, 1), round(m + h, 1))
    out = {"runs": st.runs, "errors": st.errors,
           "latency_s": {"median": _pctile(lat, 50), "p95": _pctile(lat, 95), "p99": _pctile(lat, 99),
                         "min": _pctile(lat, 0), "max": _pctile(lat, 100),
                         "mean": round(statistics.mean(lat), 1) if lat else 0.0, "mean_ci95": ci},
           "detection": _prf(st),
           "illegal_recall_pct": round(100 * st.illegal_hit / st.illegal_total, 1) if st.illegal_total else 0.0,
           "illegal_recall_ci95": _wilson(st.illegal_hit, st.illegal_total),
           "miss_illegal": st.miss_illegal, "n_illegal": st.illegal_total,
           "overflag": st.overflag, "overflag_pct": round(100 * st.overflag / st.nonillegal_total, 1) if st.nonillegal_total else 0.0,
           "n_nonillegal": st.nonillegal_total,
           "false_alarm_pct_on_clean": round(100 * st.fp / (st.fp + st.tn), 1) if (st.fp + st.tn) else 0.0,
           "warned_pct": round(100 * st.warned / st.runs, 1) if st.runs else 0.0,
           "human_review_pct": round(100 * st.hr / st.runs, 1) if st.runs else 0.0,
           "counter_inline_total": st.counter_inline,
           "per_domain_detect": {d: {"tp": v[0], "fn": v[1], "fp": v[2], "tn": v[3]} for d, v in st.per_domain.items()}}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--deep", type=int, default=0)
    ap.add_argument("--out", default="scripts/fast_bench_report.json")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    if not KEY:
        raise SystemExit("Thiếu API_KEYS/API_KEY.")

    n_ill = sum(1 for c in CASES for cl in c.clauses if cl.label == ILLEGAL)
    n_unf = sum(1 for c in CASES for cl in c.clauses if cl.label == UNFAV)
    n_cln = sum(1 for c in CASES for cl in c.clauses if cl.label == CLEAN)
    print(f"== FAST-PATH BENCH @ {BASE} · {len(CASES)} HĐ × {args.reps} lần "
          f"({n_ill} illegal + {n_unf} unfavorable + {n_cln} clean/âm) ==\n")
    created: list[str] = []
    fast, deep = Stat(), Stat()

    for rep in range(args.reps):
        for c in CASES:
            try:
                res, dt = _post_analyze(c.text, c.protected, "fast")
                if "risks" not in res:
                    fast.errors += 1
                    print(f"  [fast] {c.name}: {res.get('detail')}")
                    continue
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                fast.errors += 1
                print(f"  [fast] {c.name}: LỖI {e}")
                continue
            fast.lat.append(dt)
            _score(fast, c, res)
            if res.get("case_id"):
                created.append(res["case_id"])
            ill = sum(1 for x in res["risks"] if x.get("legal_status") == ILLEGAL)
            print(f"  [fast r{rep+1}] {c.name:<14} {dt:5.1f}s · {len(res['risks'])} risk · {ill} illegal")

    for c in CASES[:args.deep]:
        try:
            res, dt = _post_analyze(c.text, c.protected, "deep")
            if "risks" in res:
                deep.lat.append(dt)
                _score(deep, c, res)
                if res.get("case_id"):
                    created.append(res["case_id"])
                print(f"  [DEEP] {c.name:<14} {dt:5.1f}s")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"  [DEEP] {c.name}: LỖI {e}")

    report = {"base": BASE, "cases": len(CASES), "reps": args.reps,
              "labels": {"illegal": n_ill, "unfavorable": n_unf, "clean": n_cln},
              "label_note": "nhãn tác giả gán (neo luật VN), CHƯA luật-sư-verify — smoke/regression",
              "fast": _summary(fast)}
    if deep.lat:
        report["deep"] = _summary(deep)

    f = report["fast"]
    det = f["detection"]
    print(f"\n=== FAST ({f['runs']} run) — chuẩn ContractEval/CUAD ===")
    print(f"  Latency: median {f['latency_s']['median']}s · p95 {f['latency_s']['p95']}s · "
          f"p99 {f['latency_s']['p99']}s · mean {f['latency_s']['mean']}s CI{f['latency_s']['mean_ci95']}")
    print(f"  PHÁT HIỆN rủi ro: Precision {det['precision']} · Recall {det['recall']} "
          f"(CI95 {det['recall_ci95']}%) · F1 {det['f1']} · F2 {det['f2']}  [TP{det['tp']} FP{det['fp']} FN{det['fn']} TN{det['tn']}]")
    print(f"  TRÁI LUẬT: recall {f['illegal_recall_pct']}% (CI95 {f['illegal_recall_ci95']}%, n={f['n_illegal']}) · "
          f"BỎ SÓT {f['miss_illegal']} · over-flag {f['overflag_pct']}% (n={f['n_nonillegal']})")
    print(f"  FALSE-ALARM trên ca CLEAN: {f['false_alarm_pct_on_clean']}%  |  ⚡{f['warned_pct']}% · "
          f"human-review {f['human_review_pct']}% · counter_inline(→0) {f['counter_inline_total']}")
    if deep.lat:
        dl = report["deep"]["latency_s"]["median"]
        print(f"  DEEP median {dl}s → fast nhanh ~{round(dl / max(f['latency_s']['median'], 0.1))}×")

    if not args.keep and created:
        ok = sum(1 for cid in created if _delete_case(cid))
        print(f"\n  Dọn: xoá {ok}/{len(created)} case test")
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
