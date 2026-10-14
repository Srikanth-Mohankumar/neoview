/*
 * Screenshot manifest for the NeoView site. See docs/README.md.
 *
 * Each entry is one gallery tile:
 *   id      - step name; new screenshots use the smoke-test names (01-open ... 06-reload).
 *             An <img data-screen="<id>"> anywhere in index.html (the hero) also uses it.
 *   hero    - optional; true for the entry shown large at the top of the page
 *             (index.html: <img data-screen="...">). Hero entries are left out of the gallery.
 *   light   - image shown in the light theme (required).
 *   dark    - image shown in the dark theme (optional; falls back to light).
 *   width / height - pixel size of the light image, to reserve space and avoid layout shift.
 *   caption - short figure caption.
 *   alt     - what the screenshot shows, for screen readers.
 *
 * Naming convention for new screenshots: assets/screens/light-<NN>-<step>.png and
 * assets/screens/dark-<NN>-<step>.png, e.g. assets/screens/dark-05-measure.png.
 *
 * Screenshots: v0.5 UI, captured with smoke.py --pdf <sample article> --size 1440x900.
 */
window.NEOVIEW_SCREENS = [
  {
    id: "09-sidebar-outline",
    hero: true,
    light: "assets/screens/light-09-sidebar-outline.png",
    dark: "assets/screens/dark-09-sidebar-outline.png",
    width: 1440, height: 900,
    caption: "Outline, search and measurement",
    alt: "NeoView with a LaTeX article open: the outline sidebar on the left, a search match highlighted and a measurement rectangle labelled with its width, height and position."
  },
  {
    id: "07-inspector",
    light: "assets/screens/light-07-inspector.png",
    dark: "assets/screens/dark-07-inspector.png",
    width: 1440, height: 900,
    caption: "Inspector",
    alt: "The inspector panel beside the page showing the measured width, height and position in points, a units selector, and the document's metadata."
  },
  {
    id: "08-sidebar-thumbnails",
    light: "assets/screens/light-08-sidebar-thumbnails.png",
    dark: "assets/screens/dark-08-sidebar-thumbnails.png",
    width: 1440, height: 900,
    caption: "Thumbnails",
    alt: "Page thumbnails in the sidebar next to the open document, with the current page highlighted."
  },
  {
    id: "12-annotate",
    light: "assets/screens/light-12-annotate.png",
    dark: "assets/screens/dark-12-annotate.png",
    width: 1440, height: 900,
    caption: "Annotation tools",
    alt: "The annotation toolbar with highlight, underline, strike-out, note, text, shapes and freehand tools, colour, opacity and stroke width."
  },
  {
    id: "13-two-page-night",
    light: "assets/screens/light-13-two-page-night.png",
    dark: "assets/screens/dark-13-two-page-night.png",
    width: 1440, height: 900,
    caption: "Two-page view, night mode",
    alt: "Two pages side by side in night reading mode: white text on black pages, with a table and a plotted figure."
  },
  {
    id: "01-empty",
    light: "assets/screens/light-01-empty.png",
    dark: "assets/screens/dark-01-empty.png",
    width: 1440, height: 900,
    caption: "Welcome screen",
    alt: "The empty window with an Open PDF button and a drop hint."
  }
];
