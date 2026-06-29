import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Legal Guard — Trợ lý AI pháp lý cho doanh nghiệp",
  description:
    "Rà soát hợp đồng & tra cứu pháp luật Việt Nam — dẫn đúng điều luật còn hiệu lực, không bịa.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
