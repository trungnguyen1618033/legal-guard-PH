import { NextRequest, NextResponse } from "next/server";
import { askLegal } from "@/lib/api";

// BFF: browser POST /api/ask → server proxy tới /ask trên ECS + giữ key kín.
export async function POST(req: NextRequest) {
  let body: { question?: string; lang?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Body JSON không hợp lệ." }, { status: 400 });
  }
  const question = (body.question ?? "").trim();
  const lang = body.lang === "en" ? "en" : "vi";
  if (!question) {
    return NextResponse.json({ error: "Cần nhập câu hỏi." }, { status: 400 });
  }
  try {
    return NextResponse.json(await askLegal(question, lang));
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 502 });
  }
}
