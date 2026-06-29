import { NextResponse } from "next/server";
import { getTrust } from "@/lib/api";

// BFF: browser gọi /api/trust (cùng-origin) → server proxy tới API ECS + giữ key kín.
// Mẫu cho mọi endpoint cần auth (/analyze, /cases...) — KHÔNG đặt key vào client.
export async function GET() {
  try {
    return NextResponse.json(await getTrust());
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 502 });
  }
}
