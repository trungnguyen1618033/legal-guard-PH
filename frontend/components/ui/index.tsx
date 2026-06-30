// Primitives dùng chung cho mọi trang — 1 nguồn cho card/section/badge/note/disclaimer/page shell.
// KHÔNG "use client" → dùng được ở cả server lẫn client component (không hook, không handler).
import { Link } from "@/i18n/routing";

export function Card({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return <div className={`rounded-md border border-line bg-surface p-4 ${className}`}>{children}</div>;
}

export function Section({ title, className = "", children }: {
  title: string; className?: string; children: React.ReactNode;
}) {
  return (
    <section className={className}>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-[0.12em] text-muted">{title}</h2>
      {children}
    </section>
  );
}

const BADGE: Record<string, string> = {
  neutral: "border-line text-muted",
  danger: "border-red-300 bg-red-100 text-red-800",
  warn: "border-amber-200 bg-amber-50 text-amber-700",
  ok: "border-green-200 bg-green-50 text-green-700",
  high: "border-red-200 bg-red-50 text-red-700",
  medium: "border-amber-200 bg-amber-50 text-amber-700",
  low: "border-slate-200 bg-slate-50 text-slate-600",
};

export function Badge({ variant = "neutral", className = "", children }: {
  variant?: string; className?: string; children: React.ReactNode;
}) {
  return (
    <span className={`rounded border px-2 py-0.5 text-xs font-medium ${BADGE[variant] ?? BADGE.neutral} ${className}`}>
      {children}
    </span>
  );
}

export function Note({ variant = "info", className = "", children }: {
  variant?: "info" | "error"; className?: string; children: React.ReactNode;
}) {
  const v = variant === "error" ? "border-red-200 bg-red-50 text-red-700" : "border-line bg-surface text-muted";
  return <p className={`rounded-md border p-4 text-sm ${v} ${className}`}>{children}</p>;
}

export function Disclaimer({ children }: { children: React.ReactNode }) {
  return <p className="mt-2 border-t border-line pt-6 text-sm italic text-muted">{children}</p>;
}

// Khung trang chuẩn: back link → tiêu đề → lede → nội dung. Dùng cho /trust, /lookup, /app, /dashboard.
export function PageShell({ back, title, lede, children }: {
  back?: string; title: string; lede?: string; children: React.ReactNode;
}) {
  return (
    <main className="mx-auto max-w-reading px-6 py-16">
      {back && <Link href="/" className="text-sm no-underline hover:underline">{back}</Link>}
      <h1 className="mt-3 text-4xl font-semibold tracking-tight">{title}</h1>
      {lede && <p className="mt-3 max-w-[60ch] text-muted">{lede}</p>}
      <div className="mt-8">{children}</div>
    </main>
  );
}
