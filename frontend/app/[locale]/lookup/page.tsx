import { getTranslations, setRequestLocale } from "next-intl/server";
import LookupForm from "@/components/LookupForm";
import LegalTools from "@/components/LegalTools";
import { PageShell, Disclaimer } from "@/components/ui";

export default async function LookupPage({ params: { locale } }: { params: { locale: string } }) {
  setRequestLocale(locale);
  const t = await getTranslations("lookup");

  const labels = {
    placeholder: t("placeholder"),
    submit: t("submit"),
    loading: t("loading"),
    answer: t("answerLabel"),
    basis: t("basisLabel"),
    sources: t("sourcesLabel"),
    conf: { high: t("confHigh"), medium: t("confMedium"), low: t("confLow") },
    error: t("error"),
    examples: t("examples"),
    exampleList: [t("ex1"), t("ex2"), t("ex3")],
  };

  return (
    <PageShell back={t("back")} title={t("h1")} lede={t("lede")}>
      <LookupForm labels={labels} />
      <LegalTools />
      <Disclaimer>{t("disclaimer")}</Disclaimer>
    </PageShell>
  );
}
