"""Tool agent được phép gọi + dispatcher (domain logic).

Structured output: LLM phát tool-call theo schema, ta thu dữ liệu có cấu trúc
thay vì parse JSON từ text tự do.
"""
from __future__ import annotations

from legalguard.domain.models import AgentContext, Fallback, Risk

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_legal_knowledge",
            "description": "Tra cứu knowledge base luật/chính sách rủi ro/fallback của quốc gia tenant.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Nội dung cần tra cứu"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flag_risk",
            "description": "Ghi nhận một điều khoản rủi ro. PHẢI kèm `source` (nguồn KB grounding).",
            "parameters": {
                "type": "object",
                "properties": {
                    "reasoning": {"type": "string",
                                  "description": "ĐIỀN TRƯỚC TIÊN (1-2 câu): vì sao điều khoản này rủi ro "
                                  "với khách, và vì sao chọn mức `severity`+`priority` đó theo vị thế. "
                                  "Suy luận trước rồi mới điền các trường quyết định bên dưới."},
                    "clause": {"type": "string"},
                    "risk": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "priority": {"type": "string", "enum": ["must_fix", "negotiate", "acceptable"],
                                 "description": "Ưu tiên theo vị thế đàm phán của khách"},
                    "legal_status": {"type": "string", "enum": ["illegal", "unfavorable"],
                                     "description": "illegal = TRÁI LUẬT (vi phạm quy định bắt buộc → có thể "
                                     "VÔ HIỆU, vd phạt >8% trần Điều 301); unfavorable = bất lợi nhưng hợp pháp"},
                    "violated_law": {"type": "string", "description": "Điều luật bị vi phạm (khi illegal), "
                                     "vd 'Điều 301 Luật Thương mại 2005'. Để trống nếu unfavorable."},
                    "source": {"type": "string", "description": "Quote/nguồn KB chính sách rủi ro"},
                    "evidence": {"type": "string", "description": "Trích NGUYÊN VĂN đoạn trong hợp đồng"},
                },
                "required": ["clause", "risk", "severity", "source", "evidence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_fallback",
            "description": "Đề xuất chiến thuật thỏa hiệp + câu mẫu tiếng Anh sẵn gửi đối tác.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reasoning": {"type": "string",
                                  "description": "ĐIỀN TRƯỚC TIÊN (1-2 câu): vì sao chiến thuật này hợp "
                                  "vị thế khách (giữ/nhượng), bám căn cứ nào. Suy luận trước rồi mới điền "
                                  "`suggestion`+`english_reply`."},
                    "clause": {"type": "string"},
                    "suggestion": {"type": "string", "description": "Chiến thuật (tiếng Việt)"},
                    "english_reply": {"type": "string", "description": "Câu gửi đối tác (tiếng Anh)"},
                    "source": {"type": "string", "description": "Nguồn KB grounding"},
                },
                "required": ["clause", "suggestion"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_human_review",
            "description": "Đánh dấu cần chuyên gia pháp lý duyệt trước khi đưa khuyến nghị (rủi ro cao).",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
]


def execute_tool(name: str, args: dict, ctx: AgentContext) -> str:
    """Thực thi 1 tool-call, cập nhật ctx, trả observation cho LLM đọc tiếp.

    Tool lỗi (vd retriever hỏng) → trả observation lỗi để agent tự xử lý,
    KHÔNG ném exception làm sập cả vòng phân tích.
    """
    try:
        return _dispatch(name, args, ctx)
    except Exception as exc:  # noqa: BLE001
        return f"Lỗi khi chạy tool {name}: {exc}. Hãy tiếp tục với thông tin đang có."


def _dispatch(name: str, args: dict, ctx: AgentContext) -> str:
    if name == "search_legal_knowledge":
        hits = ctx.retriever.retrieve(args.get("query", ""), top_k=4)
        if not hits:
            return "Không tìm thấy mục liên quan."
        # Kèm nguồn để agent trích dẫn (grounding).
        return "\n---\n".join(f"[nguồn: {h.source}] {h.text}" for h in hits)
    if name == "flag_risk":
        clause = (args.get("clause") or "").strip()
        risk = (args.get("risk") or "").strip()
        if not clause or not risk:                       # QA: bỏ output rác/thiếu
            return "Bỏ qua: flag_risk thiếu clause hoặc risk."
        severity = args.get("severity", "medium")
        if severity not in ("low", "medium", "high"):    # QA: ép enum hợp lệ
            severity = "medium"
        priority = args.get("priority", "")
        if priority not in ("must_fix", "negotiate", "acceptable"):
            priority = "negotiate"
        legal_status = args.get("legal_status", "unfavorable")
        if legal_status not in ("illegal", "unfavorable"):   # QA: ép enum; nghi ngờ → unfavorable (bảo thủ)
            legal_status = "unfavorable"
        violated = (args.get("violated_law", "") if legal_status == "illegal" else "")
        ctx.risks.append(Risk(clause=clause, risk=risk, severity=severity, priority=priority,
                              source=args.get("source", ""), evidence=args.get("evidence", ""),
                              legal_status=legal_status, violated_law=violated))
        return f"Đã ghi nhận rủi ro: {clause}"
    if name == "propose_fallback":
        clause = (args.get("clause") or "").strip()
        suggestion = (args.get("suggestion") or "").strip()
        if not clause or not suggestion:                 # QA: bỏ output rác/thiếu
            return "Bỏ qua: propose_fallback thiếu clause hoặc suggestion."
        ctx.fallbacks.append(Fallback(clause=clause, suggestion=suggestion,
                                      english_reply=args.get("english_reply", ""),
                                      source=args.get("source", "")))
        return f"Đã ghi nhận fallback cho: {clause}"
    if name == "request_human_review":
        ctx.needs_human_review = True
        ctx.review_reasons.append(args.get("reason", ""))
        return "Đã gắn cờ cần người duyệt."
    return f"Tool không tồn tại: {name}"
