import { NextRequest, NextResponse } from "next/server";
import { bffGet, bffPost } from "@/lib/bff";

// BFF: /api/org/policy → playbook công ty (GET danh sách, POST thêm/sửa).
export async function GET() {
  const { status, data } = await bffGet("/org/policy");
  return NextResponse.json(data, { status });
}

export async function POST(req: NextRequest) {
  const { status, data } = await bffPost("/org/policy", await req.json());
  return NextResponse.json(data, { status });
}
