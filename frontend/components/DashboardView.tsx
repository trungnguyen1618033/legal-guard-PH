"use client";

import { useEffect, useState } from "react";
import type { DashboardDTO } from "@/lib/api";
import { Section, Card, Badge, Note } from "@/components/ui";

export type DashboardLabels = {
  error: string; empty: string;
  cases: string; needsReview: string; totalRisks: string; kbGaps: string;
  severity: string; high: string; medium: string; low: string;
  topClauses: string; feedback: string; noFeedback: string; topTactics: string;
};

const BAR: Record<string, string> = { high: "bg-red-400", medium: "bg-amber-400", low: "bg-slate-400" };
const FB: Record<string, string> = { helpful: "ok", wrong: "danger", incomplete: "warn" };

export default function DashboardView({ labels: L }: { labels: DashboardLabels }) {
  const [d, setD] = useState<DashboardDTO | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    let alive = true;
    fetch("/api/dashboard")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((data) => alive && setD(data))
      .catch(() => alive && setErr(true));
    return () => {
      alive = false;
    };
  }, []);

  if (err) return <Note variant="error">{L.error}</Note>;
  if (!d) return <DashboardSkeleton />;
  if (d.cases.total === 0) return <Note>{L.empty}</Note>;

  const sev = d.cases.risk_by_severity || {};
  const sevMax = Math.max(1, ...Object.values(sev));
  const order = ["high", "medium", "low"].filter((k) => sev[k]);
  const sevLabel: Record<string, string> = { high: L.high, medium: L.medium, low: L.low };

  return (
    <div className="flex flex-col gap-8">
      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label={L.cases} value={d.cases.total} />
        <Stat label={L.needsReview} value={d.cases.needs_review} />
        <Stat label={L.totalRisks} value={d.cases.total_risks} />
        <Stat label={L.kbGaps} value={d.feedback.kb_gaps} />
      </div>

      {order.length > 0 && (
        <Section title={L.severity}>
          <Card>
            <div className="flex flex-col gap-2">
              {order.map((k) => (
                <div key={k} className="flex items-center gap-3">
                  <span className="w-20 text-sm text-muted">{sevLabel[k]}</span>
                  <div className="h-3 flex-1 rounded bg-paper">
                    <div className={`h-3 rounded ${BAR[k]}`} style={{ width: `${(sev[k] / sevMax) * 100}%` }} />
                  </div>
                  <span className="w-8 text-right text-sm tabular-nums">{sev[k]}</span>
                </div>
              ))}
            </div>
          </Card>
        </Section>
      )}

      {d.top_risky_clauses.length > 0 && (
        <Section title={L.topClauses}>
          <ul className="space-y-2">
            {d.top_risky_clauses.map((c, i) => (
              <li key={i}>
                <Card className="flex items-center justify-between gap-3">
                  <span className="text-sm">{c.clause}</span>
                  <Badge>{c.count}×</Badge>
                </Card>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title={L.feedback}>
        <div className="flex flex-wrap gap-2">
          {Object.entries(d.feedback.by_rating).map(([k, v]) => (
            <Badge key={k} variant={FB[k] ?? "neutral"}>{k}: {v}</Badge>
          ))}
          {d.feedback.total === 0 && <span className="text-sm text-muted">{L.noFeedback}</span>}
        </div>
      </Section>

      {d.top_tactics.length > 0 && (
        <Section title={L.topTactics}>
          <ul className="space-y-2">
            {d.top_tactics.map((tt, i) => (
              <li key={i}>
                <Card className="flex items-center justify-between gap-3">
                  <span className="text-sm">{tt.clause}</span>
                  <span className="flex items-center gap-2">
                    <Badge variant="ok">{Math.round(tt.win_rate * 100)}%</Badge>
                    <span className="text-xs text-muted">n={tt.samples}</span>
                  </span>
                </Card>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <div className="text-3xl font-semibold tabular-nums text-accent-d">{value}</div>
      <div className="mt-1 text-sm text-muted">{label}</div>
    </Card>
  );
}

function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-8">
      <div className="grid gap-3 sm:grid-cols-4">
        {[0, 1, 2, 3].map((i) => <div key={i} className="h-20 animate-pulse rounded-md bg-line" />)}
      </div>
      <div className="h-32 animate-pulse rounded-md bg-line" />
    </div>
  );
}
