# Document tools

The File menu groups exports, annotation transfer, bookmark transfer, file-location
commands, and tab commands. The Pages menu contains structural PDF operations.
All PDF-copy commands leave the original PDF and its `.neoview.json` sidecar
unchanged. Copies include remapped sidecar records where applicable. Copy
operations refuse password-protected PDFs rather than remove their protection.

| Menu | Command | Behavior |
| --- | --- | --- |
| Pages | Reverse Pages into Copy | Reverses the document and remaps retained records. |
| Pages | Duplicate Page Ranges | Copies entered pages after the last selected original page; copied records receive new IDs. |
| Pages | Insert Blank Page | Inserts a blank A4 page at position 1 through N+1, including append. |
| Pages | Split into One-Page PDFs | Creates a new folder containing one PDF and remapped sidecar per page. |
| File / Document Exports | Save Optimized PDF Copy | Uses lossless compression and garbage collection; output is not guaranteed to be smaller. |
| File / Document Exports | Export Page Geometry as CSV | Reports displayed page dimensions in points and millimeters, rotation, and annotation counts. |
| File / Document Exports | Export Document Text | Saves selectable text as UTF-8 with numbered page separators; scanned pages need OCR elsewhere. |
| File / Document Exports | Extract Embedded Images | Extracts unique embedded image resources and soft masks into a new folder. |
| File / Document Exports | Export Pages as PNG | Renders entered pages at 36-300 DPI with image-allocation limits. Native annotations are included; NeoView sidecar overlays are not. |
| File / Document Exports | Export Outline as JSON | Exports nested outline entries and destination details. |
| File / Annotation Transfer | Export Editable Annotations as JSON | Transfers complete editable records; native annotations remain in the PDF. |
| File / Annotation Transfer | Import Editable Annotations from JSON | Validates the entire file and appends records with fresh IDs. |
| File / Annotation Transfer | Export Annotation Report as Markdown | Groups native and editable annotations by page and escapes report text. |
| File / Bookmark Transfer | Export Bookmarks as JSON | Saves bookmark titles, positions, and one-based page numbers. |
| File / Bookmark Transfer | Import Bookmarks from JSON | Validates the entire file and appends bookmarks with fresh IDs. |
| File / File Location | Copy PDF File Path | Copies the active document's absolute local path. |
| File / File Location | Open Containing Folder | Opens the folder through the platform desktop service. |
| File / Tab Actions | Close Other Tabs | Saves and closes every tab except the active document. |
| File / Tab Actions | Close Tabs to the Right | Saves and closes tabs after the active document. |
| File / Tab Actions | Reopen Closed Tab | Reopens the most recently closed available PDF; keeps up to 20 paths per window. Shortcut: Ctrl+Shift+W. |

Page ranges such as `1-3, 5` use one-based page numbers. Duplicate selections and
descending ranges are rejected. Directory exports create a fresh child folder
and refuse an existing destination. Failed exports clean up their own staged
outputs. Reports and transfers refuse destinations that alias the source PDF or
its sidecar.

## Transfer formats

Annotation JSON has `version: 1` and an `annotations` array using NeoView's
annotation fields, including **zero-based** `page`, rectangle coordinates in
PDF points, colors, opacity, and optional freehand points and extra data. It
round-trips complete editable records, but import assigns fresh IDs.

Bookmark JSON has `version: 1` and a `bookmarks` array whose records contain
`title`, **one-based** `page`, `y`, and `created_at`. Import assigns fresh IDs.
Both importers reject unknown versions, malformed records, nonfinite numbers,
and pages outside the current document before changing any state. Annotation
imports are limited to 10 MB and 10,000 combined records; bookmark imports are
limited to 5 MB and 5,000 combined records. Imports schedule normal sidecar
persistence and preserve existing native annotations.
