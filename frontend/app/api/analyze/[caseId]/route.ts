import { NextRequest, NextResponse } from "next/server";
import { BASE, authHeaders } from "@/lib/api";

// BFF poll: GET /api/analyze/{caseId} → /analyze/result/{caseId}.
// Truyền NGUYÊN status: 404 = đang xử lý (client poll tiếp), 200 = xong, 502 = lỗi phân tích.
export async function GET(_req: NextRequest, { params }: { params: { caseId: string } }) {
  try {
    const res = await fetch(`${BASE}/analyze/result/${encodeURIComponent(params.caseId)}`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 502 });
  }
}
