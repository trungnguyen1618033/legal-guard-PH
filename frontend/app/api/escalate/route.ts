import { NextRequest, NextResponse } from "next/server";
import { BASE, authHeaders } from "@/lib/api";

// BFF: reviewer Từ chối → POST /api/escalate → /escalate (gửi case cho luật sư qua kênh chuyên gia).
export async function POST(req: NextRequest) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Body JSON không hợp lệ." }, { status: 400 });
  }
  try {
    const res = await fetch(`${BASE}/escalate`, {
      method: "POST",
      headers: authHeaders({ "content-type": "application/json" }),
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 502 });
  }
}
