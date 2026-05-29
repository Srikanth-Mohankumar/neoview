---
name: wave1-must-be-parallel-dispatched
description: Wave 1 auditors must be dispatched as parallel Agent tool calls in a single message, and their outputs consolidated before Wave 2.
metadata:
  type: feedback
---

Wave 1 NeoView auditors are designed to be parallel-safe (read-mostly or writing to disjoint new files). They must be dispatched as multiple Agent tool calls in a single assistant message — not sequentially.

**Why:** sequential dispatch wastes wall-clock and, worse, lets later auditors see code edits from earlier ones that were never intended to land mid-audit. The audit baseline must be a single point-in-time snapshot.

**How to apply:** when handing off the suite, instruct the user explicitly to send all Wave 1 agents in one message. Before dispatching the fix-implementer (Wave 2), manually consolidate the ten findings lists into a single P0/P1/P2 table — the implementer needs the union as input, not ten separate transcripts. Do not let the implementer infer findings on its own; that re-does the audit work.

Related: [[composition-premium-hardening]], [[file-ownership-boundaries]].
