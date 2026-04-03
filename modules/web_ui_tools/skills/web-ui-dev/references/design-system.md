# Web UI Design System

## Color Palette

### CSS Variables
```css
:root {
  /* Canvas */
  --bg-primary: #0f0f0f;
  --bg-secondary: #1a1a2e;
  --bg-panel: #16213e;
  --bg-panel-hover: #1a2744;
  --bg-input: #0a0a1a;

  /* Text */
  --text-primary: #e8e8e8;
  --text-secondary: #a0a0b0;
  --text-muted: #6b6b7b;
  --text-accent: #00d4aa;

  /* Borders */
  --border-subtle: rgba(255, 255, 255, 0.06);
  --border-panel: rgba(255, 255, 255, 0.1);
  --border-active: #00d4aa;

  /* Status Colors */
  --color-success: #10b981;
  --color-warning: #f59e0b;
  --color-error: #ef4444;
  --color-info: #3b82f6;

  /* Metric Highlights */
  --metric-value: #ffffff;
  --metric-delta-up: #10b981;
  --metric-delta-down: #ef4444;

  /* Chart / Sparkline */
  --sparkline-stroke: #00d4aa;
  --sparkline-fill: rgba(0, 212, 170, 0.1);
  --chart-grid: rgba(255, 255, 255, 0.05);

  /* Interactive */
  --hover-bg: rgba(0, 212, 170, 0.08);
  --active-bg: rgba(0, 212, 170, 0.15);
  --focus-ring: 0 0 0 2px rgba(0, 212, 170, 0.4);
}
```

## Typography

### Font Stack
```css
--font-ui: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
--font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
```

### Scale
| Token         | Size  | Weight | Use                        |
|---------------|-------|--------|----------------------------|
| `--text-xs`   | 11px  | 400    | Timestamps, badges         |
| `--text-sm`   | 13px  | 400    | Secondary labels, captions |
| `--text-base` | 15px  | 400    | Body text, table cells     |
| `--text-lg`   | 18px  | 500    | Section headers            |
| `--text-xl`   | 24px  | 600    | Panel titles               |
| `--text-2xl`  | 32px  | 700    | Metric values              |
| `--text-3xl`  | 40px  | 700    | Hero metrics               |

### Rules
- UI elements: `--font-ui`
- Data values, code, logs: `--font-mono`
- Line height: 1.5 for body, 1.2 for headings and metrics
- Letter spacing: -0.01em for large text, normal for body

## Spacing

### Grid
All spacing uses a **4px base unit**:
| Token  | Value | Use                              |
|--------|-------|----------------------------------|
| `--s1` | 4px   | Tight internal padding           |
| `--s2` | 8px   | Badge padding, icon gaps         |
| `--s3` | 12px  | List item padding                |
| `--s4` | 16px  | Panel internal padding, card gap |
| `--s5` | 20px  | Section spacing                  |
| `--s6` | 24px  | Panel-to-panel gap               |
| `--s8` | 32px  | Page margin, major sections      |

### Panel Layout
- Panel gap: `--s4` (16px)
- Panel padding: `--s4` (16px)
- Panel border-radius: 8px
- Panel border: 1px solid `--border-panel`
- Panel background: `--bg-panel`

## Component Specifications

### Metric Card
```
┌─────────────────────────┐
│  Label          ╱╲╱╲╱╲  │  ← sparkline (optional)
│  1,247                   │  ← value: --text-2xl, --metric-value
│  +12.3%                  │  ← delta: --text-sm, green/red
└─────────────────────────┘
```
- Width: min 200px, flex within grid
- Height: auto, min ~100px
- Background: `--bg-panel`
- Border-radius: 8px
- Padding: 16px

### Data Table
```
┌──────────────────────────────────────────┐
│  Name ▲    Status     Value    Updated   │  ← header: --text-sm, --text-muted
├──────────────────────────────────────────┤
│  Task A    ● Active   847      2m ago    │  ← row: --text-base
│  Task B    ● Done     1.2k     5m ago    │  ← alt row: +2% white opacity
│  Task C    ● Failed   0        12m ago   │
└──────────────────────────────────────────┘
```
- Header: uppercase, letter-spacing 0.05em, --text-muted
- Rows: hover highlight with --hover-bg
- Sort indicator: ▲/▼ next to active column
- Status dots: 8px circles with semantic colors
- Numeric values: --font-mono, right-aligned

### Status Badge
```css
.badge {
  font-size: var(--text-xs);
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 4px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.badge-success { background: rgba(16, 185, 129, 0.15); color: #10b981; }
.badge-warning { background: rgba(245, 158, 11, 0.15); color: #f59e0b; }
.badge-error   { background: rgba(239, 68, 68, 0.15);  color: #ef4444; }
.badge-info    { background: rgba(59, 130, 246, 0.15);  color: #3b82f6; }
```

### Sidebar Navigation
- Width: 220px fixed (collapsible to 56px icon-only)
- Background: `--bg-secondary`
- Active item: left border 3px `--border-active` + `--active-bg`
- Items: 40px height, 16px horizontal padding
- Icons: 20px, --text-muted (active: --text-accent)
- Section headers: --text-xs, --text-muted, uppercase

### Live Feed / Activity Log
- Newest at top
- Each entry: timestamp (--text-xs, --text-muted) + icon + message
- Timestamp format: relative ("2m ago") with hover showing absolute
- Max visible: 50 entries, virtual scroll for more
- Entry animation: opacity 0->1 over 200ms

## Layout Grid

### Dashboard Grid
```css
.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--s4);
  padding: var(--s4);
}
```

### Breakpoints
| Name     | Width   | Columns | Notes                    |
|----------|---------|---------|--------------------------|
| Desktop  | 1920px+ | 4       | Full layout              |
| Laptop   | 1366px  | 3       | Slightly compressed      |
| Tablet   | 768px   | 2       | Stack panels             |
| Mobile   | <768px  | 1       | Single column, no sidebar|

## Accessibility

- Minimum contrast ratio: 4.5:1 for text, 3:1 for large text
- Focus indicators: `--focus-ring` on all interactive elements
- No information conveyed by color alone (use icons + text)
- Keyboard navigable: Tab order follows visual order

## Animation

- Transitions: 150ms ease-out for hover/active states
- Panel entry: fade-in 200ms
- Data updates: brief flash (100ms highlight then fade)
- No animation on initial load (prevent layout shift)
- Respect `prefers-reduced-motion`
