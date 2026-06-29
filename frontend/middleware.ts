import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

export default createMiddleware(routing);

export const config = {
  // Áp locale routing cho mọi path TRỪ api, _next, _vercel, file tĩnh (có dấu chấm).
  matcher: ["/((?!api|_next|_vercel|.*\\..*).*)"],
};
