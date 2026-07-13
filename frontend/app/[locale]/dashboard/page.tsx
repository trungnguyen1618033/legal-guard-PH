import { getTranslations, setRequestLocale } from "next-intl/server";
import DashboardView, { type DashboardLabels } from "@/components/DashboardView";
import PortfolioPlaybook from "@/components/PortfolioPlaybook";
import { PageShell } from "@/components/ui";

export default async function DashboardPage({ params: { locale } }: { params: { locale: string } }) {
  setRequestLocale(locale);
  const t = await getTranslations("dashboard");

  const labels: DashboardLabels = {
    error: t("error"), empty: t("empty"),
    cases: t("cases"), needsReview: t("needsReview"), totalRisks: t("totalRisks"), kbGaps: t("kbGaps"),
    severity: t("severity"), high: t("high"), medium: t("medium"), low: t("low"),
    topClauses: t("topClauses"), feedback: t("feedback"), noFeedback: t("noFeedback"), topTactics: t("topTactics"),
  };

  return (
    <PageShell back={t("back")} title={t("h1")} lede={t("lede")}>
      <DashboardView labels={labels} />
      <div className="mt-8">
        <PortfolioPlaybook />
      </div>
    </PageShell>
  );
}
