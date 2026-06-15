"""Inbound adapter: MCP server — expose Legal Guard thành tool cho mọi MCP client.

MCP (Model Context Protocol) là chuẩn de-facto 2026 để agent gọi tool; Qwen3/Qwen-Agent hỗ trợ sâu.
Bất kỳ MCP client (Qwen-Agent, Claude, IDE...) đều dùng được tool `analyze_contract`.

Chạy (stdio):  uv run python -m legalguard.adapters.inbound.mcp_server
"""
from __future__ import annotations

from legalguard.config.container import build_service
from legalguard.domain.models import NegotiationPosition
from legalguard.domain.tenants import default_org

_SERVICE = None


def _svc():
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = build_service()
    return _SERVICE


def analyze_contract_tool(text: str, leverage: str = "balanced", lang: str = "en") -> dict:
    """Rà soát hợp đồng ngoại thương: rủi ro + fallback + chiến lược đàm phán (theo vị thế)."""
    result = _svc().analyze(text, default_org("VN"), lang=lang,
                            position=NegotiationPosition(leverage=leverage))
    return {
        "risks": result.risks,
        "fallbacks": result.fallbacks,
        "strategy": result.strategy,
        "needs_human_review": result.needs_human_review,
        "case_id": result.case_id,
    }


def build_mcp():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("legal-guard")
    mcp.tool()(analyze_contract_tool)
    return mcp


def main() -> None:
    build_mcp().run()   # stdio transport


if __name__ == "__main__":
    main()
