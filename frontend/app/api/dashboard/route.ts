import { NextResponse } from "next/server";
import { getDashboard } from "@/lib/api";

// BFF: /api/dashboard → /insights/dashboard (cần auth) — key giữ kín server-side.
export async function GET() {
  try {
    return NextResponse.json(await getDashboard());
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 502 });
  }
}
