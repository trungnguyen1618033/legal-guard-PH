import createNextIntlPlugin from "next-intl/plugin";

// Mặc định trỏ ./i18n/request.ts
const withNextIntl = createNextIntlPlugin();

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // FE gọi BFF cùng-origin (app/api/*); BFF mới gọi API ECS (giữ key server-side).
};

export default withNextIntl(nextConfig);
