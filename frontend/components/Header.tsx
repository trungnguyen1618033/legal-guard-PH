import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/routing";
import LocaleSwitcher from "./LocaleSwitcher";

export default async function Header() {
  const t = await getTranslations("nav");
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex max-w-reading flex-wrap items-center justify-between gap-x-4 gap-y-2 px-6 py-4">
        <Link href="/" className="font-serif text-lg font-semibold text-ink no-underline">
          Legal&nbsp;Guard
        </Link>
        <nav className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <Link href="/" className="text-ink no-underline hover:text-accent-d">{t("home")}</Link>
          <Link href="/app" className="text-ink no-underline hover:text-accent-d">{t("analyze")}</Link>
          <Link href="/lookup" className="text-ink no-underline hover:text-accent-d">{t("lookup")}</Link>
          <Link href="/dashboard" className="text-ink no-underline hover:text-accent-d">{t("dashboard")}</Link>
          <Link href="/trust" className="text-ink no-underline hover:text-accent-d">{t("trust")}</Link>
          <LocaleSwitcher />
        </nav>
      </div>
    </header>
  );
}
