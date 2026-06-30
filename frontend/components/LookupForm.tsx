"use client";

import { useState } from "react";
import { useLocale } from "next-intl";
import { Card, Section, Note } from "@/components/ui";
import { Button } from "@/components/ui/Button";
import FeedbackButtons from "@/components/FeedbackButtons";

type Result = { answer: string; sources: string[] };
type Labels = {
  placeholder: string;
  submit: string;
  loading: string;
  answer: string;
  sources: string;
  error: string;
  examples: string;
  exampleList: string[];
};

export default function LookupForm({ labels }: { labels: Labels }) {
  const locale = useLocale();
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function ask(q: string) {
    const text = q.trim();
    if (!text || busy) return;
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: text, lang: locale === "en" ? "en" : "vi" }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? labels.error);
      setResult(data as Result);
      setAsked(text);
    } catch (e) {
      setErr((e as Error).message || labels.error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
        className="flex flex-col gap-3"
      >
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
          placeholder={labels.placeholder}
          className="w-full resize-y rounded-md border border-line bg-surface p-4 text-base outline-none focus:border-accent-d focus:ring-2 focus:ring-accent/30"
        />
        <Button type="submit" disabled={busy || !question.trim()} className="self-start px-5 py-2.5">
          {busy ? labels.loading : labels.submit}
        </Button>
      </form>

      {!result && !busy && !err && (
        <div className="mt-6">
          <p className="text-sm font-semibold uppercase tracking-[0.12em] text-muted">{labels.examples}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {labels.exampleList.map((ex) => (
              <button
                key={ex}
                onClick={() => {
                  setQuestion(ex);
                  ask(ex);
                }}
                className="rounded-full border border-line bg-surface px-3 py-1.5 text-sm text-muted hover:border-accent-d hover:text-ink"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      )}

      {err && <Note variant="error" className="mt-6">{err}</Note>}

      {result && (
        <Section title={labels.answer} className="mt-8">
          <Card className="whitespace-pre-wrap p-5 leading-relaxed">{result.answer}</Card>
          {result.sources.length > 0 && (
            <Section title={labels.sources} className="mt-6">
              <ul className="space-y-1.5">
                {result.sources.map((s, i) => (
                  <li key={`${s}-${i}`}>
                    <Card className="px-3 py-2 text-sm text-muted">📎 {s}</Card>
                  </li>
                ))}
              </ul>
            </Section>
          )}
          <div className="mt-4 border-t border-line pt-3">
            <FeedbackButtons kind="lookup" refValue={asked} />
          </div>
        </Section>
      )}
    </div>
  );
}
