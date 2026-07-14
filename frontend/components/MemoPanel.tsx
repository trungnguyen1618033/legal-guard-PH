"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { RiskDTO, FallbackDTO } from "@/lib/api";
import { Section, Card, Note } from "@/components/ui";
import { Button } from "@/components/ui/Button";

// Bản ghi nhớ sửa đổi: gộp risk + fallback (cùng clause) → memo markdown (+ tải Word .docx).
export default function MemoPanel({ risks, fallbacks, protectedParty }: {
  risks: RiskDTO[]; fallbacks: FallbackDTO[]; protectedParty?: string;
}) {
  const t = useTranslations("memo");
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [docxNote, setDocxNote] = useState<string | null>(null);

  function items() {
    return risks.map((r) => {
      const fb = fallbacks.find((f) => f.clause === r.clause);
      return {
        clause: r.clause, issue: r.risk, legal_status: r.legal_status,
        violated_law: r.violated_law ?? "", legal_basis: r.legal_basis ?? fb?.legal_basis ?? "",
        suggestion: fb?.suggestion ?? "", priority: r.priority ?? "",
      };
    });
  }

  // Bản ĐỐI CHIẾU: điều khoản cũ (evidence) → mới (counter_clause vi/en, hoặc suggestion) + căn cứ.
  function redlineItems() {
    return risks.map((r) => {
      const fb = fallbacks.find((f) => f.clause === r.clause);
      const cc = r.counter_clause;
      return {
        clause: r.clause, evidence: r.evidence ?? "",
        vi: cc?.vi ?? fb?.suggestion ?? "", en: cc?.en ?? "",
        rationale: cc?.rationale ?? r.legal_basis ?? "",
        legal_status: r.legal_status, violated_law: r.violated_law ?? "",
      };
    });
  }

  async function compile() {
    if (busy) return;
    setBusy(true);
    setDocxNote(null);
    try {
      const res = await fetch("/api/amendments/compile", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ items: items(), protected_party: protectedParty ?? "" }),
      });
      if (res.ok) setMarkdown((await res.json()).markdown ?? "");
    } finally {
      setBusy(false);
    }
  }

  async function downloadDocx() {
    setDocxNote(null);
    const res = await fetch("/api/amendments/compile-docx", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ items: items(), protected_party: protectedParty ?? "" }),
    });
    if (!res.ok) {
      setDocxNote(t("docxUnavailable")); // 501: thiếu python-docx → dùng markdown
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "ban-ghi-nho-sua-doi.docx";
    a.click();
    URL.revokeObjectURL(url);
  }

  async function downloadRedline() {
    setDocxNote(null);
    const res = await fetch("/api/amendments/redline-docx", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ items: redlineItems(), protected_party: protectedParty ?? "" }),
    });
    if (!res.ok) {
      setDocxNote(t("docxUnavailable"));
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "ban-doi-chieu-sua-doi.docx";
    a.click();
    URL.revokeObjectURL(url);
  }

  if (risks.length === 0) return null;

  return (
    <Section title={t("title")}>
      <p className="mb-3 text-sm text-muted">{t("lede")}</p>
      <div className="flex flex-wrap gap-2">
        <Button onClick={compile} disabled={busy}>{busy ? t("busy") : t("compile")}</Button>
        {markdown && <Button variant="ghost" onClick={downloadDocx}>{t("docx")}</Button>}
        <Button variant="ghost" onClick={downloadRedline}>{t("redline")}</Button>
      </div>
      {docxNote && <Note className="mt-3">{docxNote}</Note>}
      {markdown && (
        <Card className="mt-3 overflow-x-auto">
          <pre className="whitespace-pre-wrap text-xs leading-relaxed">{markdown}</pre>
        </Card>
      )}
    </Section>
  );
}
