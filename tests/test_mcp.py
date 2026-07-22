from legalguard.adapters.inbound.mcp_server import (
    analyze_contract_tool,
    build_mcp,
    lookup_law_tool,
    recall_memory_tool,
)


def test_mcp_tool_analyzes_contract():
    out = analyze_contract_tool("Tranh chấp bằng trọng tài tại Bắc Kinh.", leverage="weak", lang="vi")
    assert any(r["clause"] == "Điều khoản trọng tài" for r in out["risks"])
    assert out["strategy"]
    assert "needs_human_review" in out


def test_mcp_lookup_law_tool_shape():
    out = lookup_law_tool("Mức phạt vi phạm hợp đồng thương mại tối đa?", lang="vi")
    assert "answer" in out and "citations" in out and isinstance(out["citations"], list)


def test_mcp_recall_memory_tool_shape():
    out = recall_memory_tool("phạt chậm thanh toán")   # flag OFF mặc định → rỗng, nhưng shape đúng
    assert "episodes" in out and isinstance(out["episodes"], list)


def test_mcp_server_registers_tools():
    mcp = build_mcp()                 # import FastMCP + đăng ký 3 tool không lỗi
    assert mcp is not None
