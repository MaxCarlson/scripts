---
name: web-ui-dev
description: >
  This skill should be used when working on web UI code (HTML, CSS, JavaScript,
  Tailwind, templates), when the user asks to "improve the dashboard", "fix the
  layout", "change colors", "redesign the web UI", "make it look better",
  "adjust styling", "update the CSS", "make it responsive", "fix the dark theme",
  "style the page", or any task involving visual web frontend changes. It enables
  visual iteration by taking browser screenshots after every change, evaluating
  against the design system, and making aesthetic adjustments without requiring
  user confirmation for each visual tweak.
version: 0.1.0
compatibility:
  - claude-code
---

# Web UI Development with Visual Iteration

## Overview

This skill enables pixel-accurate visual iteration on web UI changes. Instead of
working blind, take browser screenshots after every change, evaluate them against
the design system, and adjust autonomously. The result is faster, higher-quality
frontend work without constant user review of cosmetic details.

## Prerequisites

Before starting any web UI work:

1. **Start the dev server** with hot-reload. Try in order:
   ```bash
   webui -r -v -p 3001                    # If webui CLI is installed
   koweb -r -v -p 3001                    # Legacy alias
   cd ~/scripts/modules/web_ui_tools && uvicorn web_ui_tools.app:create_app --reload --port 3001
   ```
   If none of these commands are available, ask the user how to start their
   development server and on which port.

2. **Take a baseline screenshot** of the current state before making any changes.
   This enables before/after comparison.

3. **Load Playwright tools** via ToolSearch for `playwright` to enable browser
   screenshot capabilities.

## Core Workflow: Edit-Screenshot-Evaluate Loop

For every visual change (CSS, HTML, layout, color, spacing, typography):

### 1. Make the Change
Edit the file (CSS, HTML, JS, template).

### 2. Take a Screenshot
Navigate to the relevant page and capture:

```
browser_navigate → http://localhost:3001
browser_take_screenshot
```

For specific views or states, navigate to the appropriate route first.

### 3. Evaluate Against Design System
Compare the screenshot to the design system defined in
`references/design-system.md`. Check:

- Color usage matches the defined palette
- Typography uses the correct font families and sizes
- Spacing follows the 4px/8px grid
- Metric cards follow the panel pattern
- Layout respects the grid structure
- Contrast ratios are sufficient for readability
- Real-time data elements have appropriate update indicators

### 4. Adjust or Approve
If the result does not match the design system or looks visually wrong:
- Make the adjustment
- Re-screenshot
- Re-evaluate
- Repeat until satisfactory

If the result matches the design system and looks clean, move to the next change.

**Do NOT ask the user for approval on individual visual tweaks.** The design
system is the authority. Only escalate to the user when:
- A design system rule conflicts with functionality
- The change fundamentally alters the page layout or information hierarchy
- Multiple valid approaches exist with meaningfully different aesthetics

## Screenshot Techniques

### Full Page Capture
```
browser_navigate → target URL
browser_take_screenshot
```

### Responsive Testing
```
browser_resize → width: 1920, height: 1080  (desktop)
browser_take_screenshot
browser_resize → width: 1366, height: 768   (laptop)
browser_take_screenshot
browser_resize → width: 768, height: 1024   (tablet)
browser_take_screenshot
```

### Component Isolation
To evaluate a specific component, use the browser snapshot tool to identify
the element, then evaluate its rendered appearance in the full screenshot.

### Dark Theme Verification
The UI is dark-theme-only. Verify that:
- Text is readable against dark backgrounds
- Panel borders are subtle but visible
- Active/hover states are distinguishable
- Status colors pop against the dark canvas

## What "Good" Looks Like

### Metric Cards
- Large numeric value (24-32px, bold, white)
- Small label below (12px, muted gray)
- Optional sparkline in top-right corner
- Subtle border or background differentiation from canvas
- Consistent padding (16px internal)

### Data Tables
- Header row with muted text, no heavy borders
- Alternating row backgrounds (subtle, 2-3% opacity difference)
- Sortable columns indicated by caret icons
- Monospace font for numeric data
- Status badges with appropriate colors

### Live Feeds
- Newest items at top
- Timestamp in muted color
- Event type badges with semantic colors
- Smooth entry animation (fade-in or slide)
- Auto-scroll with pause-on-hover

### Overall Layout
- Fixed sidebar or top nav (not both)
- Content area uses CSS Grid for panel arrangement
- Panels have consistent border-radius (8px)
- Spacing between panels: 16px gap
- No horizontal scroll at 1366px+

## Additional Resources

### Reference Files

Consult these for detailed specifications:

- **`references/design-system.md`** - Complete color palette, typography scale,
  spacing system, component specifications, and CSS variable definitions
- **`references/visual-qa-checklist.md`** - Step-by-step checklist to run after
  completing a visual change, covering accessibility, responsiveness, and polish

### Using the local-web Skill

If Playwright MCP is unavailable, invoke the `local-web` skill as an
alternative for accessing local development servers and taking screenshots.

## Anti-Patterns

- **Working blind**: Never make more than 2-3 CSS changes without screenshotting
- **Asking for color opinions**: The design system defines the palette; use it
- **Ignoring contrast**: Always verify text readability on dark backgrounds
- **Pixel-pushing without context**: Check the full page, not just the edited component
- **Forgetting responsive**: Test at least desktop (1920) and laptop (1366) widths
