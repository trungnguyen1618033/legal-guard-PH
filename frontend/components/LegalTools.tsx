"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import type {
  GraphDTO, LatestDTO, ChangelogDTO, ImpactDTO, MonitorDTO, ChangelogItem, GraphEdge, ImpactItem,
} from "@/lib/api";
import { Card, Section, Badge, Note } from "@/components/ui";
import { Button } from "@/components/ui/Button";

const REL: Record<string, { vi: string; en: string }> = {
  amends: { vi: "sửa đổi", en: "amends" },
  amended_by: { vi: "được sửa đổi bởi", en: "amended by" },
  replaces: { vi: "thay thế", en: "replaces" },
  replaced_by: { vi: "được thay thế bởi", en: "replaced by" },
  guides: { vi: "hướng dẫn", en: "guides" },
  guided_by: { vi: "được hướng dẫn bởi", en: "guided by" },
};
const STATUS_VARIANT: Record<string, string> = { in_force: "ok", expired: "danger", draft: "warn" };

// Công cụ pháp lý nâng cao trên /lookup: Autopilot quét luật mới · lược đồ+lịch sử văn bản · tác động · redline.
export default function LegalTools() {
  const t = useTranslations("tools");
  const locale = useLocale();
  const rel = (r: string) => REL[r]?.[locale === "en" ? "en" : "vi"] ?? r;

  return (
    <div className="mt-12 flex flex-col gap-8 border-t border-line pt-8">
      <h2 className="text-lg font-semibold">{t("heading")}</h2>
      <Monitor t={t} />
      <DocLens t={t} rel={rel} />
      <Impact t={t} rel={rel} />
      <Redline t={t} />
    </div>
  );
}

type T = ReturnType<typeof useTranslations>;

function Monitor({ t }: { t: T }) {
  const [since, setSince] = useState("");
  const [res, setRes] = useState<MonitorDTO | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    if (!since || busy) return;
    setBusy(true);
    setRes(null);
    try {
      const r = await fetch("/api/monitor", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ since }),
      });
      if (r.ok) setRes(await r.json());
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title={`🤖 ${t("monitorTitle")}`}>
      <p className="mb-3 text-sm text-muted">{t("monitorLede")}</p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-sm">
          <span className="mb-1 block text-muted">{t("since")}</span>
          <input type="date" value={since} onChange={(e) => setSince(e.target.value)}
            className="rounded-md border border-line bg-surface px-3 py-1.5 outline-none focus:border-accent-d" />
        </label>
        <Button onClick={run} disabled={busy || !since}>{busy ? t("scanning") : t("scan")}</Button>
      </div>
      {res && (
        <div className="mt-3">
          <p className="text-sm text-muted">{t("scanned", { n: res.new_laws_scanned })}</p>
          {res.affected.length === 0 ? (
            <Note className="mt-2">{t("noImpact")}</Note>
          ) : (
            <ul className="mt-2 space-y-2">
              {res.affected.map((a, i) => (
                <li key={i}>
                  <Card>
                    <strong>{a.title || a.doc_id}</strong>
                    {a.effective_date && <span className="ml-2 text-xs text-muted">({t("effective")} {a.effective_date})</span>}
                    <p className="mt-1 text-sm text-muted">
                      {t("affectedCases", { n: Array.isArray(a.cases) ? a.cases.length : Number(a.cases) || 0 })}
                    </p>
                    {Array.isArray(a.cases) && a.cases.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {a.cases.map((cid) => <DismissCase key={cid} t={t} docId={a.doc_id} caseId={cid} />)}
                      </div>
                    )}
                  </Card>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Section>
  );
}

// Vòng phản hồi Autopilot (#3): chip case + nút "báo nhầm" → /api/monitor-feedback → digest sau tự lọc.
function DismissCase({ t, docId, caseId }: { t: T; docId: string; caseId: string }) {
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function dismiss() {
    if (busy || done) return;
    setBusy(true);
    try {
      const r = await fetch("/api/monitor-feedback", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ doc_id: docId, case_id: caseId }),
      });
      if (r.ok) setDone(true);
    } finally {
      setBusy(false);
    }
  }

  if (done) return <Badge variant="ok">{caseId} · {t("dismissed")}</Badge>;
  return (
    <span className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-xs">
      {caseId}
      <button onClick={dismiss} disabled={busy} className="text-muted hover:text-red-600" title={t("falseAlarm")}>
        ✕ {t("falseAlarm")}
      </button>
    </span>
  );
}

function DocLens({ t, rel }: { t: T; rel: (r: string) => string }) {
  const [doc, setDoc] = useState("");
  type Lens = {
    graph?: GraphDTO | null; latest?: LatestDTO | null;
    articles?: Record<string, { doc_id: string; effective_date?: string }[]>;
    changes?: ChangelogDTO | null; notFound?: boolean;
  };
  const [data, setData] = useState<Lens | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    const id = doc.trim();
    if (!id || busy) return;
    setBusy(true);
    setData(null);
    const q = `?doc=${encodeURIComponent(id)}`;
    const [g, l, a, c] = await Promise.all([
      fetch(`/api/graph${q}`), fetch(`/api/latest${q}`), fetch(`/api/articles-changed${q}`), fetch(`/api/changes${q}`),
    ]);
    if (g.status === 404) {
      setData({ notFound: true });
      setBusy(false);
      return;
    }
    setData({
      graph: g.ok ? await g.json() : null,
      latest: l.ok ? await l.json() : null,
      articles: a.ok ? (await a.json()).amended_articles ?? {} : {},
      changes: c.ok ? await c.json() : null,
    });
    setBusy(false);
  }

  return (
    <Section title={`🗺️ ${t("lensTitle")}`}>
      <p className="mb-3 text-sm text-muted">{t("lensLede")}</p>
      <div className="flex flex-wrap items-end gap-2">
        <input value={doc} onChange={(e) => setDoc(e.target.value)} placeholder="123/2020/NĐ-CP"
          className="rounded-md border border-line bg-surface px-3 py-1.5 text-sm outline-none focus:border-accent-d" />
        <Button onClick={load} disabled={busy || !doc.trim()}>{busy ? t("loading") : t("view")}</Button>
      </div>
      {data?.notFound && <Note className="mt-3">{t("notFound")}</Note>}
      {data && !data.notFound && (
        <div className="mt-3 flex flex-col gap-3">
          {data.latest?.doc_id && (
            <Card>
              <span className="text-xs uppercase tracking-wide text-muted">{t("latest")}</span>
              <p className="mt-1 text-sm"><strong>{data.latest.title || data.latest.doc_id}</strong>
                {data.latest.effective_date && <span className="ml-2 text-xs text-muted">({t("effective")} {data.latest.effective_date})</span>}</p>
            </Card>
          )}
          {data.changes && (
            <Card>
              <p className="text-sm"><strong>{data.changes.title || data.changes.doc_id}</strong>
                {data.changes.status && <Badge variant={STATUS_VARIANT[data.changes.status] ?? "neutral"} className="ml-2">{data.changes.status}</Badge>}</p>
              {(data.changes.items ?? []).length > 0 && (
                <ul className="mt-2 space-y-1 text-sm">
                  {data.changes.items.map((x: ChangelogItem, i: number) => (
                    <li key={i}><strong>{rel(x.relation)}</strong>: {x.doc_id}
                      {x.effective_date && <span className="text-xs text-muted"> ({t("effective")} {x.effective_date})</span>}</li>
                  ))}
                </ul>
              )}
            </Card>
          )}
          {data.graph && data.graph.edges.length > 0 && (
            <Card>
              <span className="text-xs uppercase tracking-wide text-muted">{t("graph", { n: data.graph.edges.length })}</span>
              <div className="mt-2 flex flex-col gap-1 text-sm">
                {data.graph.edges.map((e: GraphEdge, i: number) => (
                  <div key={i}>{e.from} <strong className="text-accent-d">{rel(e.relation)}</strong> {e.to}</div>
                ))}
              </div>
            </Card>
          )}
          {data.articles && Object.keys(data.articles).length > 0 && (
            <Card>
              <span className="text-xs uppercase tracking-wide text-muted">{t("amended")}</span>
              <ul className="mt-2 space-y-1 text-sm">
                {Object.entries(data.articles).map(([art, by], i) => (
                  <li key={i}><strong>{art}</strong>: {(by ?? []).map((b) => b.doc_id).join(", ")}</li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}
    </Section>
  );
}

function Impact({ t, rel }: { t: T; rel: (r: string) => string }) {
  const [doc, setDoc] = useState("");
  const [res, setRes] = useState<ImpactDTO | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    const id = doc.trim();
    if (!id || busy) return;
    setBusy(true);
    setRes(null);
    try {
      const r = await fetch(`/api/impact?doc=${encodeURIComponent(id)}`);
      if (r.ok) setRes(await r.json());
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title={`🛎️ ${t("impactTitle")}`}>
      <p className="mb-3 text-sm text-muted">{t("impactLede")}</p>
      <div className="flex flex-wrap items-end gap-2">
        <input value={doc} onChange={(e) => setDoc(e.target.value)} placeholder="70/2025/NĐ-CP"
          className="rounded-md border border-line bg-surface px-3 py-1.5 text-sm outline-none focus:border-accent-d" />
        <Button onClick={load} disabled={busy || !doc.trim()}>{busy ? t("loading") : t("check")}</Button>
      </div>
      {res && (
        <div className="mt-3">
          {!res.impacted_cases ? (
            <Note className="mt-2">{t("noImpactDoc")}</Note>
          ) : (
            <>
              <Note variant="error" className="mt-2">{t("impacted", { n: res.impacted_cases, doc: res.doc_id })}</Note>
              <ul className="mt-2 space-y-1 text-sm">
                {(res.items ?? []).map((x: ImpactItem, i: number) => (
                  <li key={i}>
                    <strong>{x.clause}</strong>{" "}
                    <span className="text-xs text-muted">
                      ({x.kind === "risk" ? t("kindRisk") : t("kindFallback")}, {rel(x.relation)} {x.affected_file}{x.affected_article ? ` ${x.affected_article}` : ""})
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </Section>
  );
}

function Redline({ t }: { t: T }) {
  const [oldT, setOldT] = useState("");
  const [newT, setNewT] = useState("");
  const [res, setRes] = useState<{ redline: string; similarity: number } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    if (!oldT.trim() || !newT.trim() || busy) return;
    setBusy(true);
    setRes(null);
    try {
      const r = await fetch("/api/redline", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ old: oldT, new: newT }),
      });
      if (r.ok) setRes(await r.json());
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title={`📝 ${t("redlineTitle")}`}>
      <p className="mb-3 text-sm text-muted">{t("redlineLede")}</p>
      <div className="grid gap-2 sm:grid-cols-2">
        <textarea value={oldT} onChange={(e) => setOldT(e.target.value)} rows={4} placeholder={t("oldVersion")}
          className="w-full resize-y rounded-md border border-line bg-surface p-3 text-sm outline-none focus:border-accent-d" />
        <textarea value={newT} onChange={(e) => setNewT(e.target.value)} rows={4} placeholder={t("newVersion")}
          className="w-full resize-y rounded-md border border-line bg-surface p-3 text-sm outline-none focus:border-accent-d" />
      </div>
      <Button onClick={run} disabled={busy || !oldT.trim() || !newT.trim()} className="mt-2">
        {busy ? t("comparing") : t("compare")}
      </Button>
      {res && (
        <Card className="mt-3">
          <p className="text-sm text-muted">{t("similarity", { pct: Math.round(res.similarity * 100) })}</p>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-sm leading-relaxed">{res.redline}</pre>
        </Card>
      )}
    </Section>
  );
}
