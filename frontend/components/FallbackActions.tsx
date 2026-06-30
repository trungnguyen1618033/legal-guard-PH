"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { FallbackDTO, RiskDTO } from "@/lib/api";
import { Card } from "@/components/ui";
import { Button } from "@/components/ui/Button";

type Counter = { vi: string; en: string; rationale: string; grounded: boolean };
const RESULTS = ["accepted", "partial", "rejected"] as const;

// Hành động trên mỗi fallback: soạn điều khoản phản-đề (/counter) + ghi kết quả đàm phán (outcome).
export default function FallbackActions({ f, risk, caseId, leverage }: {
  f: FallbackDTO; risk?: RiskDTO; caseId: string; leverage: string;
}) {
  const t = useTranslations("app");
  const [counter, setCounter] = useState<Counter | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);

  async function draftCounter() {
    if (busy) return;
    setBusy(true);
    try {
      const res = await fetch("/api/counter", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          clause: f.clause, risk: risk?.risk ?? "", suggestion: f.suggestion,
          legal_basis: f.legal_basis ?? risk?.legal_basis ?? "", leverage,
        }),
      });
      if (res.ok) setCounter(await res.json());
    } finally {
      setBusy(false);
    }
  }

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

  return (
    <div className="mt-3 border-t border-line pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" onClick={draftCounter} disabled={busy} className="px-3 py-1.5 text-xs">
          {busy ? t("counterBusy") : `📝 ${t("counter")}`}
        </Button>
        {caseId && (
          <span className="flex items-center gap-1">
            <span className="text-xs text-muted">{t("outcome")}:</span>
            {RESULTS.map((r) => (
              <button key={r} onClick={() => recordOutcome(r)}
                className={`rounded-full border px-2 py-0.5 text-xs ${
                  outcome === r ? "border-accent-d bg-tint text-ink" : "border-line text-muted hover:text-ink"}`}>
                {t(`oc_${r}`)}
              </button>
            ))}
          </span>
        )}
      </div>

      {counter && (
        <Card className="mt-3 bg-paper text-sm">
          {!counter.grounded && <p className="mb-1 text-xs italic text-amber-700">⚠️ {t("counterDraft")}</p>}
          <p><strong>🇻🇳</strong> {counter.vi}</p>
          {counter.en && <p className="mt-1"><strong>🇬🇧</strong> {counter.en}</p>}
          {counter.rationale && <p className="mt-1 text-xs text-muted">{counter.rationale}</p>}
        </Card>
      )}
    </div>
  );
}
