import { getTranslations, setRequestLocale } from "next-intl/server";
import { getTrust } from "@/lib/api";
import { PageShell, Section, Card, Note, Disclaimer } from "@/components/ui";

export const revalidate = 300;

export default async function TrustPage({ params: { locale } }: { params: { locale: string } }) {
  setRequestLocale(locale);
  const t = await getTranslations("trust");

  let data;
  try {
    data = await getTrust();
  } catch {
    return (
      <PageShell back={t("back")} title={t("h1")}>
        <Note variant="error">{t("error")}</Note>
      </PageShell>
    );
  }

  return (
    <PageShell back={t("back")} title={t("h1")} lede={t("lede")}>
      <Section title={t("metrics")}>
        <div className="grid gap-3 sm:grid-cols-2">
          {data.metrics.map((m) => (
            <Card key={m.name}>
              <div className="text-2xl font-semibold text-accent-d">{m.value}</div>
              <div className="mt-1 font-medium">{m.name}</div>
              <div className="mt-1 text-sm text-muted">{m.note}</div>
            </Card>
          ))}
        </div>
      </Section>

      <Section title={t("methodology")} className="mt-10">
        <ul className="space-y-3">
          {data.methodology.map((m) => (
            <li key={m.layer}>
              <Card>
                <strong className="text-accent-d">{m.layer}</strong>
                <p className="mt-1 text-sm text-muted">{m.desc}</p>
              </Card>
            </li>
          ))}
        </ul>
      </Section>

      <Disclaimer>{data.disclaimer}</Disclaimer>
    </PageShell>
  );
}
