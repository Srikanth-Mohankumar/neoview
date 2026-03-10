# Annotation Modernization Plan

## Current state (what works / what does not)

NeoView already supports sidecar-backed annotations, but the feature set is limited and inconsistent with professional PDF tools:

- Only three types exist today (`highlight`, `underline`, `note`).
- Text/comment editing is restricted to `note` annotations.
- Visual semantics are basic, with no strikeout or squiggly-style text markup.
- Persistence rejects non-whitelisted annotation types instead of handling a broader family.

## Product direction

Move NeoView to a **professional annotation model** that remains lightweight while enabling Acrobat-like workflows:

1. Expand first-class text markup types.
2. Ensure every markup can carry an editable comment.
3. Keep sidecar format backward compatible.
4. Preserve existing user data while allowing incremental upgrades.

## Phased delivery

### Phase 1 (implemented in this PR)

- Add new supported annotation types:
  - `strikeout`
  - `squiggly`
- Add toolbar/menu actions for those types.
- Extend annotation panel filtering for new types.
- Allow editing annotation comments for **all** annotation types, not just notes.
- Render strikeout and squiggly overlays in `PdfView`.
- Extend sidecar parser whitelist to include these types.

### Phase 2 (next)

- Add author/reviewer metadata and modified timestamps for UI display.
- Add per-annotation color picker and opacity controls.
- Add keyboard navigation and multi-select annotation operations.
- Add import/export bridge to embedded PDF annotations where feasible.

### Phase 3 (optional deprecation path)

- Deprecate legacy "selection-rectangle-only" behavior for text markup in favor of true text-quad selection.
- Keep read compatibility for old sidecars indefinitely.

## Compatibility and migration

- Existing sidecars remain valid with no migration required.
- New types serialize into the same sidecar schema shape (`type` + `rect` + style fields).
- Unknown external types remain ignored for safety (future schema version can add passthrough mode).

## Validation checklist

- Unit tests for sidecar parsing of new annotation types.
- UI logic tests for creating new annotation types.
- Regression test ensuring comments are editable for non-note annotations.
