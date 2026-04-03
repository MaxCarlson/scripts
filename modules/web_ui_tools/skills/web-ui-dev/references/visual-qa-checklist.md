# Visual QA Checklist

Run through this checklist after completing any visual change. Take a screenshot
at each step and evaluate before proceeding.

## 1. Immediate Verification

After every CSS/HTML/JS change:

- [ ] Take screenshot at default viewport (1920x1080)
- [ ] Edited component renders without layout breakage
- [ ] No elements overflow their containers
- [ ] Text is readable (white/light on dark backgrounds)
- [ ] No unexpected scrollbars appeared

## 2. Color Compliance

- [ ] Background colors match design system palette
- [ ] Text colors use --text-primary, --text-secondary, or --text-muted
- [ ] Status indicators use semantic colors (success/warning/error/info)
- [ ] No pure white (#ffffff) backgrounds (too bright for dark theme)
- [ ] Accent color (--text-accent / #00d4aa) used sparingly for emphasis
- [ ] Hover/active states use the defined opacity overlays

## 3. Typography

- [ ] UI text uses --font-ui (Inter/system)
- [ ] Data values use --font-mono (JetBrains Mono)
- [ ] Font sizes follow the type scale (no arbitrary sizes)
- [ ] Headings use appropriate weight (500-700)
- [ ] Body text is 15px minimum for readability

## 4. Spacing & Layout

- [ ] Padding follows 4px grid (4, 8, 12, 16, 24, 32)
- [ ] Panel gaps are consistent (16px)
- [ ] Content doesn't touch panel edges (min 16px padding)
- [ ] Vertical rhythm is consistent within panels
- [ ] Grid layout fills available space without gaps

## 5. Components

### Metric Cards
- [ ] Value is the most prominent element (large, bold)
- [ ] Label is smaller and muted
- [ ] Sparkline (if present) doesn't dominate the card
- [ ] Card has consistent dimensions with siblings

### Tables
- [ ] Header row is visually distinct (muted, uppercase)
- [ ] Rows have subtle alternating backgrounds
- [ ] Numeric columns are right-aligned
- [ ] Status dots/badges are sized correctly (8px dots, xs text badges)

### Navigation
- [ ] Active item clearly indicated (accent color border/background)
- [ ] Hover states visible but not distracting
- [ ] Icons aligned with text labels

## 6. Responsive (when layout changes are made)

- [ ] Screenshot at 1920px - full layout, 4 columns
- [ ] Screenshot at 1366px - 3 columns, nothing clipped
- [ ] Screenshot at 768px - 2 columns or stacked
- [ ] No horizontal scrollbar at any width above 768px

## 7. Real-Time Elements

- [ ] WebSocket connection indicator visible
- [ ] Auto-updating values don't cause layout shifts
- [ ] Loading states shown for pending data
- [ ] Error states displayed gracefully (not raw errors)

## 8. Final Polish

- [ ] Border-radius consistent (8px panels, 4px badges)
- [ ] Shadows subtle or absent (dark themes need minimal shadow)
- [ ] Transitions smooth (150ms hover, 200ms panel entry)
- [ ] No orphaned or placeholder text visible
- [ ] Favicon loads (no browser default icon)

## Decision Framework

### Fix Without Asking
- Color doesn't match design system palette
- Spacing violates the 4px grid
- Typography uses wrong font family or arbitrary size
- Contrast ratio below 4.5:1
- Layout breaks at standard breakpoints
- Component doesn't match spec in design-system.md

### Escalate to User
- Choosing between two valid layout arrangements
- Adding or removing entire sections/panels
- Changing the information hierarchy
- Introducing new component types not in the design system
- Trade-offs between data density and readability
