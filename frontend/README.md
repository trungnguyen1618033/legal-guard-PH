# Legal Guard — Frontend (Next.js)

Giao diện web cho Legal Guard, thay cho bộ `web/*.html` vanilla. Next.js 14 (App Router) +
TypeScript + Tailwind + `next-intl` (song ngữ vi/en). Mọi lệnh gọi API đi qua **BFF** (route
handlers chạy server-side) để **giữ API key kín** — không bao giờ lộ ra trình duyệt.

## Chạy

```bash
cd frontend
cp .env.example .env.local      # điền LG_API_BASE + LG_API_KEY
npm install
npm run dev                     # http://localhost:3000 → tự chuyển /vi
npm run build && npm start      # bản production
```

### Biến môi trường (`.env.local`, server-side — KHÔNG có `NEXT_PUBLIC_`)
| Biến | Ý nghĩa |
|---|---|
| `LG_API_BASE` | URL API backend (mặc định `https://legalguard.duckdns.org`) |
| `LG_API_KEY`  | API key gửi qua header `x-api-key`. Chỉ dùng ở BFF, không lộ client. |

## Kiến trúc

```
app/[locale]/            # trang (SSG song ngữ): page (home) · app · lookup · dashboard · trust
  layout.tsx             # Header + Footer + NextIntlClientProvider
  error.tsx              # error boundary cấp locale
app/api/                 # BFF: route handler proxy → backend (đính kèm x-api-key)
components/
  ui/                    # primitive dùng chung: Card·Section·Badge·Note·Disclaimer·PageShell·Button
  *.tsx                  # component theo tính năng (AnalyzeFlow, LookupForm, LegalTools, …)
lib/
  api.ts                 # BASE/authHeaders + type DTO + getTrust/getDashboard/askLegal
  bff.ts                 # helper bffGet/bffPost cho route handler (truyền nguyên status)
i18n/                    # routing (locale prefix) + request (load messages)
messages/{vi,en}.json    # chuỗi dịch — vi/en luôn ĐỐI XỨNG (xem "Quy tắc")
```

**Luồng dữ liệu:** Client component → `fetch('/api/…')` (cùng-origin) → route handler BFF →
`fetch(LG_API_BASE + …, {headers: x-api-key})` → backend. Key chỉ tồn tại ở tầng server.

## Trang & tính năng

| Trang | Tính năng | Endpoint backend |
|---|---|---|
| `/` | Landing + CTA | — |
| `/app` | Rà soát HĐ (async + poll), human-checkpoint, counter-clause, ghi outcome, **đàm phán đa phiên**, bản ghi nhớ + tải Word, feedback | `/analyze` · `/analyze/result/{id}` · `/escalate` · `/counter` · `/cases/{id}/outcome` · `/negotiate` · `/amendments/compile(.docx)` · `/feedback` |
| `/lookup` | Tra cứu luật + feedback · **Autopilot quét luật mới** · tác động VB mới · lược đồ+lịch sử văn bản · redline | `/ask` · `/feedback` · `/monitor/run` · `/impact` · `/graph` · `/latest` · `/articles-changed` · `/changes` · `/redline` |
| `/dashboard` | System-of-record (KPI, severity, top clauses, win-rate) — client fetch, authed | `/insights/dashboard` |
| `/trust` | Công bố độ tin cậy (SSG, ISR 5′) | `/trust.json` |

Hợp đồng dài: `/analyze` luôn chạy `async_mode` → trả `case_id` ngay, client poll
`/api/analyze/{id}` mỗi 2.5s (404 = đang xử lý, 200 = xong), trần 6 phút.

## Quy tắc khi sửa (đã thống nhất)

1. **Không lộ key ra client** — luôn gọi qua `/api/…` (BFF). Component client KHÔNG được `fetch`
   thẳng tới `LG_API_BASE`.
2. **Tái dùng `components/ui/`** — đừng viết lại card/badge/button/section inline.
3. **i18n đối xứng** — mọi key phải có ở CẢ `vi.json` và `en.json`. Component client dùng
   `useTranslations("<ns>")`; server dùng `getTranslations`.
4. **Dữ liệu authed → `cache: "no-store"`** (vd dashboard). Chỉ dữ liệu công khai mới ISR.
5. `npm run build` phải xanh (đã bật `strict: true` — không dùng `any`).

## Triển khai (chưa thực hiện)

ECS hiện chạy bản `web/*.html`. Để lên sóng bản này: dựng Docker Node + route Caddy
(`/` → Next.js, giữ `/analyze`,`/ask`,… ở backend) hoặc deploy Vercel (đặt `LG_API_*` ở env).
