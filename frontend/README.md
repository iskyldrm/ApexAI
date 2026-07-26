# ApexAI Frontend

Next.js 14 App Router + TypeScript + Tailwind CSS + shadcn/ui.

## Pages

| Path | Description |
|---|---|
| `/login` | Sign in |
| `/register` | Create account |
| `/dashboard` | Overview (orgs, activity, account) |
| `/orgs` | List of orgs |
| `/orgs/new` | Create org (platform admin) |
| `/orgs/[id]` | Org detail (teams, members, invitations) |
| `/keys` | AI keys + integrations |
| `/settings` | Settings override chain (user→team→org→platform) |
| `/audit` | Audit log viewer |

## Setup

```bash
cd frontend
pnpm install
cp .env.example .env.local   # set NEXT_PUBLIC_API_BASE_URL
pnpm dev                     # http://localhost:3000
```

## Architecture

- **`src/lib/api.ts`** — fetch wrapper with credential cookies and `ApiError`
- **`src/lib/api-client.ts`** — typed API namespaces (`auth`, `orgs`, `invitations`, `keys`, `settings`, `audit`)
- **`src/lib/auth-context.tsx`** — client-side auth provider (login/register/logout, refresh from `/auth/me`)
- **`src/components/ui/`** — shadcn primitives (Button, Input, Card, Tabs, Select, Badge, Label)
- **`src/components/nav.tsx`** — sidebar nav with org switcher
- **`src/app/(app)/`** — protected layout (redirects to `/login` if no session)

## API contract

All routes call `NEXT_PUBLIC_API_BASE_URL/api/v1/...` with `credentials: "include"` so the FastAPI HttpOnly cookies (`access_token`, `refresh_token`) flow through the browser.

## Scripts

```bash
pnpm dev          # dev server
pnpm build        # production build
pnpm start        # serve production build
pnpm lint         # ESLint
pnpm type-check   # tsc --noEmit
```
