from legalguard.adapters.inbound.mcp_server import analyze_contract_tool, build_mcp


def test_mcp_tool_analyzes_contract():
    out = analyze_contract_tool("Tranh chấp bằng trọng tài tại Bắc Kinh.", leverage="weak", lang="vi")
    assert any(r["clause"] == "Điều khoản trọng tài" for r in out["risks"])
    assert out["strategy"]
    assert "needs_human_review" in out


def test_mcp_server_registers_tool():
    mcp = build_mcp()                 # import FastMCP + đăng ký tool không lỗi
    assert mcp is not None
