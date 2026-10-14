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
 * The entries below still point at the pre-redesign screenshots (assets/img*.png),
 * which have no dark variants.
 */
window.NEOVIEW_SCREENS = [
  {
    id: "01-open",
    hero: true,
    light: "assets/img1.png",
    dark: null,
    width: 1440, height: 980,
    caption: "Search, outline and thumbnails",
    alt: "NeoView with a PDF open: outline and thumbnails on the left, live search results below the page."
  },
  {
    id: "measure",
    light: "assets/img2.png",
    dark: null,
    width: 1380, height: 940,
    caption: "Measurement and font inspection",
    alt: "A measurement rectangle over several lines labelled with its width, height and position, and the inspector showing the font name, size and style."
  },
  {
    id: "annotate",
    light: "assets/img3.png",
    dark: null,
    width: 1440, height: 980,
    caption: "Annotations",
    alt: "Highlighted lines, an arrow and a text-box note on a page, with the annotation list beside it."
  },
  {
    id: "tabs",
    light: "assets/img4.png",
    dark: null,
    width: 1320, height: 920,
    caption: "Tabs and document info",
    alt: "A second PDF in its own tab at fit-page zoom, with the document info panel showing file, page, zoom and the auto-reload option."
  },
  {
    id: "bookmarks",
    light: "assets/img5.png",
    dark: null,
    width: 1460, height: 980,
    caption: "Tabs, bookmarks and search",
    alt: "Three PDFs in tabs, custom bookmarks under the outline, an annotated page and search results for the word workflow."
  },
  {
    id: "thumbnails",
    light: "assets/img6.png",
    dark: null,
    width: 1360, height: 940,
    caption: "Thumbnail navigation",
    alt: "A later page of a five-page PDF reached from the outline, with page thumbnails in the left panel."
  },
  {
    id: "outline",
    light: "assets/img7.png",
    dark: null,
    width: 1360, height: 940,
    caption: "Filtering the outline",
    alt: "The outline and bookmarks filtered by the word review, next to an annotated page."
  },
  {
    id: "freehand",
    light: "assets/img8.png",
    dark: null,
    width: 1440, height: 980,
    caption: "Freehand marks",
    alt: "Freehand strokes and an ellipse on a zoomed-out page, with the annotation list and Export PDF button in the inspector."
  },
  {
    id: "search",
    light: "assets/img9.png",
    dark: null,
    width: 1440, height: 980,
    caption: "Searching longer documents",
    alt: "Search for the word Section showing match 6 of 70, with every match highlighted on the page."
  },
  {
    id: "rotate",
    light: "assets/img10.png",
    dark: null,
    width: 1380, height: 940,
    caption: "Rotation and performance mode",
    alt: "A page rotated 90 degrees with its annotations rotated along with it, and performance mode switched on."
  }
];
