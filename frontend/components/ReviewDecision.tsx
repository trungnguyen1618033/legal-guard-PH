"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { RiskDTO, FallbackDTO } from "@/lib/api";

// Quyết định rà soát (đồng bộ Slack "Chốt / Sửa lại"): GỘP feedback + kết quả đàm phán thành 2 nút.
//   Chốt   → feedback=helpful + outcome=accepted cho MỌI điều khoản (win-rate flywheel)
//   Sửa lại → feedback=wrong  + outcome=rejected cho mọi điều khoản
export default function ReviewDecision(
  { caseId, risks, fallbacks }: { caseId: string; risks: RiskDTO[]; fallbacks: FallbackDTO[] },
) {
  const t = useTranslations("app");
  const [done, setDone] = useState<"close" | "revise" | null>(null);

  async function decide(kind: "close" | "revise") {
    if (done) return;
    setDone(kind);
    const rating = kind === "close" ? "helpful" : "wrong";
    const result = kind === "close" ? "accepted" : "rejected";
    try {
      await fetch("/api/feedback", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ kind: "analysis", ref: caseId, rating }),
      });
      // outcome cho MỌI điều khoản (risk ∪ fallback) → nuôi win-rate như Slack _record_deal_outcome
      const clauses = [...new Set(
        [...risks.map((r) => r.clause), ...fallbacks.map((f) => f.clause)].filter(Boolean),
      )];
      await Promise.all(clauses.map((clause) => {
        const f = fallbacks.find((x) => x.clause === clause);
        return fetch(`/api/cases/${caseId}/outcome`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ clause, tactic: f?.suggestion ?? "", result }),
        });
      }));
    } catch {
      /* không chặn UX */
    }
  }

  if (done) {
    return <p className="text-xs text-muted">{done === "close" ? t("reviewClosed") : t("reviewRevised")}</p>;
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
      <span>{t("reviewPrompt")}</span>
      <button onClick={() => decide("close")}
        className="rounded-full border border-emerald-500 px-3 py-1 font-medium text-emerald-700 hover:bg-emerald-50">
        {t("reviewClose")}
      </button>
      <button onClick={() => decide("revise")}
        className="rounded-full border border-red-400 px-3 py-1 font-medium text-red-700 hover:bg-red-50">
        {t("reviewRevise")}
      </button>
    </div>
  );
}
