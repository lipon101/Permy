# Brand assets

Bundled so the docs landing page (`../landing.html`) and any Permy-branded
output work offline from this repo / the zip.

| File | What | Spec |
|---|---|---|
| `mascot-4k.png` | Hero mascot — the "Permy" permit-badge / hard-hat character | 4096×4096, amber `#F59E0B` accent on off-white |
| `brand-mark.png` | Simplified brand mark / app icon | 2048×2048, single-color amber glyph |
| `mascot-intro.mp4` | 8s intro animation — stamp, hat tip, wave | 1080p 16:9, ~2.1MB |

## Usage
- `landing.html` references these via relative `assets/...` paths — open the
  page directly in a browser; no network needed.
- For the live published webpage the assets are also hosted publicly and the
  page is republished with those URLs.
- Color: amber `#F59E0B` (deep `#D97706`) is the single Permy accent. Keep
  backgrounds off-white `#FAF7F2` and line work charcoal `#1A1614`.

## Regenerating
These were generated with Gemini image/video models from the brand brief in
`../DOCS_OUTLINE.md` + `README.md`. To iterate, edit the prompts and rerun
image/video generation, then drop the new files here with the same names.
