# Permy — Marketing & Docs Site (static)

The public-facing pages for Permy, deployed as a static site on Vercel.
Separate from the API (which runs on Render at `https://permy.onrender.com`).

## Structure

```
web/
├── index.html        ← landing page (marketing) — served at /
├── playground.html   ← live interactive API playground + docs  — /playground
├── dashboard.html    ← coverage & API dashboard  — /dashboard
├── vercel.json       ← clean URLs + cache + security headers
└── assets/
    ├── brand-mark.png     ← logo (used by all 3 pages)
    ├── mascot-4k.png      ← hero mascot (landing only)
    └── mascot-intro.mp4   ← 8s intro animation (landing only)
```

## Deploy to Vercel (free, ~3 minutes)

1. Push this repo to GitHub (already done — `github.com/lipon101/Permy`).
2. Go to https://vercel.com → Sign up / Log in with GitHub.
3. **Add New → Project** → import the `lipon101/Permy` repo.
4. Configure:
   - **Framework Preset:** Other (or "Static")
   - **Root Directory:** `web`  ← important: set this so Vercel only deploys the web/ folder
   - **Build Command:** leave empty (no build step — pure static HTML)
   - **Output Directory:** leave as `web` (or `.` once root is set)
   - **Install Command:** leave empty
5. Click **Deploy**. Live in ~30s at `https://permy-<random>.vercel.app`.

## URLs after deploy (clean URLs via vercel.json)

- `https://<your-site>.vercel.app/` → landing page
- `https://<your-site>.vercel.app/playground` → live playground
- `https://<your-site>.vercel.app/dashboard` → coverage dashboard

## Add a custom domain later (e.g. permy.dev)

1. Buy `permy.dev` (~$12/yr, Namecheap or Cloudflare Registrar).
2. In Vercel: Project → Settings → Domains → Add → enter `permy.dev`.
3. Vercel gives you DNS records to add at your registrar. Add them.
4. Auto-SSL provisions. `https://permy.dev` is live.
5. Optionally add `docs.permy.dev` → same project.

## How the pages talk to the live API

- The **playground** fetches from `https://permy.onrender.com` (override with `?api=...`).
- CORS is open on the API (`allow_origins=["*"]`), so the playground works from any origin.
- When you add `api.permy.dev` as a CNAME → `permy.onrender.com`, update the
  `const API` line in `playground.html` to `https://api.permy.dev` for the pro URL.

## Updating content

Edit the HTML files in this folder, commit, push to GitHub — Vercel auto-deploys.
