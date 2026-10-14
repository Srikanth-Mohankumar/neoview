# NeoView website

This folder is the project site, served by GitHub Pages from `/docs` on `main`:
<https://srikanth-mohankumar.github.io/neoview/>

Plain HTML, CSS and JavaScript. There is no build step.

| File | Purpose |
|------|---------|
| `index.html` | The page. Keep the anchors `#top`, `#features`, `#gallery`, `#demo`, `#installation` stable; older links point at them. |
| `style.css` | All styles. Colours are tokens on `:root`, overridden for dark mode. |
| `script.js` | Theme toggle (remembered in `localStorage`), gallery rendering, theme-aware screenshots, copy buttons. |
| `screens.js` | The screenshot manifest (see below). |
| `assets/` | Logo, favicons, demo video, screenshots. |

Every feature the page mentions should be confirmed by the top-level `README.md` or the code.

## Preview locally

```bash
python3 -m http.server -d docs 8000
# open http://localhost:8000/
```

## Screenshots

The hero image and the gallery are driven by `screens.js`. Each entry looks like this:

```js
{
  id: "05-measure",
  light: "assets/screens/light-05-measure.png",
  dark: "assets/screens/dark-05-measure.png",   // optional
  width: 1440, height: 980,                     // pixel size of the light image
  caption: "Measurement",
  alt: "A measurement rectangle with its width, height and position in points."
}
```

- The page shows `dark` when the site is in dark mode (from the OS or the toggle) and falls
  back to `light` when an entry has no dark image.
- The entry with `hero: true` is the large image at the top of the page (the `<img
  data-screen="...">` in `index.html` names its `id`); it is not repeated in the gallery.
  Update that `<img>`'s `src`, `width` and `height` too, so the page also works without
  JavaScript.
- Clicking a gallery image opens the full-size file for the current theme.

### Naming convention

```
assets/screens/light-<NN>-<step>.png
assets/screens/dark-<NN>-<step>.png
```

`<NN>-<step>` is the name the smoke test gives each screenshot: `01-open`, `02-zoom`,
`03-navigate`, `04-search`, `05-measure`, `06-reload`.

### Regenerating them

The smoke-test skill drives the real NeoView window offscreen and writes one PNG per step.
From the repository root, with the dev environment installed (`pip install -e .[dev]`):

```bash
.venv/bin/python .claude/skills/smoke-test-ui/scripts/smoke.py --out /tmp/shots-light --theme light
.venv/bin/python .claude/skills/smoke-test-ui/scripts/smoke.py --out /tmp/shots-dark  --theme dark
```

Pass `--pdf some.pdf` to photograph a real document instead of the generated three-page one.

Copy them in under the naming convention:

```bash
for f in /tmp/shots-light/*.png; do cp "$f" "docs/assets/screens/light-$(basename "$f")"; done
for f in /tmp/shots-dark/*.png;  do cp "$f" "docs/assets/screens/dark-$(basename "$f")";  done
file docs/assets/screens/*.png   # prints each image's width x height for screens.js
```

Then edit `screens.js`: point `light` / `dark` at the new files, set `width` / `height`,
and rewrite `caption` and `alt` to describe what each new screenshot actually shows. Keep
one entry with `hero: true` (usually `01-open`) and update the hero `<img>` in
`index.html` to match. Preview locally and click through the theme toggle before
committing.

### The old screenshots

`assets/img1.png` ... `assets/img10.png` are screenshots of the interface before the UI redesign. The
manifest still points at them so the page is never broken. They have no dark variants.
Once new screenshots are in place, remove them from `screens.js`; delete the files only
after checking nothing else references them (`og:image` in `index.html` uses `img1.png`, and
the demo video poster uses `img3.png`).

## Icons

`assets/favicon-32.png`, `assets/logo-mark.png` (96 px) and `assets/apple-touch-icon.png`
(180 px) are crops of `assets/feather-logo.png`.

## External resources

The page loads the Inter font from Google Fonts. Everything else is local.
