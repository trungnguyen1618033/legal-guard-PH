"use client";

import { useRef, useState } from "react";
import { useLocale } from "next-intl";
import type { AnalysisResultDTO, RiskDTO, FallbackDTO } from "@/lib/api";
import { Card, Section, Badge, Note } from "@/components/ui";
import { Button } from "@/components/ui/Button";
import FeedbackButtons from "@/components/FeedbackButtons";
import FallbackActions from "@/components/FallbackActions";
import NegotiationPanel from "@/components/NegotiationPanel";
import MemoPanel from "@/components/MemoPanel";

export type AnalyzeLabels = {
  inputText: string;
  inputFile: string;
  placeholder: string;
  position: string;
  leverage: string;
  leverageOpts: { weak: string; balanced: string; strong: string };
  urgency: string;
  urgencyOpts: { low: string; medium: string; high: string };
  relationship: string;
  relationshipOpts: { new: string; ongoing: string; strategic: string };
  alternatives: string;
  protectedParty: string;
  protectedPartyPh: string;
  submit: string;
  analyzing: string;
  error: string;
  summary: string;
  agentWork: string;
  esCalls: string;
  esSearches: string;
  esRisks: string;
  esFallbacks: string;
  esReview: string;
  strategy: string;
  risks: string;
  fallbacks: string;
  notes: string;
  trace: string;
  legalBasis: string;
  illegal: string;
  unfavorable: string;
  unverified: string;
  reply: string;
  replyLocked: string;
  checkpoint: string;
  checkpointDesc: string;
  approve: string;
  reject: string;
  approved: string;
  rejected: string;
  rejectedSent: string;
  rejectedNotSent: string;
  winRate: string;
  disclaimer: string;
};

export default function AnalyzeFlow({ labels: L }: { labels: AnalyzeLabels }) {
  const locale = useLocale();
  const [mode, setMode] = useState<"text" | "file">("text");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [pos, setPos] = useState({
    leverage: "balanced",
    urgency: "low",
    relationship: "new",
    alternatives: false,
    protected_party: "",
  });
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResultDTO | null>(null);
  const [review, setReview] = useState<"pending" | "approved" | "rejected">("pending");
  const [rejectMsg, setRejectMsg] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function reset() {
    if (pollRef.current) clearTimeout(pollRef.current);
    setErr(null);
    setResult(null);
    setReview("pending");
    setRejectMsg(null);
    setElapsed(0);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    if (mode === "text" && !text.trim()) return;
    if (mode === "file" && !file) return;
    reset();
    setBusy(true);
    const started = Date.now();
    const tick = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);

    try {
      const fd = new FormData();
      if (mode === "file" && file) fd.set("file", file);
      else fd.set("text", text);
      fd.set("lang", locale === "en" ? "en" : "vi");
      fd.set("leverage", pos.leverage);
      fd.set("urgency", pos.urgency);
      fd.set("relationship", pos.relationship);
      fd.set("alternatives", String(pos.alternatives));
      fd.set("protected_party", pos.protected_party);

      const res = await fetch("/api/analyze", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok || !data.case_id) throw new Error(data.error ?? L.error);

      await poll(data.case_id, started);
    } catch (e2) {
      setErr((e2 as Error).message || L.error);
      setBusy(false);
    } finally {
      clearInterval(tick);
    }
  }

  // Poll /api/analyze/{id}: 404 = đang xử lý → thử lại; 200 = xong; 502/khác = lỗi. Trần ~6 phút.
  function poll(caseId: string, started: number): Promise<void> {
    return new Promise((resolve) => {
      const attempt = async () => {
        if (Date.now() - started > 6 * 60 * 1000) {
          setErr(L.error);
          setBusy(false);
          return resolve();
        }
        try {
          const res = await fetch(`/api/analyze/${caseId}`);
          if (res.status === 404) {
            pollRef.current = setTimeout(attempt, 2500);
            return;
          }
          const data = await res.json();
          if (!res.ok) throw new Error(data.error ?? L.error);
          setResult(data as AnalysisResultDTO);
          setReview((data as AnalysisResultDTO).needs_human_review ? "pending" : "approved");
          setBusy(false);
          resolve();
        } catch (e) {
          setErr((e as Error).message || L.error);
          setBusy(false);
          resolve();
        }
      };
      attempt();
    });
  }

  async function reject() {
    setReview("rejected");
    try {
      const res = await fetch("/api/escalate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          case_id: result?.case_id ?? "",
          reason: "Reviewer chuyển chuyên gia từ /app",
          via: "slack",
        }),
      });
      const data = await res.json();
      setRejectMsg(data.sent ? L.rejectedSent : L.rejectedNotSent);
    } catch {
      setRejectMsg(L.rejectedNotSent);
    }
  }

  const locked = result?.needs_human_review && review !== "approved";

  return (
    <div>
      <form onSubmit={submit} className="flex flex-col gap-5">
        <div className="flex gap-2">
          {(["text", "file"] as const).map((m) => (
            <Button key={m} type="button" variant={mode === m ? "primary" : "ghost"}
              onClick={() => setMode(m)} className="px-3 py-1.5">
              {m === "text" ? L.inputText : L.inputFile}
            </Button>
          ))}
        </div>

        {mode === "text" ? (
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={8}
            placeholder={L.placeholder}
            className="w-full resize-y rounded-md border border-line bg-surface p-4 text-sm outline-none focus:border-accent-d focus:ring-2 focus:ring-accent/30"
          />
        ) : (
          <input
            type="file"
            accept=".pdf,.docx,.doc,.txt,.png,.jpg,.jpeg"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm"
          />
        )}

        <fieldset className="rounded-md border border-line bg-surface p-4">
          <legend className="px-2 text-sm font-semibold uppercase tracking-[0.1em] text-muted">
            {L.position}
          </legend>
          <div className="grid gap-4 sm:grid-cols-3">
            <Select label={L.leverage} value={pos.leverage} onChange={(v) => setPos({ ...pos, leverage: v })}
              opts={[["weak", L.leverageOpts.weak], ["balanced", L.leverageOpts.balanced], ["strong", L.leverageOpts.strong]]} />
            <Select label={L.urgency} value={pos.urgency} onChange={(v) => setPos({ ...pos, urgency: v })}
              opts={[["low", L.urgencyOpts.low], ["medium", L.urgencyOpts.medium], ["high", L.urgencyOpts.high]]} />
            <Select label={L.relationship} value={pos.relationship} onChange={(v) => setPos({ ...pos, relationship: v })}
              opts={[["new", L.relationshipOpts.new], ["ongoing", L.relationshipOpts.ongoing], ["strategic", L.relationshipOpts.strategic]]} />
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={pos.alternatives}
                onChange={(e) => setPos({ ...pos, alternatives: e.target.checked })} />
              {L.alternatives}
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-muted">{L.protectedParty}</span>
              <input value={pos.protected_party} placeholder={L.protectedPartyPh}
                onChange={(e) => setPos({ ...pos, protected_party: e.target.value })}
                className="w-full rounded-md border border-line bg-paper px-3 py-1.5 outline-none focus:border-accent-d" />
            </label>
          </div>
        </fieldset>

        <Button type="submit"
          disabled={busy || (mode === "text" ? !text.trim() : !file)}
          className="self-start px-5 py-2.5">
          {busy ? `${L.analyzing} ${elapsed}s` : L.submit}
        </Button>
      </form>

      {err && <Note variant="error" className="mt-6">{err}</Note>}

      {result && (
        <div className="mt-10 flex flex-col gap-8">
          {result.summary && <Section title={L.summary}><p className="whitespace-pre-wrap leading-relaxed">{result.summary}</p></Section>}

          {result.execution_summary && result.execution_summary.total_tool_calls > 0 && (
            <Section title={`🤖 ${L.agentWork}`}>
              <div className="flex flex-wrap gap-2">
                <Badge variant="neutral">{result.execution_summary.total_tool_calls} {L.esCalls}</Badge>
                <Badge variant="neutral">{result.execution_summary.searches} {L.esSearches}</Badge>
                <Badge variant="neutral">{result.execution_summary.risks_flagged} {L.esRisks}</Badge>
                <Badge variant="neutral">{result.execution_summary.fallbacks_proposed} {L.esFallbacks}</Badge>
                {result.execution_summary.human_review_requested > 0 &&
                  <Badge variant="warn">{result.execution_summary.human_review_requested} {L.esReview}</Badge>}
              </div>
            </Section>
          )}

          {result.needs_human_review && (
            <div className={`rounded-md border p-4 ${
              review === "approved" ? "border-green-300 bg-green-50"
              : review === "rejected" ? "border-red-300 bg-red-50"
              : "border-amber-300 bg-amber-50"}`}>
              {review === "pending" && (
                <>
                  <strong>🧑‍⚖️ {L.checkpoint}</strong>
                  <p className="mt-1 text-sm text-muted">{(result.review_reasons || []).join(" · ") || L.checkpointDesc}</p>
                  <div className="mt-3 flex gap-2">
                    <Button variant="ok" onClick={() => setReview("approved")}>✓ {L.approve}</Button>
                    <Button variant="danger" onClick={reject}>✗ {L.reject}</Button>
                  </div>
                </>
              )}
              {review === "approved" && <strong className="text-green-800">✅ {L.approved}</strong>}
              {review === "rejected" && <div><strong className="text-red-800">✗ {L.rejected}</strong>{rejectMsg && <p className="mt-1 text-sm text-muted">{rejectMsg}</p>}</div>}
            </div>
          )}

          {result.strategy && <Section title={L.strategy}><p className="whitespace-pre-wrap leading-relaxed">{result.strategy}</p></Section>}

          {result.risks?.length > 0 && (
            <Section title={`${L.risks} (${result.risks.length})`}>
              <div className="flex flex-col gap-3">{result.risks.map((r, i) => <RiskCard key={i} r={r} L={L} />)}</div>
            </Section>
          )}

          {result.fallbacks?.length > 0 && (
            <Section title={L.fallbacks}>
              <div className="flex flex-col gap-3">
                {result.fallbacks.map((f, i) => (
                  <FallbackCard key={i} f={f} L={L} locked={!!locked}
                    risk={result.risks?.find((r) => r.clause === f.clause)}
                    caseId={result.case_id ?? ""} leverage={pos.leverage} />
                ))}
              </div>
            </Section>
          )}

          {result.notes && result.notes.length > 0 && (
            <Section title={L.notes}>
              <ul className="list-disc space-y-1 pl-5 text-sm text-muted">{result.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
            </Section>
          )}

          {result.risks?.length > 0 && <MemoPanel risks={result.risks} fallbacks={result.fallbacks ?? []} />}

          {(result.strategy || result.risks?.length > 0) && (
            <NegotiationPanel position={pos} dealContext={dealContext(result)} />
          )}

          {result.case_id && (
            <div className="border-t border-line pt-4">
              <FeedbackButtons kind="analysis" refValue={result.case_id} />
            </div>
          )}

          {result.trace?.length > 0 && (
            <details className="rounded-md border border-line bg-surface p-4">
              <summary className="cursor-pointer text-sm font-semibold uppercase tracking-[0.1em] text-muted">{L.trace}</summary>
              <pre className="mt-3 overflow-x-auto rounded bg-paper p-3 text-xs">{JSON.stringify(result.trace, null, 2)}</pre>
            </details>
          )}

          <p className="border-t border-line pt-6 text-sm italic text-muted">{L.disclaimer}</p>
        </div>
      )}
    </div>
  );
}

function Select({ label, value, onChange, opts }: {
  label: string; value: string; onChange: (v: string) => void; opts: [string, string][];
}) {
  return (
    <label className="text-sm">
      <span className="mb-1 block text-muted">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-line bg-paper px-3 py-1.5 outline-none focus:border-accent-d">
        {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

function RiskCard({ r, L }: { r: RiskDTO; L: AnalyzeLabels }) {
  const illegal = r.legal_status === "illegal";
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={r.severity}>{r.severity}</Badge>
        {illegal ? (
          <Badge variant="danger">⚖️ {L.illegal}{r.violated_law ? ` · ${r.violated_law}` : ""}</Badge>
        ) : (
          <Badge variant="neutral">{L.unfavorable}</Badge>
        )}
        {r.priority && <Badge variant="neutral">{r.priority}</Badge>}
        {r.verified === false && <Badge variant="warn">⚠ {L.unverified}</Badge>}
        <strong className="text-ink">{r.clause}</strong>
      </div>
      <p className="mt-2 text-sm leading-relaxed">{r.risk}</p>
      {r.evidence && <p className="mt-2 border-l-2 border-line pl-3 text-sm italic text-muted">“{r.evidence}”</p>}
      {r.legal_basis && <p className="mt-2 text-xs text-muted">📎 {L.legalBasis}: {r.legal_basis}</p>}
    </Card>
  );
}

// Bối cảnh deal cho đàm phán đa phiên: chiến lược + danh sách rủi ro (giống web/app.html _deal).
function dealContext(r: AnalysisResultDTO): string {
  const risks = (r.risks ?? [])
    .map((x) => `- ${x.clause} [${x.priority ?? ""}/${x.legal_status ?? ""}]: ${x.risk}`)
    .join("\n");
  return `CHIẾN LƯỢC:\n${r.strategy ?? ""}\n\nRỦI RO:\n${risks}`;
}

function FallbackCard({ f, L, locked, risk, caseId, leverage }: {
  f: FallbackDTO; L: AnalyzeLabels; locked: boolean; risk?: RiskDTO; caseId: string; leverage: string;
}) {
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        <strong className="text-ink">{f.clause}</strong>
        {typeof f.win_rate === "number" && <Badge variant="ok">{L.winRate} {Math.round(f.win_rate * 100)}%</Badge>}
      </div>
      <p className="mt-2 text-sm leading-relaxed">{f.suggestion}</p>
      {f.english_reply && (
        <div className="mt-3">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted">{L.reply}</span>
          <div className={`mt-1 rounded bg-paper p-3 text-sm ${locked ? "select-none blur-sm" : ""}`}>
            ✉️ {f.english_reply}
          </div>
          {locked && <p className="mt-1 text-xs italic text-muted">🔒 {L.replyLocked}</p>}
        </div>
      )}
      {f.legal_basis && <p className="mt-2 text-xs text-muted">📎 {L.legalBasis}: {f.legal_basis}</p>}
      {!locked && <FallbackActions f={f} risk={risk} caseId={caseId} leverage={leverage} />}
    </Card>
  );
}
