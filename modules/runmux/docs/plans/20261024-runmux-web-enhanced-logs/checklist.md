# Runmux Web Enhanced Output Search and Filtering Checklist

## Stage 1: Search & Filter Architecture, Controls & Safe Line Classification
- [x] Add `.output-search-bar` markup to `index.html`
- [x] Add styles for search bar, toggles, badges, and match highlights to `dashboard.css`
- [x] Implement `classifyLogLine()` and search/filter state in `dashboard.js`
- [x] Wire event listeners and safe keyboard shortcuts
- [x] Unit tests for line classification and control initialization

## Stage 2: Bounded Search, Safe Regex, Match Highlighting & Navigation
- [x] Implement bounded search matching with case sensitivity and safe regex
- [x] Implement safe DOM match highlighting using text nodes (XSS immunity)
- [x] Implement next/previous match navigation and viewport scrolling
- [x] Coordinate with follow/jump-to-latest behavior
- [x] Automated tests for search navigation, invalid regex, and XSS prevention

## Stage 3: Severity Filtering, Truncation & Scope Labeling, and Live Streaming Updates
- [x] Implement line-level severity filtering with access to unstructured lines
- [x] Implement accurate scope labeling for full and truncated buffers
- [x] Integrate with incremental streaming in `refreshOutput()`
- [x] Automated tests for severity filtering, scope display, and live updates

## Stage 4: Headless Browser & End-to-End Validation, Final Polish, Documentation & Push
- [x] Build and run headless browser test script validating real DOM, large logs, ANSI, XSS, and live updates (`browser_e2e_test.js` passed)
- [x] Run full test suite (Python pytest 29/29 + Node tests 21/21 passed)
- [x] Update documentation, plan files, and handoffs
- [x] Commit and push feature branch to origin
