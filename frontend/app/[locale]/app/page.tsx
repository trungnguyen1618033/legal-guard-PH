import { getTranslations, setRequestLocale } from "next-intl/server";
import AnalyzeFlow, { type AnalyzeLabels } from "@/components/AnalyzeFlow";
import { PageShell } from "@/components/ui";

export default async function AppPage({ params: { locale } }: { params: { locale: string } }) {
  setRequestLocale(locale);
  const t = await getTranslations("app");

  const labels: AnalyzeLabels = {
    inputText: t("inputText"),
    inputFile: t("inputFile"),
    placeholder: t("placeholder"),
    position: t("position"),
    leverage: t("leverage"),
    leverageOpts: { weak: t("leverageWeak"), balanced: t("leverageBalanced"), strong: t("leverageStrong") },
    urgency: t("urgency"),
    urgencyOpts: { low: t("urgencyLow"), medium: t("urgencyMedium"), high: t("urgencyHigh") },
    relationship: t("relationship"),
    relationshipOpts: { new: t("relNew"), ongoing: t("relOngoing"), strategic: t("relStrategic") },
    alternatives: t("alternatives"),
    protectedParty: t("protectedParty"),
    protectedPartyPh: t("protectedPartyPh"),
    submit: t("submit"),
    analyzing: t("analyzing"),
    error: t("error"),
    summary: t("summary"),
    agentWork: t("agentWork"),
    esCalls: t("esCalls"),
    esSearches: t("esSearches"),
    esRisks: t("esRisks"),
    esFallbacks: t("esFallbacks"),
    esReview: t("esReview"),
    strategy: t("strategy"),
    risks: t("risks"),
    fallbacks: t("fallbacks"),
    notes: t("notes"),
    trace: t("trace"),
    legalBasis: t("legalBasis"),
    illegal: t("illegal"),
    unfavorable: t("unfavorable"),
    unverified: t("unverified"),
    reply: t("reply"),
    replyLocked: t("replyLocked"),
    checkpoint: t("checkpoint"),
    checkpointDesc: t("checkpointDesc"),
    approve: t("approve"),
    reject: t("reject"),
    approved: t("approved"),
    rejected: t("rejected"),
    rejectedSent: t("rejectedSent"),
    rejectedNotSent: t("rejectedNotSent"),
    winRate: t("winRate"),
    disclaimer: t("disclaimer"),
  };

  return (
    <PageShell back={t("back")} title={t("h1")} lede={t("lede")}>
      <AnalyzeFlow labels={labels} />
    </PageShell>
  );
}
