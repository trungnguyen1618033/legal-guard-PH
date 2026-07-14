"""BENCHMARK FAST-PATH TRÊN PROD THẬT — chứng minh latency + độ chính xác bằng SỐ (không nói suông).

Gọi endpoint /analyze (mode=fast) trên deploy THẬT với bộ HĐ CÓ NHÃN (đa lĩnh vực, neo luật VN):
illegal = phạt >8% (LTM Đ.301) · lãi >20%/năm (BLDS Đ.468); unfavorable-hợp-pháp = 120 ngày · đơn phương ·
luật nước ngoài · NDA dài · giao SHTT rộng. Mỗi ca đo:
  - latency end-to-end (phân phối: min/median/p95/max)
  - illegal_recall (bắt trúng trái luật), miss_illegal (bỏ sót — NGUY HIỂM), over-flag (báo dư)
  - detect_recall (bắt được điều khoản), ⚡ warning + needs_human_review + counter_inline (fast phải = 0)
TỰ DỌN: xoá mọi case tạo ra (DELETE /cases/{id}). Có --deep để so latency deep trên vài ca.

Chạy: API_BASE=https://legalguard.duckdns.org API_KEYS=<key> uv run python -m scripts.fast_bench_live
      [--reps N] [--deep K] [--out scripts/fast_bench_report.json] [--keep]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000").rstrip("/")
KEY = os.environ.get("API_KEY") or (
    os.environ.get("API_KEYS", "").strip('"').split(",")[0].split(":")[0] if os.environ.get("API_KEYS") else "")


@dataclass
class Clause:
    anchor: str          # neo nhận diện trong risk.clause/evidence
    label: str           # "illegal" | "unfavorable"
    why: str


@dataclass
class Case:
    name: str
    text: str
    clauses: list[Clause]
    protected: str = "Bên B (SME Việt Nam)"


# Bộ HĐ có NHÃN — mỗi HĐ 2-3 điều khoản, trộn illegal + unfavorable, đa lĩnh vực.
CASES: list[Case] = [
    Case("thuong_mai_phat", "HỢP ĐỒNG CUNG CẤP HÀNG HÓA (thương mại)\n"
         "Điều 5. Phạt vi phạm: Bên B chịu phạt 30% giá trị hợp đồng nếu chậm giao quá 3 ngày.\n"
         "Điều 8. Thanh toán: Bên A thanh toán trong vòng 120 ngày kể từ ngày nhận hàng.\n",
         [Clause("Điều 5", "illegal", "phạt 30% > trần 8% LTM Đ.301"),
          Clause("Điều 8", "unfavorable", "120 ngày bất lợi dòng tiền, hợp pháp")]),
    Case("vay_lai", "HỢP ĐỒNG VAY\nĐiều 3. Lãi suất: 60%/năm; lãi quá hạn bằng 200% lãi trong hạn.\n"
         "Điều 6. Phạt trả chậm: 25% số tiền vay mỗi kỳ chậm.\n",
         [Clause("Điều 3", "illegal", "lãi 60%/năm > trần 20%/năm BLDS Đ.468")]),
    Case("dich_vu_chamdut", "HỢP ĐỒNG DỊCH VỤ\n"
         "Điều 10. Chấm dứt: Bên A đơn phương chấm dứt bất cứ lúc nào không cần lý do, không bồi thường; "
         "Bên B không có quyền tương ứng.\n"
         "Điều 12. Luật áp dụng: luật Anh, tranh chấp tại tòa London.\n",
         [Clause("Điều 10", "unfavorable", "đơn phương lệch — bất lợi, không đương nhiên trái luật"),
          Clause("Điều 12", "unfavorable", "luật nước ngoài + tài phán London bất lợi SME VN")]),
    Case("thuong_mai_phat2", "HỢP ĐỒNG THI CÔNG XÂY DỰNG\n"
         "Điều 7. Phạt chậm tiến độ: 15% giá trị hợp đồng cho mỗi tuần chậm.\n"
         "Điều 9. Bảo hành: Bên B bảo hành 24 tháng.\n",
         [Clause("Điều 7", "illegal", "phạt 15% > trần 8% LTM/hoặc 12% XD — vượt trần"),
          Clause("Điều 9", "unfavorable", "bảo hành 24 tháng — điều kiện, không trái luật")]),
    Case("nda_shtt", "HỢP ĐỒNG HỢP TÁC\n"
         "Điều 4. Bảo mật: Bên B không tiết lộ thông tin trong 10 năm sau chấm dứt.\n"
         "Điều 5. Sở hữu trí tuệ: Mọi sáng tạo của Bên B trong VÀ ngoài phạm vi hợp đồng đều thuộc Bên A.\n",
         [Clause("Điều 4", "unfavorable", "NDA 10 năm khắt khe nhưng hợp pháp"),
          Clause("Điều 5", "unfavorable", "giao SHTT quá rộng — bất lợi")]),
    Case("mua_ban_phat", "HỢP ĐỒNG MUA BÁN\n"
         "Điều 6. Phạt vi phạm hợp đồng: 50% giá trị đơn hàng nếu hủy.\n"
         "Điều 8. Giao hàng: Bên B chịu mọi rủi ro tới khi Bên A xác nhận nhận đủ.\n",
         [Clause("Điều 6", "illegal", "phạt 50% > trần 8% LTM Đ.301"),
          Clause("Điều 8", "unfavorable", "chuyển rủi ro bất lợi cho bên bán")]),
    Case("lao_dong", "HỢP ĐỒNG LAO ĐỘNG\n"
         "Điều 3. Thử việc: 6 tháng với lương 70% chính thức.\n"
         "Điều 7. Bồi thường: người lao động bồi thường 3 tháng lương nếu nghỉ trước hạn không báo trước.\n",
         [Clause("Điều 3", "unfavorable", "thử việc dài/lương thấp — cần đối chiếu BLLĐ")]),
    Case("thanh_toan_datcoc", "HỢP ĐỒNG THUÊ\n"
         "Điều 4. Đặt cọc: Bên B đặt cọc 6 tháng tiền thuê, không hoàn lại trong mọi trường hợp.\n"
         "Điều 9. Thanh toán: trả trước 180 ngày một lần.\n",
         [Clause("Điều 4", "unfavorable", "cọc không hoàn 'mọi trường hợp' bất lợi"),
          Clause("Điều 9", "unfavorable", "trả trước 180 ngày bất lợi dòng tiền")]),
]


def _post_analyze(text: str, protected: str, mode: str) -> tuple[dict, float]:
    data = []
    for k, v in (("text", text), ("lang", "vi"), ("protected_party", protected), ("mode", mode)):
        data.append(f'--B\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n')
    body = ("".join(data) + "--B--\r\n").encode("utf-8")
    req = urllib.request.Request(f"{BASE}/analyze", data=body, method="POST", headers={
        "X-API-Key": KEY, "Content-Type": "multipart/form-data; boundary=B"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as r:
        dt = time.time() - t0
        return json.loads(r.read().decode("utf-8")), dt


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


@dataclass
class Stat:
    lat: list[float] = field(default_factory=list)
    illegal_hit: int = 0
    illegal_total: int = 0
    miss_illegal: int = 0
    unfav_total: int = 0
    overflag: int = 0
    detect_hit: int = 0
    detect_total: int = 0
    warned: int = 0
    hr: int = 0
    counter_inline: int = 0
    runs: int = 0
    errors: int = 0


def _score(st: Stat, case: Case, res: dict) -> None:
    st.runs += 1
    risks = res.get("risks", [])
    if any(n.startswith("⚡") for n in res.get("notes", [])):
        st.warned += 1
    if res.get("needs_human_review"):
        st.hr += 1
    st.counter_inline += sum(1 for r in risks if r.get("counter_clause"))
    for cl in case.clauses:
        st.detect_total += 1
        r = _find(risks, cl.anchor)
        if r is not None:
            st.detect_hit += 1
        got = r.get("legal_status") if r else None
        if cl.label == "illegal":
            st.illegal_total += 1
            if got == "illegal":
                st.illegal_hit += 1
            else:
                st.miss_illegal += 1
        else:
            st.unfav_total += 1
            if got == "illegal":
                st.overflag += 1


def _pct(a: int, b: int) -> float:
    return round(100 * a / b, 1) if b else 0.0


def _pctile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = min(len(s) - 1, int(round((p / 100) * (len(s) - 1))))
    return round(s[k], 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=1, help="số lần chạy mỗi HĐ (khử nhiễu)")
    ap.add_argument("--deep", type=int, default=0, help="chạy DEEP trên N HĐ đầu để so latency")
    ap.add_argument("--out", default="scripts/fast_bench_report.json")
    ap.add_argument("--keep", action="store_true", help="KHÔNG xoá case (mặc định tự dọn)")
    args = ap.parse_args()
    if not KEY:
        raise SystemExit("Thiếu API_KEYS/API_KEY.")

    print(f"== FAST-PATH BENCH @ {BASE} · {len(CASES)} HĐ × {args.reps} lần ==\n")
    created: list[str] = []
    fast, deep = Stat(), Stat()

    for rep in range(args.reps):
        for c in CASES:
            try:
                res, dt = _post_analyze(c.text, c.protected, "fast")
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                fast.errors += 1
                print(f"  [fast] {c.name}: LỖI {e}")
                continue
            if "risks" not in res:
                fast.errors += 1
                print(f"  [fast] {c.name}: {res.get('detail')}")
                continue
            fast.lat.append(dt)
            _score(fast, c, res)
            if res.get("case_id"):
                created.append(res["case_id"])
            n_ill = sum(1 for x in res["risks"] if x.get("legal_status") == "illegal")
            print(f"  [fast r{rep+1}] {c.name:<20} {dt:5.1f}s · {len(res['risks'])} risk · {n_ill} illegal")

    for c in CASES[:args.deep]:
        try:
            res, dt = _post_analyze(c.text, c.protected, "deep")
            if "risks" in res:
                deep.lat.append(dt)
                _score(deep, c, res)
                if res.get("case_id"):
                    created.append(res["case_id"])
                print(f"  [DEEP] {c.name:<20} {dt:5.1f}s")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"  [DEEP] {c.name}: LỖI {e}")

    def summary(st: Stat) -> dict:
        return {
            "runs": st.runs, "errors": st.errors,
            "latency_s": {"min": _pctile(st.lat, 0), "median": _pctile(st.lat, 50),
                          "p95": _pctile(st.lat, 95), "max": _pctile(st.lat, 100),
                          "avg": round(statistics.mean(st.lat), 1) if st.lat else 0.0},
            "illegal_recall_pct": _pct(st.illegal_hit, st.illegal_total),
            "miss_illegal": st.miss_illegal, "miss_illegal_pct": _pct(st.miss_illegal, st.illegal_total),
            "overflag": st.overflag, "overflag_pct": _pct(st.overflag, st.unfav_total),
            "detect_recall_pct": _pct(st.detect_hit, st.detect_total),
            "n_illegal": st.illegal_total, "n_unfav": st.unfav_total,
            "warned_pct": _pct(st.warned, st.runs), "needs_human_review_pct": _pct(st.hr, st.runs),
            "counter_inline_total": st.counter_inline,
        }

    report = {"base": BASE, "cases": len(CASES), "reps": args.reps, "fast": summary(fast)}
    if deep.lat:
        report["deep"] = summary(deep)

    f = report["fast"]
    print(f"\n=== FAST ({f['runs']} run, {f['n_illegal']} illegal + {f['n_unfav']} unfavorable) ===")
    print(f"  Latency: median {f['latency_s']['median']}s · p95 {f['latency_s']['p95']}s · "
          f"min {f['latency_s']['min']}s · max {f['latency_s']['max']}s")
    print(f"  Illegal recall: {f['illegal_recall_pct']}%  |  BỎ SÓT illegal: {f['miss_illegal']} "
          f"({f['miss_illegal_pct']}%)  |  báo dư: {f['overflag']} ({f['overflag_pct']}%)")
    print(f"  Detect: {f['detect_recall_pct']}%  |  ⚡ warning: {f['warned_pct']}%  |  "
          f"human-review: {f['needs_human_review_pct']}%  |  counter_inline (phải 0): {f['counter_inline_total']}")
    if deep.lat:
        print(f"  DEEP latency median: {report['deep']['latency_s']['median']}s "
              f"(fast nhanh ~{round(report['deep']['latency_s']['median'] / max(f['latency_s']['median'], 0.1))}×)")

    if not args.keep and created:
        ok = sum(1 for cid in created if _delete_case(cid))
        print(f"\n  Dọn: xoá {ok}/{len(created)} case test")

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
