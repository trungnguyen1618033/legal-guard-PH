import { NextRequest, NextResponse } from "next/server";
import { bffPost } from "@/lib/bff";

export async function POST(req: NextRequest) {
  const { status, data } = await bffPost("/monitor/run", await req.json());
  return NextResponse.json(data, { status });
}
