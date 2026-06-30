import { NextRequest, NextResponse } from "next/server";
import { BASE, authHeaders } from "@/lib/api";

// BFF binary: POST /api/amendments/compile-docx → /amendments/compile.docx (Word).
// Thiếu python-docx → backend trả 501; truyền nguyên để UI fallback sang markdown.
export async function POST(req: NextRequest) {
  const body = await req.text();
  const res = await fetch(`${BASE}/amendments/compile.docx`, {
    method: "POST",
    headers: authHeaders({ "content-type": "application/json" }),
    body,
    cache: "no-store",
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    return NextResponse.json(data, { status: res.status });
  }
  const buf = await res.arrayBuffer();
  return new NextResponse(buf, {
    status: 200,
    headers: {
      "content-type": res.headers.get("content-type") ?? "application/octet-stream",
      "content-disposition": 'attachment; filename="ban-ghi-nho-sua-doi.docx"',
    },
  });
}
