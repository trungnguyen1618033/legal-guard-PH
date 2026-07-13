import { NextRequest, NextResponse } from "next/server";
import { bffPost } from "@/lib/bff";

// BFF: POST /api/obligations/{id}/status → đánh dấu done/dismissed (org-scoped ở backend).
export async function POST(req: NextRequest, { params }: { params: { id: string } }) {
  const { status, data } = await bffPost(`/obligations/${encodeURIComponent(params.id)}/status`, await req.json());
  return NextResponse.json(data, { status });
}
