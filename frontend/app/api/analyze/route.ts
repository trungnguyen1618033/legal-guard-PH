import { NextRequest, NextResponse } from "next/server";
import { BASE, authHeaders } from "@/lib/api";

// BFF: browser POST /api/analyze (multipart: text|file + vị thế) → proxy tới /analyze trên ECS.
// LUÔN async_mode=true → trả {case_id} ngay, client poll /api/analyze/{caseId}. Key giữ kín server-side.
export async function POST(req: NextRequest) {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return NextResponse.json({ error: "Form không hợp lệ." }, { status: 400 });
  }
  form.set("async_mode", "true");
  try {
    const res = await fetch(`${BASE}/analyze`, {
      method: "POST",
      headers: authHeaders(),
      body: form,
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 502 });
  }
}
