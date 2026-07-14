#!/usr/bin/env python3
"""Dọn dữ liệu TEST do smoke_live để lại trên prod: (1) case rà soát, (2) tin [SMOKE] trên Slack.
MẶC ĐỊNH dry-run (chỉ liệt kê) — thêm `--yes` để XOÁ THẬT. (Feedback ref='smoke' phải xoá bằng SQL — xem
cuối output.)

Chỉ xoá case THOẢ CẢ HAI: created_at >= --since (mặc định hôm nay UTC) VÀ excerpt chứa --marker → an toàn,
không đụng case thật cũ. Slack: chỉ tin chứa '[SMOKE' + reply trong thread của chúng (bot tự xoá tin mình).

Chạy:
  API_BASE=https://legalguard.duckdns.org CHANNEL_ID=C0B8SC8FJCF uv run python -m scripts.cleanup_smoke          # xem trước
  API_BASE=https://legalguard.duckdns.org CHANNEL_ID=C0B8SC8FJCF uv run python -m scripts.cleanup_smoke --yes    # xoá thật
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def _load_env() -> dict:
    env = {}
    for p in (Path(".env"), Path(__file__).resolve().parent.parent / ".env"):
        if p.exists():
            for ln in p.read_text().splitlines():
                if "=" in ln and not ln.strip().startswith("#"):
                    k, v = ln.split("=", 1)
                    env.setdefault(k.strip(), v.strip().strip('"'))
    import os
    env.update({k: v for k, v in os.environ.items()})
    return env


ENV = _load_env()
BASE = ENV.get("API_BASE", "http://127.0.0.1:8000").rstrip("/")
KEY = ENV.get("API_KEY") or (ENV.get("API_KEYS", "").split(",")[0].split(":")[0])
TOKEN = ENV.get("SLACK_BOT_TOKEN", "")
CHANNEL = ENV.get("SLACK_TEST_CHANNEL") or ENV.get("CHANNEL_ID", "")


def _api(method: str, path: str) -> object:
    r = urllib.request.Request(BASE + path, method=method, headers={"x-api-key": KEY})
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.load(resp) if resp.status == 200 else resp.status


def _slack(m: str, **p) -> dict:
    data = urllib.parse.urlencode(p).encode()
    r = urllib.request.Request(f"https://slack.com/api/{m}", data,
                               {"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.load(resp)


def clean_cases(since: str, marker: str, do: bool) -> None:
    print(f"\n== CASES (created >= {since} & excerpt chứa '{marker}') ==")
    cases = _api("GET", "/cases?limit=60")
    if not isinstance(cases, list):
        print(f"  lỗi đọc /cases: {cases}")
        return
    targets = [c for c in cases if (c.get("created_at") or "") >= since
               and marker.lower() in (c.get("contract_excerpt") or "").lower()]
    print(f"  khớp: {len(targets)}")
    for c in targets:
        cid = c["id"]
        if do:
            code = _api("DELETE", f"/cases/{cid}")
            print(f"  XOÁ {cid[:8]} ({c.get('created_at','')[:19]}) -> {code}")
        else:
            print(f"  [dry] {cid[:8]} ({c.get('created_at','')[:19]}) {(c.get('contract_excerpt') or '')[:45]}")


def clean_slack(do: bool) -> None:
    print(f"\n== SLACK [SMOKE] @ {CHANNEL} ==")
    if not (TOKEN and CHANNEL):
        print("  thiếu SLACK_BOT_TOKEN/CHANNEL → bỏ qua")
        return
    hist = _slack("conversations.history", channel=CHANNEL, limit=200)
    parents = [m for m in hist.get("messages", []) if "[SMOKE" in (m.get("text") or "")]
    tss: list[str] = []
    for m in parents:
        tss.append(m["ts"])
        rep = _slack("conversations.replies", channel=CHANNEL, ts=m["ts"])
        tss += [r["ts"] for r in rep.get("messages", [])[1:]]
    print(f"  tin [SMOKE] + reply: {len(tss)}")
    for ts in tss:
        if do:
            ok = _slack("chat.delete", channel=CHANNEL, ts=ts).get("ok")
            print(f"  XOÁ {ts} -> {ok}")
            time.sleep(0.35)
        else:
            print(f"  [dry] {ts}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    help="chỉ xoá case created_at >= mốc này (ISO, mặc định hôm nay UTC)")
    ap.add_argument("--marker", default="15%", help="excerpt phải chứa (an toàn, tránh case thật)")
    ap.add_argument("--yes", action="store_true", help="XOÁ THẬT (không có = dry-run)")
    args = ap.parse_args()
    print(f"cleanup_smoke @ {BASE} · yes={args.yes}")
    clean_cases(args.since, args.marker, args.yes)
    clean_slack(args.yes)
    print("\n== FEEDBACK (ref='smoke') — chạy SQL trên server (không có API xoá) ==")
    print("  ssh ... \"docker exec legalguard-db-1 psql -U legalguard -d legalguard "
          "-c \\\"DELETE FROM feedback WHERE ref='smoke';\\\"\"")
    if not args.yes:
        print("\n(dry-run — thêm --yes để xoá thật)")


if __name__ == "__main__":
    main()
