import { getTranslations } from "next-intl/server";

export default async function Footer() {
  const t = await getTranslations("footer");
  return (
    <footer className="mt-20 border-t border-line">
      <div className="mx-auto flex max-w-reading flex-wrap justify-between gap-2 px-6 py-8 text-sm text-muted">
        <span>{t("tagline")}</span>
        <span>© 2026 Legal Guard · {t("rights")}</span>
      </div>
    </footer>
  );
}
