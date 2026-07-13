"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import type { ImpactDTO, MonitorDTO, ImpactItem, InForceDTO } from "@/lib/api";
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
// Công cụ pháp lý nâng cao trên /lookup: Autopilot quét luật mới · kiểm tra hiệu lực VB · tác động · redline.
export default function LegalTools() {
  const t = useTranslations("tools");
  const locale = useLocale();
  const rel = (r: string) => REL[r]?.[locale === "en" ? "en" : "vi"] ?? r;

  return (
    <div className="mt-12 flex flex-col gap-8 border-t border-line pt-8">
      <h2 className="text-lg font-semibold">{t("heading")}</h2>
      <Monitor t={t} />
      <InForce t={t} />
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
    <Section title={t("monitorTitle")}>
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

// VB còn hiệu lực pháp luật không (thay "lược đồ" cũ — đồng bộ web/lookup.html checkInForce).
function InForce({ t }: { t: T }) {
  const [doc, setDoc] = useState("");
  const [data, setData] = useState<InForceDTO | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [busy, setBusy] = useState(false);

  async function load() {
    const id = doc.trim();
    if (!id || busy) return;
    setBusy(true);
    setData(null);
    setNotFound(false);
    try {
      const r = await fetch(`/api/in-force?doc=${encodeURIComponent(id)}`);
      if (r.status === 404) { setNotFound(true); return; }
      if (r.ok) setData(await r.json());
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title={t("inForceTitle")}>
      <p className="mb-3 text-sm text-muted">{t("inForceLede")}</p>
      <div className="flex flex-wrap items-end gap-2">
        <input value={doc} onChange={(e) => setDoc(e.target.value)} placeholder="13/2023/NĐ-CP"
          className="rounded-md border border-line bg-surface px-3 py-1.5 text-sm outline-none focus:border-accent-d" />
        <Button onClick={load} disabled={busy || !doc.trim()}>{busy ? t("loading") : t("check")}</Button>
      </div>
      {notFound && <Note className="mt-3">{t("notFound")}</Note>}
      {data && (
        <Card className="mt-3">
          <p className="text-sm">
            <strong>{data.title || data.doc_id}</strong>{" "}
            <Badge variant={data.in_force ? "ok" : "danger"}>{data.in_force ? t("inForceYes") : t("inForceNo")}</Badge>
          </p>
          <p className="mt-2 text-sm">{data.reason}</p>
          {data.effective_date && <p className="mt-1 text-xs text-muted">{t("effective")}: {data.effective_date}</p>}
          {data.replaced && data.latest && (
            <Note variant="error" className="mt-2">
              {t("currentDoc")}: <strong>{data.latest}</strong>{data.latest_title ? ` — ${data.latest_title}` : ""}
            </Note>
          )}
          {(data.amended_by ?? []).length > 0 && (
            <p className="mt-2 text-xs text-muted">
              {t("amendedByLabel")}: {data.amended_by!.map((a) => a.doc_id + (a.title ? ` (${a.title})` : "")).join(", ")}
            </p>
          )}
        </Card>
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
    <Section title={t("impactTitle")}>
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
    <Section title={t("redlineTitle")}>
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
