/*
 * Screenshot manifest for the NeoView site. See docs/README.md.
 *
 * Each entry is one gallery tile:
 *   id      - step name from the recorder (e.g. "05-fonts"). An <img data-screen="<id>">
 *             anywhere in index.html (the hero) also uses it.
 *   hero    - optional; true for the entry shown large at the top of the page.
 *             Hero entries are left out of the gallery.
 *   light   - image shown in the light theme (required).
 *   dark    - image shown in the dark theme (optional; falls back to light).
 *   width / height - pixel size of the light image, to reserve space and avoid layout shift.
 *   caption - short figure caption.
 *   alt     - what the screenshot shows, for screen readers.
 *
 * Naming: assets/screens/light-<NN>-<step>.webp and assets/screens/dark-<NN>-<step>.webp.
 * Screenshots: v0.5 UI at 1440x900, real window driven offscreen on a LaTeX sample article.
 */
window.NEOVIEW_SCREENS = [
  {
    id: "00-hero", hero: true,
    light: "assets/screens/light-00-hero.webp", dark: "assets/screens/dark-00-hero.webp",
    width: 1440, height: 900,
    caption: "Outline, search, measurement and inspector",
    alt: "NeoView with a LaTeX article open: the outline sidebar on the left, search matches for 'measure' highlighted, a measured table with its size badge, and the inspector showing width, height, position and the document's metadata."
  },
  {
    id: "05-fonts",
    light: "assets/screens/light-05-fonts.webp", dark: "assets/screens/dark-05-fonts.webp",
    width: 1440, height: 900,
    caption: "Font inspection",
    alt: "The pointer over a code word in the text; it is outlined and the inspector's Text section reads Inconsolatazi4-Regular, 10.9 pt, Regular."
  },
  {
    id: "06-measure",
    light: "assets/screens/light-06-measure.webp", dark: "assets/screens/dark-06-measure.webp",
    width: 1440, height: 900,
    caption: "Measuring a table",
    alt: "A measurement rectangle around a table with a badge giving its width, height, X and Y in points, repeated in the inspector."
  },
  {
    id: "07-grid",
    light: "assets/screens/light-07-grid.webp", dark: "assets/screens/dark-07-grid.webp",
    width: 1440, height: 900,
    caption: "Rulers and layout grid",
    alt: "Rulers in points along the top and left of the view and a magenta layout grid drawn over the page."
  },
  {
    id: "04-search",
    light: "assets/screens/light-04-search.webp", dark: "assets/screens/dark-04-search.webp",
    width: 1440, height: 900,
    caption: "Search results with snippets",
    alt: "Matches for 'baseline' highlighted on the page and listed in the search results panel with their page numbers and surrounding text."
  },
  {
    id: "09-annotate",
    light: "assets/screens/light-09-annotate.webp", dark: "assets/screens/dark-09-annotate.webp",
    width: 1440, height: 900,
    caption: "Annotations",
    alt: "The annotation toolbar above the page, a highlighted phrase, a sticky note and a red rectangle on the page, and the three annotations listed in the sidebar."
  },
  {
    id: "03-outline",
    light: "assets/screens/light-03-outline.webp", dark: "assets/screens/dark-03-outline.webp",
    width: 1440, height: 900,
    caption: "Outline filter",
    alt: "The outline sidebar filtered to one section, with the view jumped to that section."
  },
  {
    id: "13-reloaded",
    light: "assets/screens/light-13-reloaded.webp", dark: "assets/screens/dark-13-reloaded.webp",
    width: 1440, height: 900,
    caption: "Reloaded after a rebuild",
    alt: "The page after the PDF was rebuilt on disk: a revised, highlighted paragraph is shown in place at the same position."
  },
  {
    id: "10-two-page-sepia",
    light: "assets/screens/light-10-two-page-sepia.webp", dark: "assets/screens/dark-10-two-page-sepia.webp",
    width: 1440, height: 900,
    caption: "Two pages, sepia",
    alt: "Two pages side by side in the sepia reading mode."
  },
  {
    id: "10-two-page-night",
    light: "assets/screens/light-10-two-page-night.webp", dark: "assets/screens/dark-10-two-page-night.webp",
    width: 1440, height: 900,
    caption: "Two pages, night mode",
    alt: "Two pages side by side in night reading mode: light text on black pages."
  },
  {
    id: "12-print",
    light: "assets/screens/light-12-print.webp", dark: "assets/screens/dark-12-print.webp",
    width: 1440, height: 900,
    caption: "Print",
    alt: "The print dialog over the document."
  },
  {
    id: "01-welcome",
    light: "assets/screens/light-01-welcome.webp", dark: "assets/screens/dark-01-welcome.webp",
    width: 1440, height: 900,
    caption: "Welcome screen",
    alt: "The empty window with an Open PDF button, a drop hint and a list of recent files."
  }
];
