import { NextRequest, NextResponse } from "next/server";
import { bffPost } from "@/lib/bff";

// BFF: user báo cảnh báo monitor là nhầm → /monitor/feedback (autopilot tự lọc lần sau).
export async function POST(req: NextRequest) {
  const { status, data } = await bffPost("/monitor/feedback", await req.json());
  return NextResponse.json(data, { status });
}
