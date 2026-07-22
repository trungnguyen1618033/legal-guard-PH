"""Ops helper agent-ready quanh CockroachDB `ccloud` CLI (feature #2/4 CockroachDB hackathon).

`ccloud` = CLI "agent-ready" (output JSON mọi lệnh) → script/agent tự động hoá vận hành cluster mà không
cần Console. Dùng cho deploy (lấy connection-string) + monitoring (version/state). Yêu cầu: đã
`ccloud auth login` (token lưu ~/.ccloud). Mọi lệnh trả JSON ra stdout → nhét thẳng vào pipeline/agent.

    uv run python -m scripts.crdb_ops clusters                # liệt kê cluster (JSON)
    uv run python -m scripts.crdb_ops info <cluster>          # version/state/region 1 cluster
    uv run python -m scripts.crdb_ops connstring <cluster>    # connection-string SQL (cho deploy)
    uv run python -m scripts.crdb_ops health <cluster>        # {healthy, state, version} — cho monitor/CI
"""
from __future__ import annotations

import json
import subprocess
import sys


def _ccloud(*args: str) -> subprocess.CompletedProcess:
    """Gọi ccloud, ưu tiên JSON. Trả CompletedProcess (kiểm returncode)."""
    return subprocess.run(["ccloud", *args], capture_output=True, text=True, timeout=60)


def _clusters() -> list[dict]:
    p = _ccloud("cluster", "list", "-o", "json", "--quiet")
    if p.returncode != 0:
        raise SystemExit(f"ccloud lỗi (đã `ccloud auth login` chưa?): {p.stderr.strip()}")
    return json.loads(p.stdout or "[]")


def _find(name: str) -> dict:
    for c in _clusters():
        if c.get("name") == name or c.get("id") == name:
            return c
    raise SystemExit(f"Không thấy cluster '{name}'.")


def cmd_clusters() -> None:
    print(json.dumps(_clusters(), indent=2, ensure_ascii=False))


def cmd_info(name: str) -> None:
    print(json.dumps(_find(name), indent=2, ensure_ascii=False))


def cmd_connstring(name: str) -> None:
    """connection-string SQL cho deploy (P5). ccloud tự chèn cluster đúng; secret KHÔNG in ở đây (ccloud lo)."""
    p = _ccloud("cluster", "connection-string", name, "--sql")
    if p.returncode != 0:
        raise SystemExit(f"ccloud lỗi: {p.stderr.strip()}")
    print(p.stdout.strip())


def cmd_health(name: str) -> None:
    """Tóm tắt sức khoẻ cho monitor/CI (JSON tất định)."""
    c = _find(name)
    print(json.dumps({"cluster": c.get("name"), "healthy": c.get("state") == "CREATED",
                      "state": c.get("state"), "version": c.get("cockroach_version"),
                      "plan": c.get("plan"),
                      "region": (c.get("regions") or [{}])[0].get("name", "")},
                     ensure_ascii=False))


_CMDS = {"clusters": cmd_clusters, "info": cmd_info, "connstring": cmd_connstring, "health": cmd_health}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in _CMDS:
        raise SystemExit(f"Dùng: python -m scripts.crdb_ops <{'|'.join(_CMDS)}> [cluster]")
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "clusters":
        cmd_clusters()
    else:
        if not rest:
            raise SystemExit(f"'{cmd}' cần tên cluster.")
        _CMDS[cmd](rest[0])


if __name__ == "__main__":
    main()
