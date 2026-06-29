"use client";

import { useLocale } from "next-intl";
import { Link, usePathname } from "@/i18n/routing";
import { routing } from "@/i18n/routing";

export default function LocaleSwitcher() {
  const locale = useLocale();
  const pathname = usePathname(); // đã bỏ tiền tố locale → giữ nguyên path khi đổi ngôn ngữ
  return (
    <div className="flex items-center gap-1 text-sm" aria-label="Language">
      {routing.locales.map((l) => (
        <Link
          key={l}
          href={pathname}
          locale={l}
          className={`rounded px-2 py-1 no-underline ${
            l === locale ? "font-semibold text-accent-d" : "text-muted hover:text-ink"
          }`}
        >
          {l.toUpperCase()}
        </Link>
      ))}
    </div>
  );
}
