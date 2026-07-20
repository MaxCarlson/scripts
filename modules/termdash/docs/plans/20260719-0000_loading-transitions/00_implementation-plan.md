# Loading Transitions Implementation Plan

## Goal

Make brief or lengthy terminal state transitions visibly active instead of
appearing frozen.

## Result

* Add a standalone `LoadingIndicator` with manual and context-manager APIs.
* Add `TermDash.transition()` for explicitly marked transitions and
  `show_loading()` / `hide_loading()` for manual dashboard placement.
* Render dashboard transitions below normal dashboard rows.
* Integrate ytaedl's slow domain-index rebuild and add focused tests.
