import { NextRequest, NextResponse } from "next/server";
import { bffDelete } from "@/lib/bff";

// BFF: DELETE /api/org/policy/{id} → xóa 1 quy tắc playbook (org-scoped).
export async function DELETE(_req: NextRequest, { params }: { params: { id: string } }) {
  const { status, data } = await bffDelete(`/org/policy/${encodeURIComponent(params.id)}`);
  return NextResponse.json(data, { status });
}
