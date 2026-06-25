"""Integration check — chạy các luồng THẬT (có gọi LLM Qwen) đúng như khi dùng trên Slack,
rồi LƯU SNAPSHOT để so sánh/đối chiếu giữa các lần chạy.

Khác `run_eval`/pytest (offline, stub): file này CÓ gọi LLM thật → tốn API call, KHÔNG tất định.
Mục đích: kiểm bằng mắt + theo dõi hồi quy chất lượng (regression) khi đổi prompt/model/KB.

Chạy (cần QWEN_API_KEY trong .env):
    uv run python -m evaluation.integration_check
    uv run python -m evaluation.integration_check --compare evaluation/snapshots/<cũ>/snapshot.json

Lưu gì:
- `evaluation/snapshots/<timestamp>/snapshot.json` — bản ghi máy đọc được (diff/so sánh).
- `evaluation/snapshots/<timestamp>/snapshot.md`   — bản người đọc (eyeball/chia sẻ).
So sánh 2 lần chạy:  git diff --no-index A/snapshot.json B/snapshot.json   (hoặc --compare ở trên).
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from legalguard.adapters.inbound.channels import ChatHandler
from legalguard.adapters.outbound.conversation_store import InMemoryConversationStore
from legalguard.adapters.outbound.document_parser import PdfDocxParser
from legalguard.config.container import build_service
from legalguard.config.settings import settings

_OUT_ROOT = Path("evaluation/snapshots")

# HĐ mẫu (tiếng Anh, có tín hiệu "arbitration/payment/delivery", KHÔNG dấu hỏi → route sang ANALYZE).
_SAMPLE_CONTRACT = (
    "1. Governing Law & Arbitration. This contract is governed by the laws of the People's Republic "
    "of China. Any dispute shall be finally settled by arbitration in Beijing under CIETAC rules, in "
    "Chinese.\n"
    "2. Payment. The Buyer shall pay 100% by T/T within 90 days after delivery.\n"
    "3. Inspection. Quality and quantity shall be determined solely by inspection at the destination "
    "port designated by the Seller, whose certificate shall be final and binding.\n"
    "4. Penalty. If the Seller delays delivery, the Buyer may claim a penalty of 30% of the total "
    "contract value. No penalty applies to the Buyer for late payment.\n"
    "5. Termination. The Seller may terminate at any time with 7 days notice; the Buyer may not "
    "terminate once the order is placed."
)


def _run_scenarios(handler: ChatHandler, service) -> list[dict]:
    """Mỗi scenario mô phỏng 1 lượt trên Slack (qua ChatHandler) hoặc 1 tính năng LLM, kèm đo thời gian."""
    out: list[dict] = []

    def record(name: str, desc: str, fn) -> dict:
        t0 = time.perf_counter()
        err, payload = None, {}
        try:
            payload = fn()
        except Exception as exc:  # noqa: BLE001 — ghi lỗi vào snapshot, không dừng cả lần chạy
            err = f"{type(exc).__name__}: {exc}"
        item = {"name": name, "description": desc,
                "duration_ms": round((time.perf_counter() - t0) * 1000), "error": err, **payload}
        out.append(item)
        print(f"  • {name}: {'LỖI ' + err if err else 'OK'} ({item['duration_ms']} ms)")
        return item

    conv = "slack:C_DEMO"   # dùng CHUNG 1 conversation_id để follow-up nhớ ngữ cảnh (như 1 thread Slack)

    # 1) Slack: dán hợp đồng → rà soát. Lưu cả reply (Slack thấy) lẫn case structured (đối chiếu).
    def analyze():
        r = handler.reply_ex(conv, text=_SAMPLE_CONTRACT, lang="vi")
        case = service.get_case(r.ref) if r.ref else None
        detail = None
        if case is not None:
            detail = {"risks": case.risks, "fallbacks": case.fallbacks,
                      "needs_human_review": case.needs_human_review}
        return {"input": _SAMPLE_CONTRACT, "routed_kind": r.kind, "case_id": r.ref,
                "reply_text": r.text, "case_detail": detail}
    record("slack_analyze", "Dán HĐ vào Slack → rà soát rủi ro + fallback + chiến lược", analyze)

    # 2) Slack: hỏi tiếp trong cùng thread (đã có deal context) → _followup qua reasoner.
    fu = "Nếu đối tác nhất quyết không đổi nơi trọng tài khỏi Bắc Kinh thì mình nên làm gì?"
    record("slack_followup", "Hỏi tiếp sau khi rà soát (nhớ ngữ cảnh deal)",
           lambda: {"input": fu, **_reply(handler, conv, fu)})

    # 3) Slack: câu hỏi pháp lý độc lập (thread mới) → tra cứu KB có grounding.
    q = "Mức phạt vi phạm hợp đồng tối đa là bao nhiêu phần trăm giá trị nghĩa vụ?"
    record("slack_lookup", "Hỏi pháp lý độc lập → tra cứu dẫn Điều/Khoản còn hiệu lực",
           lambda: {"input": q, **_reply(handler, "slack:C_LOOKUP", q)})

    # 4) Lookup point-in-time: hỏi luật TẠI một mốc thời gian.
    q2 = "Năm 2020 thì văn bản nào quy định về hóa đơn điện tử đang có hiệu lực?"
    record("slack_lookup_point_in_time", "Tra cứu theo mốc thời gian (point-in-time)",
           lambda: {"input": q2, **_reply(handler, "slack:C_PIT", q2)})

    # 5) Counter-clause: soạn điều khoản phản-đề song ngữ (có gọi LLM).
    record("counter_clause", "Soạn điều khoản phản-đề VN/EN cho điều khoản phạt một chiều",
           lambda: {"output": service.draft_counter_clause(
               clause="Penalty of 30% for seller's delay; none for buyer's late payment",
               risk="Phạt một chiều, mức 30% vượt trần 8% của Luật Thương mại 2005",
               suggestion="Đưa phạt về đối xứng hai chiều, trần 8% theo luật VN",
               legal_basis="luat_thuong_mai_2005_che_tai.md#Điều 301", leverage="balanced")})

    # 6) Regulatory impact (tất định, không LLM) — VB mới ảnh hưởng case nào của org 'default'.
    record("regulatory_impact", "VB mới 70/2025/NĐ-CP ảnh hưởng hợp đồng đã rà soát nào",
           lambda: {"output": service.regulatory_impact("70/2025/NĐ-CP", "VN", "default")})

    # 7) Dashboard (tất định) — tổng hợp những gì lần chạy này tạo ra cho org 'default'.
    record("dashboard", "System-of-record tổng hợp org 'default'",
           lambda: {"output": service.dashboard("default")})

    return out


def _reply(handler: ChatHandler, conv: str, text: str) -> dict:
    r = handler.reply_ex(conv, text=text, lang="vi")
    return {"routed_kind": r.kind, "reply_text": r.text}


def _to_markdown(meta: dict, items: list[dict]) -> str:
    lines = [f"# Integration snapshot — {meta['timestamp']}",
             f"- Model: `{meta['qwen_model']}` · commit: `{meta['git_commit']}`",
             f"- Scenarios: {len(items)} · lỗi: {sum(1 for i in items if i['error'])}", ""]
    for it in items:
        lines.append(f"## {it['name']} — {it['description']}")
        lines.append(f"_{it['duration_ms']} ms_" + (f" · ⚠️ **{it['error']}**" if it['error'] else ""))
        if it.get("input"):
            lines.append(f"\n**Input:**\n\n```\n{it['input'][:1200]}\n```")
        if it.get("routed_kind"):
            lines.append(f"\n**Định tuyến:** `{it['routed_kind']}`")
        if it.get("reply_text"):
            lines.append(f"\n**Trả lời (Slack thấy):**\n\n{it['reply_text']}")
        if it.get("case_detail"):
            lines.append(f"\n**Chi tiết case:**\n\n```json\n"
                         f"{json.dumps(it['case_detail'], ensure_ascii=False, indent=2)[:3000]}\n```")
        if it.get("output") is not None:
            lines.append(f"\n**Output:**\n\n```json\n"
                         f"{json.dumps(it['output'], ensure_ascii=False, indent=2)[:3000]}\n```")
        lines.append("")
    return "\n".join(lines)


def _git_commit() -> str:
    head = Path(".git/HEAD")
    try:
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref:"):
            return Path(".git", ref[5:]).read_text(encoding="utf-8").strip()[:12]
        return ref[:12]
    except OSError:
        return "unknown"


def _compare(items: list[dict], old_path: str) -> None:
    """So nhanh với 1 snapshot cũ: theo scenario, báo đổi định tuyến / số risk / độ dài reply."""
    old = {i["name"]: i for i in json.loads(Path(old_path).read_text(encoding="utf-8"))["scenarios"]}
    print(f"\nSo với {old_path}:")
    for it in items:
        o = old.get(it["name"])
        if not o:
            print(f"  • {it['name']}: MỚI (không có ở bản cũ)")
            continue
        diffs = []
        if it.get("routed_kind") != o.get("routed_kind"):
            diffs.append(f"định tuyến {o.get('routed_kind')}→{it.get('routed_kind')}")
        nr_new = len((it.get("case_detail") or {}).get("risks") or [])
        nr_old = len((o.get("case_detail") or {}).get("risks") or [])
        if nr_new != nr_old:
            diffs.append(f"#risk {nr_old}→{nr_new}")
        ln, lo = len(it.get("reply_text") or ""), len(o.get("reply_text") or "")
        if ln and lo and abs(ln - lo) / max(lo, 1) > 0.4:
            diffs.append(f"độ dài reply {lo}→{ln}")
        print(f"  • {it['name']}: {'; '.join(diffs) if diffs else 'tương đương'}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Integration check (gọi LLM thật) + lưu snapshot")
    ap.add_argument("--compare", help="đường dẫn snapshot.json cũ để so sánh nhanh")
    args = ap.parse_args()

    if not settings.qwen_api_key:
        raise SystemExit("Chưa có QWEN_API_KEY trong .env — file này cần LLM thật. "
                         "Dùng `uv run pytest` cho test offline (stub).")

    service = build_service()
    handler = ChatHandler(service, PdfDocxParser(), InMemoryConversationStore(), settings.default_tenant)

    print(f"Chạy integration check (model={settings.qwen_model})…")
    items = _run_scenarios(handler, service)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    meta = {"timestamp": ts, "qwen_model": settings.qwen_model, "git_commit": _git_commit(),
            "scenario_count": len(items), "errors": sum(1 for i in items if i["error"])}
    out_dir = _OUT_ROOT / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "snapshot.json").write_text(
        json.dumps({"meta": meta, "scenarios": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "snapshot.md").write_text(_to_markdown(meta, items), encoding="utf-8")
    print(f"\nĐã lưu:\n  {out_dir}/snapshot.json  (máy đọc — để diff)\n  {out_dir}/snapshot.md    (người đọc)")

    if args.compare:
        _compare(items, args.compare)


if __name__ == "__main__":
    main()
