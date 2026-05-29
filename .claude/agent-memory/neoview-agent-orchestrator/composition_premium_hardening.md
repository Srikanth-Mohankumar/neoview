---
name: composition-premium-hardening
description: Twelve-agent suite the user invoked when production reported NeoView didn't feel like a premium PDF editor — post-fix hardening composition (10 parallel auditors, 1 implementer, 1 packager).
metadata:
  type: project
---

When the user has already landed root-cause fixes for reported defects and wants to harden the codebase, they prefer this composition over the standard architect-led suite:

Wave 1 parallel (10): regression-tester, render-auditor, interaction-auditor, perf-profiler, persistence-auditor, ui-polish-reviewer, cross-platform-checker, lint-checker, security-scanner, bug-sweeper.
Wave 2: fix-implementer (consumes consolidated Wave 1 findings).
Wave 3: build-packager (no release coordinator unless explicitly asked).

**Why:** the user's failure mode is "we shipped fixes but unspecified bugs remain". They want broad parallel coverage of adjacent surfaces (the code paths around the just-fixed lines) rather than a feature-planning architect. They are comfortable consolidating Wave 1 outputs manually before dispatching the implementer.

**How to apply:** when the user describes a "quality push", "hardening", "premium feel", or lists a batch of just-fixed defects and asks what comes next, emit this composition. Skip [[architect]] and [[refactor-implementer]]. Skip [[release-coordinator]] unless they ask for a release. Include [[security-scanner]] and [[perf-profiler]] — both are non-default but the user values them in quality pushes.

Related: [[file-ownership-boundaries]], [[wave1-must-be-parallel-dispatched]].
