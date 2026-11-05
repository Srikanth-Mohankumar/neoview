# Tagged PDF support

NeoView is adding PDF accessibility tooling in stages. Acrobat Pro is a useful
workflow reference; this work does not establish feature parity or certify PDF/UA
or WCAG conformance.

## Inspection

Open a PDF and choose **Tools > Tags, Reading Order and Artifacts...**. The
inspector reads the PDF's existing structure rather than inferring tags from its
visual layout. It provides:

- A hierarchical tag tree with standard/custom roles and role mappings.
- The structure tree's logical order, independent of page drawing order.
- Tag properties including alternate text, actual text, language, page and MCIDs.
- Page navigation for entries with a resolved page association.
- Structural warnings and counts of explicit artifact marked-content sequences.

The report is a snapshot. Close and reopen it after changing or reloading the
PDF. Inspection does not modify the PDF, sidecar, or accessibility metadata.
An untagged document is reported as untagged; ordinary extracted text is not
presented as an authoritative accessibility reading order.

Artifact counts describe explicit PDF markings; they cannot determine whether
an author correctly classified decorative versus meaningful content. The dialog
states parsing limits and warnings. Absence of warnings is not a conformance
result. Complex forms, annotation associations and PDF 2.0 namespaces require
additional validation. Human review remains necessary for meaningful alternate
text, language, table semantics and sensible reading order.

## Editing a separate copy

**Tools > Edit Tags and Artifacts in Copy...** provides an isolated working copy.
Select an existing tag to edit its standard role, alternate text, actual text,
title or language. Move Up/Down changes supported sibling tag order. The editor
provides bounded undo/redo and **Save PDF Copy...** preserves the original PDF and
sidecar. Password-protected or signed documents are refused for editing.

Whole-page artifact marking is an explicit operation for supported untagged pages.
Use it only when the entire page is decorative; it is not a content-selection
repair tool. Existing structure/marked content and unsupported forms are refused.
Unmarking removes only an unchanged wrapper made by NeoView. The editor does not
infer semantics or automatically create a complete tag structure.

## Remaining Acrobat-style workflows

These capabilities require further implementation and testing:

| Area | Required work |
| --- | --- |
| Tag editing | Create/delete/reparent tags and support arbitrary custom roles; existing-tag properties and bounded undo/redo are available. |
| Reading order repair | Extend sibling moves to arbitrary reparenting/content order with a visual page overlay. |
| Content marking | Select individual content, assign MCIDs, mark/unmark artifacts in tagged content, handle Form XObjects and reused resources. |
| Tables and forms | Table headers/scope/headers associations, lists, links, annotation OBJR and form labels. |
| Automatic tagging | Semantic analysis and OCR with manual correction and reliable content associations. |
| Validation | ParentTree/IDTree/namespace validation, untagged content checks, PDF/UA profiles and report export. |
| Safe persistence | Extend supported copy saves to comprehensive repairs, protected/signed workflows and independent round-trip validation. |
| Assistive use | Screen-reader interoperability and manual testing with real tagged documents. |

Page insertion, duplication, extraction and reordering are separate document
operations. Do not assume they repair or preserve every structure association
until dedicated tagged-document round-trip tests establish that behavior.
