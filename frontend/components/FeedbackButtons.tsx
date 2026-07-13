"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

// Nút phản hồi (đúng / chưa đúng / còn thiếu) → /api/feedback (nuôi flywheel + golden set). Dùng ở /app và /lookup.
export default function FeedbackButtons({ kind, refValue }: { kind: "analysis" | "lookup"; refValue: string }) {
  const t = useTranslations("fb");
  const [sent, setSent] = useState(false);

  async function send(rating: string) {
    if (sent) return;
    setSent(true);
    try {
      await fetch("/api/feedback", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ kind, ref: refValue, rating }),
      });
    } catch {
      /* phản hồi không chặn UX — nuốt lỗi */
    }
  }

  if (sent) return <p className="text-xs text-muted">{t("thanks")}</p>;

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
      <span>{t("prompt")}</span>
      {(["helpful", "wrong", "incomplete"] as const).map((r) => (
        <button key={r} onClick={() => send(r)}
          className="rounded-full border border-line px-2.5 py-1 hover:border-accent-d hover:text-ink">
          {t(r)}
        </button>
      ))}
    </div>
  );
}
