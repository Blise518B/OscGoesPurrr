<!-- This folder is the OscGoesPurrr landing page, served by GitHub Pages. -->

# OscGoesPurrr — landing page

A single, self-contained promo page (`index.html`) with embedded CSS/JS and a
handful of generated images. No build step, no framework.

**Live page:** https://blise518b.github.io/OscGoesPurrr/

## Publishing it (one-time)

On GitHub: **Settings → Pages → Build and deployment**

- **Source:** *Deploy from a branch*
- **Branch:** `main`  ·  **Folder:** `/docs`
- Save. The page goes live at the URL above in a minute or two.

> The `.nojekyll` file tells Pages to serve these files as-is (no Jekyll), so
> the hand-written HTML is published verbatim.

## Adding your recordings

The gallery shows styled placeholders until you drop real captures into
[`assets/shots/`](assets/shots/). Filenames are matched automatically — no code
changes needed:

| File | Shows as |
| --- | --- |
| `assets/shots/demo.mp4` | Looping highlight clip (wide) |
| `assets/shots/demo-poster.png` | Poster frame for the clip (optional) |
| `assets/shots/dashboard.png` | Dashboard |
| `assets/shots/routing.png` | Device Routing |
| `assets/shots/signal-chain.png` | Signal-chain tuning |
| `assets/shots/bhaptics.png` | bHaptics dot grid |

Suggested specs: PNG screenshots ~1600 px wide; the clip as H.264 MP4, muted,
a few seconds, looping.

## Regenerating the brand images

The logo/favicon/social-card are derived from `Images/OGP_Logo_Original.png`:

```
python tools/build_site_assets.py
```

Edit the gradient stops in that script to re-tint everything.

## Editing copy

Everything lives in `index.html`. Section content is plain HTML; the brand
colors are CSS custom properties near the top (`--pink`, `--violet`, `--cyan`,
`--grad`).
