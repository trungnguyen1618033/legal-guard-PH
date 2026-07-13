import { NextResponse } from "next/server";
import { bffGet } from "@/lib/bff";

// BFF: /api/portfolio → /portfolio (danh mục HĐ hành-động-được, org-scoped).
export async function GET() {
  const { status, data } = await bffGet("/portfolio");
  return NextResponse.json(data, { status });
}
