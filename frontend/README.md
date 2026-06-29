# Legal Guard — Frontend (Next.js) · P0 scaffold

Khung FE riêng (Next.js 14 App Router + TypeScript + Tailwind) — bước **P0** trong
`docs/internal/nextjs-fe-plan.md`. Hiện có: trang **landing** + trang **/trust** (data-driven qua BFF).

## Chạy
```bash
cd frontend
cp .env.example .env        # điền LG_API_KEY nếu API ECS bật auth
npm install
npm run dev                 # http://localhost:3000
```

## Đã có (P0)
- `app/page.tsx` — **landing** marketing (design tokens xanh-ngọc, port từ /tai-lieu).
- `app/trust/page.tsx` — **/trust** đọc số liệu thật từ API ECS (Server Component + ISR 5').
- `app/api/trust/route.ts` — **BFF mẫu**: browser gọi cùng-origin, server giữ `LG_API_KEY` kín, proxy tới ECS.
- `lib/api.ts` — **typed client** (`getTrust()`), base URL + key từ env (server-side).
- `tailwind.config.ts` — **design tokens** (paper/ink/accent…).

## Vì sao có BFF
API key KHÔNG được lộ ở browser. Mọi endpoint cần auth (`/analyze`, `/cases`…) gọi qua route handler
`app/api/*` (giữ key server-side) thay vì fetch trực tiếp từ client.

## Bước tiếp (xem plan)
P1 hoàn thiện marketing + i18n vi/en → P2 `/lookup` → P3 `/app` (async poll + human-checkpoint) → P4 dashboard+graph → P5 auth.

## Triển khai
- **Vercel** (khuyến nghị — SSR/SEO; đặt `LG_API_BASE`/`LG_API_KEY` ở Project Settings), hoặc
- **Cùng ECS** (thêm service Node vào compose, sau Caddy) để cùng-origin.
