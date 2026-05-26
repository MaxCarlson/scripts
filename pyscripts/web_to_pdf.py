#!/usr/bin/env python3
"""
web_to_pdf.py — Download PDFs of linked pages from a listing/index URL.

Renders pages with full JavaScript support (Playwright/Chromium), capturing
interactive visualizations (D3, SVG, etc.) in their default rendered state.
True browser interactivity is not preserved in PDFs — JS-driven elements
are captured as static renders at the moment of export.

Install:
    pip install playwright pypdf
    playwright install chromium

    # Or with conda:
    conda install -c conda-forge playwright pypdf
    playwright install chromium

Usage:
    python web_to_pdf.py -u https://transformer-circuits.pub/
    python web_to_pdf.py -u https://transformer-circuits.pub/ -p 1,-1 -o ./papers
    python web_to_pdf.py -u https://transformer-circuits.pub/ -p 3,10 --newest-first
    python web_to_pdf.py -u https://transformer-circuits.pub/ --headed  # debug mode
"""
__version__ = "0.1.0"

import argparse
import asyncio
import io
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    from playwright.async_api import BrowserContext, Page, async_playwright
except ImportError:
    sys.exit(
        "Missing dependency: pip install playwright && playwright install chromium"
    )

try:
    import pypdf
except ImportError:
    sys.exit("Missing dependency: pip install pypdf")


# ── Range parsing ──────────────────────────────────────────────────────────────

def parse_range(range_str: str, total: int) -> tuple[int, int | None]:
    """
    Parse a 'START,END' range string with [START, END) semantics.

    - 1-based indexing for positive values.
    - Negative END values count from end; -1 is the sentinel for 'include all
      remaining' (i.e. one past the last element), making [1,-1) == all items.
    - Other negative values behave like Python slice indices.

    Examples:
        "1,-1"  → all items          → arr[0:]
        "1,10"  → first 9 articles   → arr[0:9]
        "5,-1"  → 5th onward         → arr[4:]
        "2,8"   → articles 2–7       → arr[1:7]
    """
    try:
        parts = range_str.split(",")
        if len(parts) != 2:
            raise ValueError
        start, end = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        raise ValueError(
            f"Invalid range {range_str!r}: expected 'START,END' "
            "(e.g. '1,-1' for all, '1,10' for first 9)"
        )

    # Convert 1-based positive start → 0-based Python index
    start_idx = (start - 1) if start > 0 else max(0, total + start)

    # -1 as end = sentinel for 'include everything remaining'
    if end == -1:
        end_idx = None
    elif end > 0:
        # [1,5) includes 1,2,3,4 → Python arr[0:4] → end - 1
        end_idx = end - 1
    else:
        # e.g. -2 means 'exclude last item' → total + (-2)
        end_idx = total + end

    return start_idx, end_idx


# ── Link discovery ─────────────────────────────────────────────────────────────

_MONTH_RE_JS = (
    r"(january|february|march|april|may|june|july|august|"
    r"september|october|november|december"
    r"|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\\.?\\s+\\d{4}"
)

_DISCOVER_JS = f"""
(sameHost) => {{
    const results = [];
    const seen = new Set();
    const monthRe = new RegExp(
        "\\\\b{_MONTH_RE_JS}\\\\b", "i"
    );

    // Walk up ancestors + preceding siblings looking for a month+year date
    function findDate(el) {{
        let node = el;
        for (let depth = 0; depth < 7; depth++) {{
            node = node.parentElement;
            if (!node) break;

            // Check preceding siblings at each ancestor level
            let sib = node.previousElementSibling;
            while (sib) {{
                const m = monthRe.exec(sib.innerText || "");
                if (m) return m[0];
                sib = sib.previousElementSibling;
            }}

            // Also check the ancestor's own direct text (may contain inline date)
            const direct = Array.from(node.childNodes)
                .filter(n => n.nodeType === Node.TEXT_NODE)
                .map(n => n.textContent)
                .join(" ");
            const dm = monthRe.exec(direct);
            if (dm) return dm[0];
        }}
        return "";
    }}

    document.querySelectorAll("a[href]").forEach(a => {{
        try {{
            const url = new URL(a.href);
            if (url.hostname !== sameHost) return;          // different domain
            if (url.pathname.length <= 1) return;           // root / home link
            if (url.hash && url.pathname === window.location.pathname) return; // anchor-only
            if (seen.has(url.href)) return;
            seen.add(url.href);

            results.push({{
                url:      url.href,
                title:    (a.innerText.trim() || a.getAttribute("title") || url.pathname).substring(0, 120),
                date_raw: findDate(a),
            }});
        }} catch {{}}
    }});

    return results;
}}
"""


async def discover_links(page: Page, base_url: str) -> list[dict]:
    """Return list of {url, title, date_raw} dicts found on the listing page."""
    same_host = urlparse(base_url).netloc
    return await page.evaluate(_DISCOVER_JS, same_host)


# ── Date parsing ───────────────────────────────────────────────────────────────

_DATE_FORMATS = (
    "%B %Y",     # January 2025
    "%b %Y",     # Jan 2025
    "%b. %Y",    # Jan. 2025
    "%Y-%m-%d",  # 2025-01-15
    "%Y/%m/%d",
)


def parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    # Fallback: extract "Month YYYY" with regex
    m = re.search(r"(\w+\.?)\s+(\d{4})", raw, re.IGNORECASE)
    if m:
        month = m.group(1).rstrip(".")
        year  = m.group(2)
        for fmt in ("%B %Y", "%b %Y"):
            try:
                return datetime.strptime(f"{month} {year}", fmt)
            except ValueError:
                pass
    return None


# ── PDF helpers ────────────────────────────────────────────────────────────────

def count_pdf_pages(pdf_bytes: bytes) -> int:
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return len(reader.pages)


def sanitize(name: str, max_len: int = 60) -> str:
    """Make a string safe for use as a cross-platform filename component."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    name = re.sub(r"[\s_]+", "_", name.strip())
    return name[:max_len].strip("_")


async def render_pdf(
    page: Page,
    url: str,
    *,
    render_wait_ms: int = 2000,
    timeout_ms: int = 60_000,
) -> bytes:
    """
    Navigate to URL, trigger lazy-loaded content by scrolling, then export PDF.

    Notes on interactive content:
      - SVG / D3 visualizations are captured in their initial rendered state.
      - Canvas / WebGL content may be blank in headless mode; use --headed to
        check if a specific page fails to render correctly.
    """
    await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
    await page.wait_for_timeout(render_wait_ms)

    # Scroll through the page to trigger lazy-loaded images & deferred JS
    await page.evaluate("""
        async () => {
            const delay = ms => new Promise(r => setTimeout(r, ms));
            let prev = -1;
            for (let guard = 0; guard < 50; guard++) {
                const curr = document.documentElement.scrollHeight;
                if (curr === prev) break;
                prev = curr;
                window.scrollBy(0, window.innerHeight * 2);
                await delay(250);
            }
            window.scrollTo(0, 0);
            await delay(600);
        }
    """)

    return await page.pdf(
        format="A4",
        print_background=True,
        margin={
            "top":    "1.5cm",
            "bottom": "1.5cm",
            "left":   "1.5cm",
            "right":  "1.5cm",
        },
    )


# ── Core runner ────────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not args.headed)
        context: BrowserContext = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        # ── Load listing page ──────────────────────────────────────────────────
        print(f"[+] Loading listing page: {args.url}")
        await page.goto(args.url, wait_until="networkidle", timeout=60_000)
        await page.wait_for_timeout(1500)

        raw_links = await discover_links(page, args.url)
        print(f"[+] Discovered {len(raw_links)} candidate links")

        # ── Attach parsed dates ────────────────────────────────────────────────
        for link in raw_links:
            link["date"] = parse_date(link["date_raw"])

        # Sort: dated entries by date, undated appended at the end
        dated   = [l for l in raw_links if l["date"]]
        undated = [l for l in raw_links if not l["date"]]
        dated.sort(key=lambda x: x["date"], reverse=args.newest_first)  # type: ignore[arg-type]
        ordered = dated + undated

        # ── Apply article range filter ─────────────────────────────────────────
        if args.pages:
            try:
                s, e = parse_range(args.pages, len(ordered))
            except ValueError as exc:
                print(f"[!] {exc}", file=sys.stderr)
                await browser.close()
                return 1
            ordered = ordered[s:e]
            print(f"[+] After range filter [{args.pages}): {len(ordered)} articles")

        if not ordered:
            print("[!] No articles to process after filtering.")
            await browser.close()
            return 0

        print(f"[+] Processing {len(ordered)} articles  →  {output_dir}/\n")

        saved, skipped, failed = 0, 0, 0

        for idx, link in enumerate(ordered, start=1):
            url   = link["url"]
            title = link["title"] or urlparse(url).path.strip("/").replace("/", "_")
            date  = link["date"]
            label = date.strftime("%Y-%m") if date else "undated"

            filename = f"{idx:04d}_{label}_{sanitize(title)}.pdf"
            dest     = output_dir / filename
            prefix   = f"  [{idx:>{len(str(len(ordered)))}}/{len(ordered)}]"

            if dest.exists() and not args.force:
                print(f"{prefix} SKIP (exists)          {filename}")
                skipped += 1
                continue

            print(f"{prefix} Fetching …             {url}")
            t0 = time.monotonic()

            # Retry loop with exponential back-off
            pdf_bytes: bytes | None = None
            for attempt in range(1, args.retries + 2):
                try:
                    pdf_bytes = await render_pdf(
                        page,
                        url,
                        render_wait_ms=args.render_wait,
                        timeout_ms=args.timeout * 1_000,
                    )
                    break
                except Exception as exc:
                    if attempt > args.retries:
                        print(f"{prefix} ERROR (gave up): {exc}", file=sys.stderr)
                        break
                    wait = 2 ** attempt
                    print(f"{prefix} Retry {attempt}/{args.retries} (in {wait}s): {exc}")
                    await asyncio.sleep(wait)

            if pdf_bytes is None:
                failed += 1
                continue

            pages   = count_pdf_pages(pdf_bytes)
            elapsed = time.monotonic() - t0

            if pages < args.min_pages:
                print(f"{prefix} SKIP ({pages}p < {args.min_pages})      {filename}")
                skipped += 1
            else:
                dest.write_bytes(pdf_bytes)
                size_kb = len(pdf_bytes) // 1024
                print(
                    f"{prefix} SAVED "
                    f"({pages}p, {size_kb}KB, {elapsed:.1f}s)  {filename}"
                )
                saved += 1

            # Polite delay between requests
            if args.delay > 0 and idx < len(ordered):
                await asyncio.sleep(args.delay)

        await browser.close()

    # ── Summary ────────────────────────────────────────────────────────────────
    width = 60
    print(f"\n{'─' * width}")
    print(f"  Saved:   {saved}")
    print(f"  Skipped: {skipped}  (already exists or < {args.min_pages} pages)")
    print(f"  Failed:  {failed}")
    print(f"  Output:  {output_dir.resolve()}")
    print(f"{'─' * width}")
    return 0 if failed == 0 else 1


# ── CLI ────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="web_to_pdf",
        description=(
            "Download PDFs of linked pages from a listing/index URL.\n"
            "Pages are rendered with full JS support via Playwright/Chromium."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Range syntax  (-p / --pages):
  [START, END)  — 1-based inclusive start, exclusive end.
  Positive values are 1-based. END of -1 means 'include all remaining'
  (i.e. the sentinel for 'one past the last element').

  Examples:
    -p 1,-1     all articles   (same as omitting the flag)
    -p 1,10     first 9 articles
    -p 5,-1     articles 5 through the end
    -p 2,8      articles 2–7

File naming:
  {INDEX:04d}_{YYYY-MM}_{title}.pdf
  Index reflects sort order — oldest = 0001 by default.
  Undated articles are appended after all dated ones.

Examples:
  python web_to_pdf.py -u https://transformer-circuits.pub/
  python web_to_pdf.py -u https://transformer-circuits.pub/ -p 1,20 -o ./papers
  python web_to_pdf.py -u https://transformer-circuits.pub/ --newest-first --delay 1
  python web_to_pdf.py -u https://transformer-circuits.pub/ --headed --render-wait 4000
""",
    )

    ap.add_argument(
        "-u", "--url",
        required=True,
        metavar="URL",
        help="Listing/index page URL to scrape for article links",
    )
    ap.add_argument(
        "-p", "--pages",
        metavar="START,END",
        help=(
            "Article index range [START,END) — 1-based; "
            "-1 as END includes all remaining (default: all)"
        ),
    )
    ap.add_argument(
        "-o", "--output",
        default="./pdfs",
        metavar="DIR",
        help="Output directory for PDF files (default: ./pdfs)",
    )
    ap.add_argument(
        "--min-pages",
        type=int,
        default=2,
        metavar="N",
        help=(
            "Minimum number of PDF pages required to save (default: 2 — "
            "i.e. 'longer than 1 page')"
        ),
    )
    ap.add_argument(
        "--newest-first",
        action="store_true",
        help=(
            "Sort newest articles first — they receive the lowest index suffix. "
            "Default: oldest first."
        ),
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-download and overwrite even if the output file already exists",
    )
    ap.add_argument(
        "--delay",
        type=float,
        default=0.5,
        metavar="SECS",
        help="Seconds to wait between requests — be polite (default: 0.5)",
    )
    ap.add_argument(
        "--render-wait",
        type=int,
        default=2000,
        metavar="MS",
        help=(
            "Extra milliseconds to wait after page load for JS rendering "
            "(default: 2000). Increase for heavy interactive pages."
        ),
    )
    ap.add_argument(
        "--timeout",
        type=int,
        default=60,
        metavar="SECS",
        help="Per-page navigation timeout in seconds (default: 60)",
    )
    ap.add_argument(
        "--retries",
        type=int,
        default=2,
        metavar="N",
        help="Retry attempts per page on failure, with exponential back-off (default: 2)",
    )
    ap.add_argument(
        "--headed",
        action="store_true",
        help=(
            "Show the browser window. Useful for debugging pages that don't "
            "render correctly headless (e.g. WebGL content)."
        ),
    )

    return ap


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
