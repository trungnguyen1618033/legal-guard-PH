#!/usr/bin/env python3
"""Live FUNCTIONAL test — gọi deployment THẬT (LLM thật) + assert ĐÚNG NỘI DUNG (không chỉ HTTP 200).

Khác smoke_live.py (chỉ kiểm "còn sống"): file này kiểm "trả lời ĐÚNG" — dẫn đúng điều luật/số liệu,
phân loại illegal đúng, biết TỪ CHỐI khi ngoài KB. Data-driven: thêm 1 dòng vào CASES = thêm 1 test.

    python3 scripts/live_cases.py                 # lookup (nhanh) — mặc định
    python3 scripts/live_cases.py --kind all       # + analyze (chậm ~90s/ca)
    python3 scripts/live_cases.py --kind analyze
    python3 scripts/live_cases.py --limit 5        # chỉ N ca đầu mỗi loại

Assert keyword tất định (chịu được LLM đổi câu chữ):
    any  = ÍT NHẤT MỘT chuỗi xuất hiện (OR)     all  = TẤT CẢ phải có (AND)
    none = KHÔNG chuỗi nào được xuất hiện
Đọc config từ env/.env: API_BASE, API_KEY/API_KEYS.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def load_cfg():
    env = {}
    for p in (Path(".env"), Path(__file__).resolve().parent.parent / ".env"):
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip().strip('"'))
    import os
    env.update({k: v for k, v in os.environ.items() if k in ("API_BASE", "API_KEY", "API_KEYS")})
    base = env.get("API_BASE", "http://127.0.0.1:8000").rstrip("/")
    key = env.get("API_KEY") or (env.get("API_KEYS", "").split(",")[0].split(":")[0] if env.get("API_KEYS") else "")
    return base, key


BASE, KEY = load_cfg()


def post(path: str, body: dict, timeout: int):
    data = json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"x-api-key": KEY, "content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {"_err": e.read().decode("utf-8", "replace")[:120]}
    except Exception as e:  # noqa: BLE001 — timeout/URLError → FAIL chứ KHÔNG crash cả suite
        return 0, {"_err": "timeout/conn: " + str(e)[:80]}


def check(text: str, c: dict) -> tuple[bool, str]:
    low = (text or "").lower()
    miss = [s for s in c.get("all", []) if s.lower() not in low]
    if miss:
        return False, "thiếu tất-cả: " + ", ".join(miss)
    if c.get("any") and not any(s.lower() in low for s in c["any"]):
        return False, "thiếu any-of: " + " | ".join(c["any"])
    bad = [s for s in c.get("none", []) if s.lower() in low]
    if bad:
        return False, "có chuỗi cấm: " + ", ".join(bad)
    return True, "ok"


# ============================================================
# BẢNG CASE — thêm 1 dòng = 1 test. Phủ 12 lĩnh vực + ca biên.
# ============================================================
LOOKUP = [
    # --- chế tài / hợp đồng (Luật TM + BLDS) ---
    {"id": "phat-tm", "q": "Mức phạt vi phạm hợp đồng thương mại tối đa là bao nhiêu?", "any": ["8%"], "all": ["301"]},
    {"id": "boi-thuong", "q": "Bồi thường thiệt hại trong thương mại gồm những gì?", "any": ["302", "tổn thất", "thực tế"]},
    {"id": "lai-vay", "q": "Trần lãi suất cho vay theo Bộ luật Dân sự là bao nhiêu?", "any": ["20%", "468"]},
    {"id": "tra-no", "q": "Nghĩa vụ trả nợ của bên vay tiền quy định ở đâu?", "any": ["466"]},
    {"id": "dat-coc", "q": "Quy định về đặt cọc trong Bộ luật Dân sự?", "any": ["328", "đặt cọc"]},
    {"id": "lai-cham", "q": "Lãi do chậm thực hiện nghĩa vụ trả tiền tính thế nào?", "any": ["357", "chậm"]},
    # --- hóa đơn ---
    {"id": "hoa-don-thoi-diem", "q": "Thời điểm lập hóa đơn khi bán hàng hóa là khi nào?",
     "any": ["chuyển giao", "Điều 9", "quyền sở hữu"], "none": ["39/2014"]},
    # --- trọng tài ---
    {"id": "trong-tai", "q": "Điều kiện để thỏa thuận trọng tài thương mại có hiệu lực?",
     "any": ["trọng tài", "thỏa thuận"]},
    # --- lao động ---
    {"id": "lao-dong", "q": "Người lao động làm thêm giờ tối đa bao nhiêu giờ?",
     "any": ["làm thêm", "giờ", "200", "300"]},
    # --- doanh nghiệp ---
    {"id": "doanh-nghiep", "q": "Các loại hình doanh nghiệp theo Luật Doanh nghiệp 2020?",
     "any": ["trách nhiệm hữu hạn", "cổ phần", "hợp danh"]},
    # --- SHTT ---
    {"id": "shtt", "q": "Quyền tác giả được bảo hộ trong bao lâu?", "any": ["tác giả", "bảo hộ", "năm"]},
    # --- PDPD ---
    {"id": "pdpd", "q": "Dữ liệu cá nhân nhạy cảm gồm những gì theo Nghị định 13/2023?",
     "any": ["dữ liệu cá nhân", "nhạy cảm", "13/2023"]},
    # --- hôn nhân gia đình / đất đai / đầu tư ---
    {"id": "dat-dai", "q": "Thời hạn sử dụng đất nông nghiệp là bao lâu?", "any": ["đất", "năm", "50"]},
    {"id": "dau-tu", "q": "Ưu đãi đầu tư theo Luật Đầu tư gồm những hình thức nào?", "any": ["ưu đãi", "đầu tư"]},
    # --- thêm: phrasing khác + lĩnh vực phủ thêm ---
    {"id": "phat-va-boithuong", "q": "Có được vừa phạt vi phạm vừa yêu cầu bồi thường thiệt hại không?",
     "any": ["307", "vừa", "đồng thời", "cả phạt"]},
    {"id": "lai-qua-han", "q": "Lãi suất nợ quá hạn được tính thế nào?", "any": ["quá hạn", "468", "357", "150%"]},
    {"id": "hn-gd-taisan", "q": "Tài sản chung của vợ chồng gồm những gì?",
     "any": ["tài sản chung", "vợ chồng", "hôn nhân"]},
    {"id": "trong-tai-vien", "q": "Trọng tài viên phải đáp ứng tiêu chuẩn gì?",
     "any": ["trọng tài viên", "tiêu chuẩn", "điều kiện"]},
    {"id": "dn-von", "q": "Vốn điều lệ công ty cổ phần được quy định thế nào?",
     "any": ["vốn điều lệ", "cổ phần", "cổ phiếu"]},
    {"id": "shtt-cn", "q": "Quyền sở hữu công nghiệp gồm những đối tượng nào?",
     "any": ["sở hữu công nghiệp", "nhãn hiệu", "sáng chế", "kiểu dáng"]},
    # --- point-in-time có mốc HỢP LỆ (2023 → NĐ 123/2020 đã hiệu lực 2022, KHÔNG phải TT39) ---
    {"id": "pit-2023", "q": "Tính đến năm 2023, văn bản nào quy định về hóa đơn điện tử?",
     "any": ["123/2020", "hóa đơn"], "none": ["39/2014"]},
    # --- thêm phrasing/độ phủ (đảm bảo) ---
    {"id": "mien-trach", "q": "Khi nào bên vi phạm được miễn trách nhiệm theo Luật Thương mại?",
     "any": ["miễn", "bất khả kháng", "294"]},
    {"id": "phat-thoa-thuan", "q": "Phạt vi phạm có bắt buộc phải thỏa thuận trước trong hợp đồng không?",
     "any": ["thỏa thuận", "301", "phải"]},
    {"id": "vay-khong-lai", "q": "Bên vay tiền không có lãi thì có nghĩa vụ gì khi đến hạn?",
     "any": ["466", "trả", "đúng hạn"]},
    {"id": "hoa-don-dichvu", "q": "Khi cung cấp dịch vụ thì lập hóa đơn vào thời điểm nào?",
     "any": ["hoàn thành", "dịch vụ", "Điều 9", "thu tiền"]},
    {"id": "nd70-sua", "q": "Nghị định 70/2025 liên quan gì đến hóa đơn?",
     "any": ["70/2025", "123/2020", "hóa đơn", "sửa"]},
    {"id": "lam-them-nam", "q": "Tổng số giờ làm thêm tối đa trong một năm là bao nhiêu?",
     "any": ["200", "300", "năm", "giờ"]},
    {"id": "tnhh-1tv", "q": "Công ty trách nhiệm hữu hạn một thành viên do ai làm chủ sở hữu?",
     "any": ["một thành viên", "tổ chức", "cá nhân", "chủ sở hữu"]},
    {"id": "ket-hon", "q": "Điều kiện kết hôn theo Luật Hôn nhân và Gia đình?",
     "any": ["kết hôn", "tự nguyện", "tuổi", "nam", "nữ"]},
    {"id": "dau-tu-cam", "q": "Ngành nghề bị cấm đầu tư kinh doanh gồm những gì?",
     "any": ["cấm", "đầu tư", "kinh doanh", "ma túy"]},
    {"id": "pit-2025", "q": "Tính đến năm 2025, văn bản hiện hành quy định về hóa đơn?",
     "any": ["70/2025", "123/2020", "hóa đơn"], "none": ["39/2014"]},
    # --- NEGATIVE: chủ đề CHẮC CHẮN ngoài KB → phải TỪ CHỐI (không bịa). Giá trị cao nhất cho lòng tin. ---
    {"id": "edge-out-of-kb", "q": "Quy định đăng kiểm ô tô chở khách như thế nào?",
     "any": ["chưa đủ", "không đủ", "không tìm", "ngoài phạm vi", "không có"]},
    {"id": "edge-out-of-kb-2", "q": "Mức xử phạt vi phạm giao thông khi vượt đèn đỏ?",
     "any": ["chưa đủ", "không đủ", "không tìm", "ngoài phạm vi", "không có"]},
    {"id": "edge-tndn", "q": "Thuế suất thuế thu nhập doanh nghiệp hiện nay là bao nhiêu?",
     "any": ["chưa đủ", "không đủ", "không tìm", "ngoài phạm vi", "không có"]},
    {"id": "edge-gtgt", "q": "Các mức thuế suất thuế giá trị gia tăng?",
     "any": ["chưa đủ", "không đủ", "không tìm", "ngoài phạm vi", "không có"]},
    {"id": "edge-chungkhoan", "q": "Điều kiện để doanh nghiệp IPO theo Luật Chứng khoán?",
     "any": ["chưa đủ", "không đủ", "không tìm", "ngoài phạm vi", "không có"]},
    # (gỡ edge-visa: giấy phép lao động được KB lao động phủ → KHÔNG phải ca abstain sạch)
    # --- ca biên: luật CHẾT (không mốc thời gian) → phải trả VB còn hiệu lực, không dẫn TT 39/2014 ---
    {"id": "edge-in-force", "q": "Văn bản nào quy định về hóa đơn điện tử hiện hành?",
     "none": ["39/2014"], "any": ["123/2020", "70/2025", "hóa đơn"]},
]

# Analyze: text HĐ → assert risk/illegal. Chậm (~90s/ca) → chỉ chạy với --kind all/analyze.
ANALYZE = [
    {"id": "an-phat15-tm", "text": "Bên B chịu phạt 15% giá trị hợp đồng nếu giao hàng chậm. Bên A không chịu phạt.",
     "min_risks": 1, "answer_any": ["301", "8%"], "expect_illegal": True},
    {"id": "an-trongtai-ngoai", "text": "Mọi tranh chấp giải quyết tại tòa án Singapore theo luật Đức.",
     "min_risks": 1, "answer_any": ["trọng tài", "singapore", "tòa", "thi hành"]},
    {"id": "an-datcoc-50", "text": "Bên B đặt cọc trước 50% giá trị hợp đồng ngay khi ký.",
     "min_risks": 1, "answer_any": ["đặt cọc", "cọc", "rủi ro"]},
    {"id": "an-vay-laicao", "text": "Hợp đồng vay: lãi suất 30%/năm; phạt chậm trả 50% số tiền vay.",
     "min_risks": 1, "answer_any": ["466", "468", "20%", "lãi"], "expect_illegal": True},
    {"id": "an-baomat-rong", "text": "Bên B không được tiết lộ bất kỳ thông tin nào về Bên A, vĩnh viễn, kể cả sau khi chấm dứt.",
     "min_risks": 1, "answer_any": ["bảo mật", "thông tin", "vĩnh viễn", "phạm vi"]},
]

# Counter-clause + Negotiate (LLM, ~30s/ca) — chạy với --kind counter|negotiate|all.
COUNTER = [
    {"id": "ct-phat", "clause": "Phạt 15% giá trị hợp đồng", "risk": "vượt trần 8%",
     "suggestion": "giảm về 8%, áp dụng hai chiều", "legal_basis": "Điều 301 Luật Thương mại 2005",
     "leverage": "strong", "any": ["8%", "301", "phạt", "penalty"]},
]
NEGOTIATE = [
    {"id": "ng-counter", "deal_context": "Phạt 15% trái Điều 301; cần giảm về 8%.",
     "partner_message": "Chúng tôi chỉ giảm xuống 12%, không thấp hơn.", "leverage": "strong"},
]


def run_lookup(limit, recs):
    print("\n— LOOKUP (gọi /ask thật) —")
    for c in LOOKUP[:limit]:
        s, d = post("/ask", {"question": c["q"], "lang": "vi"}, 120)   # 120s: ca point-in-time route flagship (chậm)
        if s != 200:
            recs.append((False, "lookup:" + c["id"], f"HTTP {s} {d.get('_err','')}"))
            continue
        ok, why = check(d.get("answer", ""), c)
        recs.append((ok, "lookup:" + c["id"], why if ok else why + " | got: " + d.get("answer", "")[:80]))
        _p(ok, "lookup:" + c["id"], (d.get("answer", "")[:60] if ok else why))


def run_analyze(limit, recs):
    print("\n— ANALYZE (gọi /analyze thật, chậm) —")
    for c in ANALYZE[:limit]:
        body, ctype = _mp({"text": c["text"], "lang": "vi"})
        req = urllib.request.Request(BASE + "/analyze", data=body,
                                     headers={"x-api-key": KEY, "content-type": ctype}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=200) as r:
                d = json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            recs.append((False, "analyze:" + c["id"], str(e)[:80]))
            _p(False, "analyze:" + c["id"], str(e)[:60])
            continue
        risks = d.get("risks", [])
        blob = json.dumps(d, ensure_ascii=False).lower()
        problems = []
        if len(risks) < c.get("min_risks", 1):
            problems.append(f"risks={len(risks)}<{c['min_risks']}")
        if c.get("answer_any") and not any(s.lower() in blob for s in c["answer_any"]):
            problems.append("thiếu any: " + "|".join(c["answer_any"]))
        if c.get("expect_illegal") and not any(r.get("legal_status") == "illegal" for r in risks):
            problems.append("không có risk illegal")
        ok = not problems
        recs.append((ok, "analyze:" + c["id"], "ok" if ok else "; ".join(problems)))
        _p(ok, "analyze:" + c["id"], f"risks={len(risks)}" if ok else "; ".join(problems))


def run_counter(limit, recs):
    print("\n— COUNTER (gọi /counter thật) —")
    for c in COUNTER[:limit]:
        s, d = post("/counter", {"clause": c["clause"], "risk": c["risk"], "suggestion": c["suggestion"],
                                 "legal_basis": c["legal_basis"], "leverage": c["leverage"]}, 90)
        blob = json.dumps(d, ensure_ascii=False).lower()
        ok = s == 200 and bool(d.get("vi")) and any(x.lower() in blob for x in c["any"])
        recs.append((ok, "counter:" + c["id"], "ok" if ok else f"HTTP {s} grounded={d.get('grounded')}"))
        _p(ok, "counter:" + c["id"], (d.get("vi", "")[:60] if ok else f"HTTP {s}"))


def run_negotiate(limit, recs):
    print("\n— NEGOTIATE (gọi /negotiate thật) —")
    for c in NEGOTIATE[:limit]:
        s, d = post("/negotiate", {"deal_context": c["deal_context"], "partner_message": c["partner_message"],
                                   "lang": "vi", "leverage": c["leverage"]}, 90)
        ok = s == 200 and d.get("status") in ("continue", "close", "walk_away") and bool(d.get("assessment"))
        recs.append((ok, "negotiate:" + c["id"], f"status={d.get('status')}" if ok else f"HTTP {s}"))
        _p(ok, "negotiate:" + c["id"], f"status={d.get('status')}" if ok else f"HTTP {s}")


def _mp(fields):
    b = "----lc"
    parts = "".join(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n" for k, v in fields.items())
    return (parts + f"--{b}--\r\n").encode(), f"multipart/form-data; boundary={b}"


def _p(ok, name, detail):
    print(f"  {'✅ PASS' if ok else '❌ FAIL'}  {name}" + (f" — {detail}" if detail else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["lookup", "analyze", "counter", "negotiate", "all"], default="lookup")
    ap.add_argument("--limit", type=int, default=999)
    args = ap.parse_args()
    print(f"== Live functional cases @ {BASE} (key={'set' if KEY else 'none'}) ==")
    recs: list[tuple] = []
    if args.kind in ("lookup", "all"):
        run_lookup(args.limit, recs)
    if args.kind in ("analyze", "all"):
        run_analyze(args.limit, recs)
    if args.kind in ("counter", "all"):
        run_counter(args.limit, recs)
    if args.kind in ("negotiate", "all"):
        run_negotiate(args.limit, recs)
    npass = sum(1 for r in recs if r[0])
    fails = [r for r in recs if not r[0]]
    print(f"\n== TỔNG: {npass}/{len(recs)} pass ==")
    if fails:
        print("FAIL:")
        for _, name, why in fails:
            print(f"  - {name}: {why}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
