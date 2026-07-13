import { NextRequest, NextResponse } from "next/server";
import { bffGet } from "@/lib/bff";

// BFF: /api/obligations?within=N → /obligations (nghĩa vụ & hạn chót sắp tới).
export async function GET(req: NextRequest) {
  const within = req.nextUrl.searchParams.get("within");
  const { status, data } = await bffGet(`/obligations${within ? `?within=${encodeURIComponent(within)}` : ""}`);
  return NextResponse.json(data, { status });
}
