# Permy — Marketing & Docs Site (static)

The public-facing pages for Permy, deployed as a static site on Vercel.
Separate from the API (which runs on Render at `https://permy.onrender.com`).

## Structure

```
web/
├── index.html        ← landing page (marketing) — served at /
├── playground.html   ← live interactive API playground — /playground
├── dashboard.html    ← coverage & API dashboard — /dashboard
├── docs.html         ← interactive OpenAPI 3.1 reference (Scalar) — /docs
├── legal.html        ← legal & data-license page — /legal
├── vercel.json       ← clean URLs + immutable asset cache + security headers
├── robots.txt        ← SEO crawler rules
├── sitemap.xml       ← sitemap for search engines
├── site.webmanifest  ← PWA manifest (theme + icons)
└── assets/
    ├── brand-mark.png        ← logo (all pages)
    ├── mascot.png            ← hero mascot (landing)
    ├── mascot-intro-sm.mp4   ← 8s intro animation (landing, compressed)
    ├── og-image.jpg          ← Open Graph / social share image
    ├── favicon-32.png        ← favicon (32px)
    ├── favicon-16.png        ← favicon (16px)
    ├── apple-touch-icon.png  ← iOS home-screen icon
    ├── icon-192.png          ← PWA icon (192px)
    └── icon-512.png          ← PWA icon (512px)
```

## Deploy to Vercel (free, ~3 minutes)

1. Push this repo to GitHub (`github.com/lipon101/Permy`).
2. Go to https://vercel.com → Sign up / Log in with GitHub.
3. **Add New → Project** → import the `lipon101/Permy` repo.
4. Configure:
   - **Framework Preset:** Other
   - **Root Directory:** `web`  ← important: deploy only this folder
   - **Build Command:** leave empty (pure static)
   - **Output Directory:** `.`
   - **Install Command:** leave empty
5. Click **Deploy**. Live in ~30s. Every push to `main` auto-redeploys.

## URLs after deploy (clean URLs via vercel.json)

- `/` → landing page
- `/playground` → live keyless playground (hits `/v1/sample/*` on Render, CORS-open)
- `/dashboard` → coverage dashboard
- `/docs` → interactive OpenAPI 3.1 reference (renders live `permy.onrender.com/openapi.json`)
- `/legal` → legal & data license

## How the pages talk to the live API

- The **playground** and **dashboard** fetch from `https://permy.onrender.com` (override with `?api=...`).
- CORS is open on the API (`access-control-allow-origin: *`), so cross-origin calls work from Vercel.
- The **docs** page renders the live OpenAPI spec from `https://permy.onrender.com/openapi.json` via Scalar.

## SEO & performance

- Compressed assets (total `assets/` ≈ 1.3 MB; mascot 4096px → 760px, video CRF 28).
- Open Graph + Twitter Card + JSON-LD `WebApplication` structured data on every page.
- `robots.txt` + `sitemap.xml` for search indexing.
- Immutable 1-year cache on `/assets/*` and security headers (nosniff, DENY, referrer-policy) via `vercel.json`.

## Add a custom domain later (e.g. permy.dev)

1. Buy `permy.dev` (~$12/yr, Namecheap or Cloudflare Registrar).
2. In Vercel: Project → Settings → Domains → Add → enter `permy.dev`.
3. Add the DNS records Vercel gives you at your registrar. Auto-SSL provisions.
4. Optionally add `docs.permy.dev` → same project.
5. Update `canonical`/`og:url`/`sitemap.xml`/`robots.txt` URLs from `permyapp.vercel.app` to your domain.

## Updating content

Edit the HTML files here, commit, push to `main` — Vercel auto-deploys.
