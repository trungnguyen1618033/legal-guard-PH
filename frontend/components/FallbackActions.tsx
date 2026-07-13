"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { FallbackDTO } from "@/lib/api";

const RESULTS = ["accepted", "partial", "rejected"] as const;

// Ghi KẾT QUẢ đàm phán thực tế cho fallback → nuôi win-rate (flywheel). Soạn điều khoản sửa nay là
// nút "Đồng ý sửa" ở mỗi rủi ro (đồng bộ web/app.html — dùng nguyên văn evidence trích HĐ).
export default function FallbackActions({ f, caseId }: { f: FallbackDTO; caseId: string }) {
  const t = useTranslations("app");
  const [outcome, setOutcome] = useState<string | null>(null);

  async function recordOutcome(result: string) {
    if (!caseId) return;
    setOutcome(result);
    try {
      await fetch(`/api/cases/${caseId}/outcome`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ clause: f.clause, tactic: f.suggestion, result }),
      });
    } catch {
      /* không chặn UX */
    }
  }

  if (!caseId) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-1 border-t border-line pt-3">
      <span className="text-xs text-muted">{t("outcome")}:</span>
      {RESULTS.map((r) => (
        <button key={r} onClick={() => recordOutcome(r)}
          className={`rounded-full border px-2 py-0.5 text-xs ${
            outcome === r ? "border-accent-d bg-tint text-ink" : "border-line text-muted hover:text-ink"}`}>
          {t(`oc_${r}`)}
        </button>
      ))}
    </div>
  );
}
