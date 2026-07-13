import { NextRequest, NextResponse } from "next/server";
import { bffGet } from "@/lib/bff";

// VB còn hiệu lực pháp luật không → /in-force/{doc_id}. doc_id có dấu "/" (mẫu như graph route).
export async function GET(req: NextRequest) {
  const doc = req.nextUrl.searchParams.get("doc");
  if (!doc) return NextResponse.json({ error: "Thiếu tham số doc." }, { status: 400 });
  const { status, data } = await bffGet(`/in-force/${encodeURIComponent(doc)}`);
  return NextResponse.json(data, { status });
}
