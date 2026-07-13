"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import type { ObligationDTO, OrgPolicyDTO, PortfolioRow } from "@/lib/api";
import { Section, Card, Badge, Note } from "@/components/ui";
import { Button } from "@/components/ui/Button";

// Sau-ký (A/B/C) trên dashboard: danh mục HĐ (portfolio) · nghĩa vụ sắp đến hạn · playbook công ty.
// Dùng CHUNG endpoint với web/Slack — chỉ khác lớp trình bày (hexagonal: domain/service không lặp).
export default function PortfolioPlaybook() {
  const t = useTranslations("dashboard");
  const [portfolio, setPortfolio] = useState<PortfolioRow[]>([]);
  const [obligations, setObligations] = useState<ObligationDTO[]>([]);
  const [policies, setPolicies] = useState<OrgPolicyDTO[]>([]);
  const [text, setText] = useState("");
  const [err, setErr] = useState(false);

  async function loadPolicies() {
    const r = await fetch("/api/org/policy");
    if (r.ok) setPolicies((await r.json()).policies ?? []);
    else setErr(true);
  }

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [p, o] = await Promise.all([fetch("/api/portfolio"), fetch("/api/obligations?within=30")]);
        if (!alive) return;
        if (p.ok) setPortfolio((await p.json()).portfolio ?? []); else setErr(true);
        if (o.ok) setObligations((await o.json()).obligations ?? []); else setErr(true);
        if (alive) await loadPolicies();
      } catch {
        if (alive) setErr(true);        // backend down → báo lỗi, KHÔNG hiện "chưa có dữ liệu" gây hiểu nhầm
      }
    })();
    return () => { alive = false; };
  }, []);

  async function addPolicy() {
    const rule = text.trim();
    if (!rule) return;
    const r = await fetch("/api/org/policy", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ rule_text: rule }),
    });
    if (r.ok) { setText(""); loadPolicies(); }
  }

  async function delPolicy(id: string) {
    const r = await fetch(`/api/org/policy/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (r.ok) loadPolicies();
  }

  async function setObligationStatus(id: string, status: string) {
    const r = await fetch(`/api/obligations/${encodeURIComponent(id)}/status`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (r.ok) setObligations((prev) => prev.filter((o) => o.id !== id));   // ẩn khỏi list sắp-đến-hạn
  }

  return (
    <div className="flex flex-col gap-8">
      {err && <Note variant="error">{t("error")}</Note>}
      <Section title={t("portfolioTitle")}>
        {portfolio.length === 0 ? <Note>{t("portfolioEmpty")}</Note> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-muted">
                <th className="py-1 pr-3">{t("contract")}</th><th className="px-2">{t("mustFix")}</th>
                <th className="px-2">{t("illegal")}</th><th className="px-2">{t("nextDue")}</th>
              </tr></thead>
              <tbody>
                {portfolio.map((p) => (
                  <tr key={p.case_id} className="border-t border-line">
                    <td className="py-1.5 pr-3">{p.title}{p.needs_review && <Badge variant="warn" className="ml-2">{t("needsReviewTag")}</Badge>}</td>
                    <td className="px-2 text-center tabular-nums">{p.must_fix}</td>
                    <td className="px-2 text-center tabular-nums">{p.illegal}</td>
                    <td className="px-2">{p.next_due ? `${p.next_due}${p.days_to_due != null ? ` (${p.days_to_due}d)` : ""}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title={t("obligationsTitle")}>
        {obligations.length === 0 ? <Note>{t("obligationsEmpty")}</Note> : (
          <ul className="space-y-2">
            {obligations.map((o) => (
              <li key={o.id}>
                <Card className="flex flex-wrap items-center gap-2 text-sm">
                  <Badge variant="warn">{o.due_date || "?"}</Badge>
                  <span className="flex-1">{o.description}</span>
                  {o.consequence && <span className="text-xs text-muted">— {o.consequence}</span>}
                  <button onClick={() => setObligationStatus(o.id, "done")}
                    className="text-xs text-accent-d hover:underline">{t("oblDone")}</button>
                  <button onClick={() => setObligationStatus(o.id, "dismissed")}
                    className="text-xs text-muted hover:underline">{t("oblDismiss")}</button>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={t("playbookTitle")}>
        <div className="flex gap-2">
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder={t("policyPlaceholder")}
            className="flex-1 rounded-md border border-line bg-surface px-3 py-1.5 text-sm outline-none focus:border-accent-d" />
          <Button onClick={addPolicy} className="px-4 py-1.5">{t("add")}</Button>
        </div>
        {policies.length === 0 ? <Note className="mt-3">{t("playbookEmpty")}</Note> : (
          <ul className="mt-3 space-y-2">
            {policies.map((p) => (
              <li key={p.id}>
                <Card className="flex items-center justify-between gap-3 text-sm">
                  <span>{p.rule_text}</span>
                  <button onClick={() => delPolicy(p.id)} className="text-xs text-red-600 hover:underline">{t("delete")}</button>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
