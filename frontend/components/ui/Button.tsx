"use client";

// Nút tương tác (có onClick) — tách "use client" riêng để các primitive khác giữ trung lập server/client.
import type { ButtonHTMLAttributes } from "react";

const VARIANT: Record<string, string> = {
  primary: "bg-accent text-white hover:bg-accent-d",
  ghost: "border border-line bg-surface text-muted hover:border-accent-d hover:text-ink",
  danger: "border border-red-300 text-red-700 hover:bg-red-100",
  ok: "bg-green-600 text-white hover:bg-green-700",
};

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof VARIANT }) {
  return (
    <button
      {...props}
      className={`rounded-md px-4 py-2 text-sm font-medium disabled:opacity-50 ${VARIANT[variant]} ${className}`}
    />
  );
}
