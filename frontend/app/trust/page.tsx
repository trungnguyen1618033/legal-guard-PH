import Link from "next/link";
import { getTrust } from "@/lib/api";

// Server Component: fetch trực tiếp qua lib (server-side) — minh họa pattern data-driven + ISR.
export const revalidate = 300;

export default async function TrustPage() {
  let data;
  try {
    data = await getTrust();
  } catch {
    return (
      <main className="mx-auto max-w-reading px-6 py-16">
        <h1 className="text-3xl font-semibold">Độ tin cậy</h1>
        <p className="mt-4 text-muted">Chưa lấy được số liệu từ máy chủ. Thử lại sau.</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-reading px-6 py-16">
      <Link href="/" className="text-sm no-underline hover:underline">← Trang chủ</Link>
      <h1 className="mt-3 text-4xl font-semibold tracking-tight">Độ tin cậy</h1>
      <p className="mt-3 max-w-[60ch] text-muted">Cách chúng tôi đảm bảo AI không bịa luật — kèm số đo trên bộ kiểm thử nội bộ.</p>

      <section className="mt-10">
        <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-muted">Số đo</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {data.metrics.map((m) => (
            <div key={m.name} className="rounded-md border border-line bg-surface p-4">
              <div className="text-2xl font-semibold text-accent-d">{m.value}</div>
              <div className="mt-1 font-medium">{m.name}</div>
              <div className="mt-1 text-sm text-muted">{m.note}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-10">
        <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-muted">Phương pháp</h2>
        <ul className="mt-3 space-y-3">
          {data.methodology.map((m) => (
            <li key={m.layer} className="rounded-md border border-line bg-surface p-4">
              <strong className="text-accent-d">{m.layer}</strong>
              <p className="mt-1 text-sm text-muted">{m.desc}</p>
            </li>
          ))}
        </ul>
      </section>

      <p className="mt-10 border-t border-line pt-6 text-sm italic text-muted">{data.disclaimer}</p>
    </main>
  );
}
