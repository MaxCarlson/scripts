# Startup Loading Indicator Implementation Plan

## Goal

Show a visible, animated status while ytaedl performs slow initialization before
its custom UI can render.

## Result

Use TermDash's standalone `LoadingIndicator` around `DomainIndex.build()`, the
slow startup path selected by `-D` and explicitly rebuilt by `-M`. Forward the
index's real phase messages to both the indicator and the manager log.
