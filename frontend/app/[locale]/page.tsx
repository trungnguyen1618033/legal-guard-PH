import { getTranslations, setRequestLocale } from "next-intl/server";
import { Link } from "@/i18n/routing";

export default async function Home({ params: { locale } }: { params: { locale: string } }) {
  setRequestLocale(locale);
  const t = await getTranslations("home");
  const features = [
    { t: t("f1t"), d: t("f1d") },
    { t: t("f2t"), d: t("f2d") },
    { t: t("f3t"), d: t("f3d") },
  ];
  return (
    <main className="mx-auto max-w-reading px-6 py-16">
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-accent">{t("eyebrow")}</p>
      <h1 className="mt-3 text-5xl font-semibold leading-[1.05] tracking-tight">{t("h1")}</h1>
      <p className="mt-5 max-w-[60ch] text-lg text-muted">{t("lede")}</p>
      <div className="mt-8 flex flex-wrap gap-3">
        <Link href="/trust" className="rounded-md bg-accent px-5 py-2.5 font-medium text-white no-underline hover:bg-accent-d">
          {t("ctaTrust")}
        </Link>
        <Link href="/app" className="rounded-md border border-line bg-surface px-5 py-2.5 font-medium text-ink no-underline hover:border-accent-d">
          {t("ctaTry")}
        </Link>
      </div>
      <div className="mt-16 grid gap-4 sm:grid-cols-3">
        {features.map((f) => (
          <div key={f.t} className="rounded-md border border-line bg-surface p-5">
            <h3 className="text-lg font-semibold text-accent-d">{f.t}</h3>
            <p className="mt-2 text-sm text-muted">{f.d}</p>
          </div>
        ))}
      </div>
      <p className="mt-16 border-t border-line pt-6 text-sm text-muted">{t("foot")}</p>
    </main>
  );
}
