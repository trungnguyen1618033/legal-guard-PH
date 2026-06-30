import { NextRequest, NextResponse } from "next/server";
import { bffPost } from "@/lib/bff";

export async function POST(req: NextRequest, { params }: { params: { caseId: string } }) {
  const { status, data } = await bffPost(`/cases/${encodeURIComponent(params.caseId)}/outcome`, await req.json());
  return NextResponse.json(data, { status });
}
