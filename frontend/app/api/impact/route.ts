import { NextRequest, NextResponse } from "next/server";
import { bffGet } from "@/lib/bff";

export async function GET(req: NextRequest) {
  const doc = req.nextUrl.searchParams.get("doc");
  if (!doc) return NextResponse.json({ error: "Thiếu tham số doc." }, { status: 400 });
  const depth = req.nextUrl.searchParams.get("depth");
  const qs = depth ? `?depth=${encodeURIComponent(depth)}` : "";
  const { status, data } = await bffGet(`/impact/${encodeURIComponent(doc)}${qs}`);
  return NextResponse.json(data, { status });
}
