"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Card, Section, Badge } from "@/components/ui";
import { Button } from "@/components/ui/Button";

type Round = {
  assessment: string; strategy: string; reply_vi: string; reply_en: string;
  status: "continue" | "close" | "walk_away" | string; grounded: boolean;
  partner: string;
};
type Pos = { leverage: string; urgency: string; relationship: string; alternatives: boolean; protected_party: string };

const STATUS: Record<string, string> = { continue: "neutral", close: "ok", walk_away: "danger" };

// Đàm phán đa phiên: dán phản hồi đối tác → vòng mới, NỐI bối cảnh qua các vòng (deal context tích lũy).
export default function NegotiationPanel({ dealContext, position }: { dealContext: string; position: Pos }) {
  const t = useTranslations("nego");
  const locale = useLocale();
  const [rounds, setRounds] = useState<Round[]>([]);
  const [partner, setPartner] = useState("");
  const [busy, setBusy] = useState(false);

  // Bối cảnh nối: bối cảnh gốc + các vòng đã diễn ra (giống web/app.html _deal).
  function buildContext(): string {
    const prior = rounds.map((r, i) =>
      `--- Vòng ${i + 1} ---\nĐối tác: ${r.partner}\nĐánh giá: ${r.assessment}\nChiến lược: ${r.strategy}`).join("\n\n");
    return prior ? `${dealContext}\n\n${prior}` : dealContext;
  }

  async function go() {
    const msg = partner.trim();
    if (!msg || busy) return;
    setBusy(true);
    try {
      const res = await fetch("/api/negotiate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          deal_context: buildContext(), partner_message: msg, lang: locale === "en" ? "en" : "vi",
          leverage: position.leverage, urgency: position.urgency, relationship: position.relationship,
          alternatives: position.alternatives, protected_party: position.protected_party,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setRounds((rs) => [...rs, { ...data, partner: msg }]);
        setPartner("");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title={`💬 ${t("title")}`}>
      <p className="mb-3 text-sm text-muted">{t("lede")}</p>

      <div className="flex flex-col gap-3">
        {rounds.map((r, i) => (
          <Card key={i}>
            <div className="flex items-center gap-2">
              <Badge variant="neutral">{t("round")} {i + 1}</Badge>
              <Badge variant={STATUS[r.status] ?? "neutral"}>{t(`st_${r.status}`)}</Badge>
              {!r.grounded && <span className="text-xs italic text-amber-700">{t("draft")}</span>}
            </div>
            <p className="mt-2 text-sm"><span className="text-muted">{t("partner")}:</span> {r.partner}</p>
            {r.assessment && <p className="mt-2 text-sm"><strong>{t("assessment")}:</strong> {r.assessment}</p>}
            {r.strategy && <p className="mt-1 text-sm"><strong>{t("strategy")}:</strong> {r.strategy}</p>}
            {r.reply_vi && <div className="mt-2 rounded bg-paper p-2 text-sm"><span className="text-muted">VI:</span> {r.reply_vi}</div>}
            {r.reply_en && <div className="mt-1 rounded bg-paper p-2 text-sm"><span className="text-muted">EN:</span> {r.reply_en}</div>}
          </Card>
        ))}
      </div>

      <div className="mt-3 flex flex-col gap-2">
        <textarea value={partner} onChange={(e) => setPartner(e.target.value)} rows={3}
          placeholder={t("placeholder")}
          className="w-full resize-y rounded-md border border-line bg-surface p-3 text-sm outline-none focus:border-accent-d" />
        <Button onClick={go} disabled={busy || !partner.trim()} className="self-start">
          {busy ? t("busy") : rounds.length ? t("next") : t("start")}
        </Button>
      </div>
    </Section>
  );
}
