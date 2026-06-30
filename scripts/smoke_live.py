#!/usr/bin/env python3
"""Live smoke test — Legal Guard (API + Slack) trên một deployment đang chạy.

Gom các kịch bản đã verify thủ công thành 1 công cụ TÁI DÙNG, in PASS/FAIL + tóm tắt.
Chỉ dùng stdlib. Chạy TRÊN host ECS (có .env + localhost:8000 + token Slack).

    python3 scripts/smoke_live.py                 # tất cả (API + Slack), live
    python3 scripts/smoke_live.py --no-slack      # chỉ API
    python3 scripts/smoke_live.py --no-llm         # bỏ kịch bản LLM chậm
    python3 scripts/smoke_live.py --quick          # chỉ kịch bản nhanh tất định

Cấu hình (env hoặc đọc từ .env cùng thư mục gốc):
    API_BASE   (mặc định http://127.0.0.1:8000)
    API_KEYS / API_KEY   (key xác thực; lấy key đầu)
    SLACK_SIGNING_SECRET, SLACK_BOT_TOKEN, SLACK_TEST_CHANNEL
KHÔNG hardcode secret — đọc lúc chạy. An toàn để commit.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---------- cấu hình ----------
def load_env() -> dict:
    env = {}
    for p in (Path(".env"), Path(__file__).resolve().parent.parent / ".env"):
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip().strip('"'))
    import os
    env.update({k: v for k, v in os.environ.items() if k in (
        "API_BASE", "API_KEY", "API_KEYS", "SLACK_SIGNING_SECRET", "SLACK_BOT_TOKEN", "SLACK_TEST_CHANNEL")})
    return env


ENV = load_env()
BASE = ENV.get("API_BASE", "http://127.0.0.1:8000").rstrip("/")
KEY = ENV.get("API_KEY") or (ENV.get("API_KEYS", "").split(",")[0].split(":")[0] if ENV.get("API_KEYS") else "")
SIGNING = ENV.get("SLACK_SIGNING_SECRET", "")
BOT = ENV.get("SLACK_BOT_TOKEN", "")
CHANNEL = ENV.get("SLACK_TEST_CHANNEL", "")

# ---------- kết quả ----------
PASS, FAIL, SKIP = [], [], []


def record(group: str, name: str, ok: bool | None, detail: str = "") -> None:
    tag = {True: "✅ PASS", False: "❌ FAIL", None: "⏭️  SKIP"}[ok]
    print(f"  {tag}  [{group}] {name}" + (f" — {detail}" if detail else ""))
    (PASS if ok else SKIP if ok is None else FAIL).append(f"[{group}] {name}")


# ---------- helper HTTP ----------
def http(method: str, url: str, headers: dict, data: bytes | None = None, timeout: int = 30):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def api(method: str, path: str, body: dict | None = None, key: str | None = KEY, timeout: int = 30):
    headers = {"x-api-key": key} if key else {}
    data = None
    if body is not None:
        headers["content-type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode()
    url = BASE + urllib.parse.quote(path, safe="/?=&:%")   # encode ký tự non-ASCII (vd 'NĐ-CP') trong path
    status, raw = http(method, url, headers, data, timeout)
    try:
        return status, json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return status, raw.decode("utf-8", "replace")


# ---------- helper Slack ----------
def slack_api(method: str, body: dict):
    status, raw = http("POST", "https://slack.com/api/" + method,
                       {"Authorization": "Bearer " + BOT, "Content-Type": "application/json; charset=utf-8"},
                       json.dumps(body).encode(), 20)
    return json.loads(raw)


def slack_get(method: str, params: dict):
    url = "https://slack.com/api/" + method + "?" + urllib.parse.urlencode(params)
    status, raw = http("GET", url, {"Authorization": "Bearer " + BOT}, None, 20)
    return json.loads(raw)


def _sign(ts: str, body: str) -> str:
    return "v0=" + hmac.new(SIGNING.encode(), f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()


def slack_post_msg(text: str) -> str:
    return slack_api("chat.postMessage", {"channel": CHANNEL, "text": text}).get("ts", "")


def slack_event(text: str, ts: str, thread: str | None = None, bot_uid: str = "UTEST", bad_sig: bool = False):
    ev = {"type": "app_mention", "channel": CHANNEL, "user": "U_SMOKE", "text": f"<@{bot_uid}> {text}", "ts": ts}
    if thread:
        ev["thread_ts"] = thread
    body = json.dumps({"type": "event_callback", "authorizations": [{"user_id": bot_uid}], "event": ev},
                      ensure_ascii=False)
    sts = str(int(time.time()))
    sig = "v0=" + "0" * 64 if bad_sig else _sign(sts, body)
    status, raw = http("POST", BASE + "/channels/slack/events",
                       {"Content-Type": "application/json", "X-Slack-Request-Timestamp": sts, "X-Slack-Signature": sig},
                       body.encode(), 25)
    return status, raw


def slack_interact(payload: dict, bad_sig: bool = False):
    body = "payload=" + urllib.parse.quote(json.dumps(payload, ensure_ascii=False))
    sts = str(int(time.time()))
    sig = "v0=" + "0" * 64 if bad_sig else _sign(sts, body)
    return http("POST", BASE + "/channels/slack/interactions",
                {"Content-Type": "application/x-www-form-urlencoded",
                 "X-Slack-Request-Timestamp": sts, "X-Slack-Signature": sig}, body.encode(), 20)


def wait_bot_reply(thread_ts: str, bot_uid: str, timeout: int = 120) -> str:
    """Poll thread tới khi có reply BOT KHÔNG phải ack (hoặc hết giờ). Trả text reply cuối."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = slack_get("conversations.replies", {"channel": CHANNEL, "ts": thread_ts})
        for m in r.get("messages", [])[1:]:
            is_bot = m.get("user") == bot_uid or m.get("bot_id")
            txt = m.get("text", "")
            if is_bot and "Đang tra cứu" not in txt and "Đã nhận" not in txt:
                return txt
        time.sleep(5)
    return ""


# ============================================================
# KỊCH BẢN
# ============================================================
def run_api_fast():
    g = "API-fast"
    for name, path in [("health", "/health"), ("ready", "/ready"), ("trust.json", "/trust.json")]:
        s, _ = api("GET", path, key=None)
        record(g, name, s == 200, f"HTTP {s}")
    s, d = api("GET", "/runs")
    record(g, "runs (AI evidence)", s == 200 and "totals" in d, f"runs={d.get('totals',{}).get('runs')}")
    s, d = api("GET", "/insights/dashboard")
    record(g, "dashboard", s == 200 and "cases" in d)
    s, d = api("POST", "/redline", {"old": "phạt 8%", "new": "phạt 15% và bồi thường"})
    record(g, "redline", s == 200 and "redline" in d, f"sim={round(d.get('similarity',0),2)}")
    s, d = api("GET", "/graph/123/2020/NĐ-CP")
    record(g, "graph", s == 200 and len(d.get("nodes", [])) >= 1, f"nodes={len(d.get('nodes',[]))}")
    s, d = api("GET", "/impact/70/2025/NĐ-CP")
    record(g, "impact", s == 200 and "impacted_cases" in d)
    s, d = api("POST", "/feedback", {"kind": "lookup", "ref": "smoke q", "rating": "helpful"})
    record(g, "feedback", s == 200 and d.get("recorded"))
    s, d = api("POST", "/monitor/feedback", {"doc_id": "70/2025/NĐ-CP", "case_id": "smoke", "reason": "t"})
    record(g, "monitor/feedback (#3)", s == 200 and d.get("recorded"))
    s, d = api("POST", "/amendments/compile", {"items": [{"clause": "A", "issue": "x"}]})
    record(g, "amendments/compile", s == 200 and "markdown" in d)
    # auth: thiếu key → nếu bật REQUIRE_AUTH sẽ 401; chấp nhận 200 (tắt) hoặc 401 (bật)
    s, _ = api("GET", "/runs", key=None)
    record(g, "auth gate (/runs no key)", s in (200, 401), f"HTTP {s}")


def run_api_llm():
    g = "API-LLM"
    s, d = api("POST", "/ask", {"question": "Trần lãi suất cho vay theo Bộ luật Dân sự?", "lang": "vi"}, timeout=90)
    ok = s == 200 and "468" in d.get("answer", "")
    record(g, "ask (grounded)", ok, (d.get("answer", "")[:60] if s == 200 else f"HTTP {s}"))
    # analyze (multipart) + execution_summary
    body, ctype = _multipart({"text": "Bên B chịu phạt 15% nếu giao chậm; tranh chấp xử tại Singapore.",
                              "lang": "vi"})
    s, raw = http("POST", BASE + "/analyze", {"x-api-key": KEY, "content-type": ctype}, body, 200)
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        d = {}
    es = d.get("execution_summary", {})
    record(g, "analyze + execution_summary", s == 200 and es.get("total_tool_calls", 0) >= 1,
           f"risks={len(d.get('risks',[]))} tools={es.get('total_tool_calls')}")
    s, d = api("POST", "/counter", {"clause": "Phạt 15%", "risk": "vượt trần 8%", "suggestion": "giảm 8%",
                                    "legal_basis": "Điều 301 LTM", "leverage": "strong"}, timeout=90)
    record(g, "counter (bilingual)", s == 200 and bool(d.get("vi")), f"grounded={d.get('grounded')}")
    s, d = api("POST", "/negotiate", {"deal_context": "Phạt 15% trái Đ.301", "partner_message": "Chỉ giảm 12%",
                                      "lang": "vi", "leverage": "strong"}, timeout=90)
    record(g, "negotiate (multi-round)", s == 200 and d.get("status") in ("continue", "close", "walk_away"),
           f"status={d.get('status')}")
    s, d = api("POST", "/monitor/run", {"since": "2020-01-01"}, timeout=60)
    record(g, "monitor/run (autopilot)", s == 200 and "new_laws_scanned" in d,
           f"scanned={d.get('new_laws_scanned')}")


def _multipart(fields: dict):
    boundary = "----smoke" + str(int(time.time()))
    parts = []
    for k, v in fields.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n")
    body = ("".join(parts) + f"--{boundary}--\r\n").encode()
    return body, f"multipart/form-data; boundary={boundary}"


def run_slack(no_llm: bool):
    g = "Slack"
    if not (SIGNING and BOT and CHANNEL):
        record(g, "config", None, "thiếu SLACK_SIGNING_SECRET/BOT_TOKEN/TEST_CHANNEL → bỏ qua Slack")
        return
    auth = slack_get("auth.test", {})
    if not auth.get("ok"):
        record(g, "auth.test", False, auth.get("error"))
        return
    bot_uid = auth.get("user_id")
    record(g, "auth.test", True, f"bot={auth.get('user')}")

    # bảo mật: chữ ký sai → 401
    s, _ = slack_event("x", "1.1", bad_sig=True)
    record(g, "events bad signature → 401", s == 401, f"HTTP {s}")
    s, _ = slack_interact({"type": "block_actions", "actions": [{"action_id": "fb_helpful", "value": "{}"}]}, bad_sig=True)
    record(g, "interactions bad signature → 401", s == 401, f"HTTP {s}")

    # nút feedback → ghi DB
    n0 = len(api("GET", "/feedback?limit=300")[1] or [])
    s, d = slack_interact({"type": "block_actions", "user": {"id": "U_SMOKE"},
                           "actions": [{"action_id": "fb_helpful", "value": json.dumps({"k": "lookup", "r": "smoke"})}]})
    n1 = len(api("GET", "/feedback?limit=300")[1] or [])
    record(g, "interaction feedback → records", s == 200 and n1 > n0, f"feedback {n0}->{n1}")

    # events: lookup + trust (async, poll reply)
    if not no_llm:
        for name, q, expect in [
            ("event lookup", "Trần lãi suất cho vay theo Bộ luật Dân sự?", "468"),
            ("event trust", "Độ chính xác của hệ thống thế nào?", "tin cậy"),
        ]:
            ts = slack_post_msg(f"[SMOKE] {q}")
            if not ts:
                record(g, name, None, "không post được (channel?)")
                continue
            slack_event(q, ts, bot_uid=bot_uid)
            reply = wait_bot_reply(ts, bot_uid, timeout=60)
            record(g, name, expect.lower() in reply.lower(), reply[:70] or "(không có reply)")

        # analyze qua Slack (chậm) + nút trong reply
        q = "Rà soát: Bên B chịu phạt 15% nếu giao chậm; tranh chấp xử tại Singapore."
        ts = slack_post_msg(f"[SMOKE analyze] {q}")
        if ts:
            slack_event(q, ts, bot_uid=bot_uid)
            reply = wait_bot_reply(ts, bot_uid, timeout=130)
            record(g, "event analyze", bool(reply) and ("301" in reply or "phạt" in reply.lower()), reply[:70])
    else:
        record(g, "events (lookup/trust/analyze)", None, "--no-llm")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-slack", action="store_true")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--quick", action="store_true", help="chỉ API nhanh tất định")
    args = ap.parse_args()

    print(f"== Legal Guard smoke @ {BASE} (key={'set' if KEY else 'none'}, slack={'set' if BOT else 'none'}) ==")
    print("\n— API nhanh (tất định) —")
    run_api_fast()
    if not args.quick and not args.no_llm:
        print("\n— API LLM (chậm) —")
        run_api_llm()
    if not args.quick and not args.no_slack:
        print("\n— Slack —")
        run_slack(args.no_llm)

    print(f"\n== TỔNG: {len(PASS)} pass · {len(FAIL)} fail · {len(SKIP)} skip ==")
    if FAIL:
        print("FAIL:", "; ".join(FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
