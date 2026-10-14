# NeoView website

This folder is the project site, served by GitHub Pages from `/docs` on `main`:
<https://srikanth-mohankumar.github.io/neoview/>

Plain HTML, CSS and JavaScript. There is no build step.

| File | Purpose |
|------|---------|
| `index.html` | The page. Keep the anchors `#top`, `#features`, `#gallery`, `#demo`, `#installation` stable; older links point at them. Newer ones: `#performance`, `#faq`, `#about`. |
| `style.css` | All styles. Colours are tokens on `:root`, overridden for dark mode. |
| `script.js` | Theme toggle (remembered in `localStorage`), gallery rendering, theme-aware screenshots, copy buttons, feature clips (play when visible, paused under reduced motion), demo chapter buttons. |
| `screens.js` | The screenshot manifest (see below). |
| `assets/` | Logo, favicons, demo video, clips, screenshots. |

Every feature the page mentions should be confirmed by the top-level `README.md` or the code.

## Preview locally

```bash
python3 -m http.server -d docs 8000
# open http://localhost:8000/
```

## Media

| Path | What |
|------|------|
| `assets/screens/{light,dark}-<NN>-<step>.webp` | Screenshots (1440x900), listed in `screens.js` |
| `assets/screens/og-image.png` | Social preview (PNG on purpose: some crawlers skip WebP) |
| `assets/clips/clip-<name>.mp4` + `.webp` | Silent looping feature clips (1200x750) and their posters |
| `assets/neoview-demo.mp4` | Chaptered demo (1440x900 H.264, faststart); chapters also in `neoview-demo-chapters.vtt` |
| `assets/neoview-demo-poster.webp` | Demo poster |

Every feature the page or the media shows must be in `docs/dev/feature-inventory.md`, which
traces it to the code.

### Screenshots manifest

The hero image and the gallery are driven by `screens.js`. Each entry has `id`, `light`,
`dark` (optional), `width`, `height`, `caption` and `alt`; the entry with `hero: true` is the
large image at the top (the `<img data-screen="...">` in `index.html` names its `id`; update
that `<img>`'s `src` too so the page works without JavaScript). The page shows `dark` when the
site is in dark mode and falls back to `light`.

### Regenerating media

Screenshots, the demo and the clips are recorded by driving the real window offscreen
(temporary INI settings, never the user's config) on a LaTeX sample article, then encoded with
ffmpeg (libx264, `-tune stillimage -pix_fmt yuv420p -movflags +faststart`). The cursor and the
chapter captions are painted onto the frames with QPainter, since window grabs do not include
the OS cursor. For quick screenshots of the basic flows, the smoke-test skill also works:

```bash
.venv/bin/python .claude/skills/smoke-test-ui/scripts/smoke.py --out /tmp/shots --theme light --size 1440x900
```

When changing the demo, keep the chapter timestamps in `index.html` (`data-t` on the chapter
buttons) and `neoview-demo-chapters.vtt` in step with the video.

### Old images

`assets/img1.png` ... `assets/img10.png` are screenshots of the interface before the 0.5
redesign. Nothing on the page uses them; they stay so old external links keep working.

## Icons

`assets/favicon-32.png`, `assets/logo-mark.png` (96 px) and `assets/apple-touch-icon.png`
(180 px) are crops of `assets/feather-logo.png`.

## External resources

The page loads the Inter font from Google Fonts. Everything else is local.
