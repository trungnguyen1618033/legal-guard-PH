import { BASE, authHeaders } from "@/lib/api";

// Helper dùng chung cho route handler BFF: gọi API ECS (key kín) + truyền nguyên status.
export async function bffPost(path: string, body: unknown) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: authHeaders({ "content-type": "application/json" }),
    body: JSON.stringify(body),
    cache: "no-store",
  });
  const data = await res.json().catch(() => ({}));
  return { status: res.status, data };
}

export async function bffGet(path: string) {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders(), cache: "no-store" });
  const data = await res.json().catch(() => ({}));
  return { status: res.status, data };
}

export async function bffDelete(path: string) {
  const res = await fetch(`${BASE}${path}`, {
    method: "DELETE", headers: authHeaders(), cache: "no-store",
  });
  const data = await res.json().catch(() => ({}));
  return { status: res.status, data };
}
