#!/usr/bin/env python3
"""
gh_docs_to_pdf.py

Combine all Markdown docs (README.md and *.md) from a GitHub repository
into a single PDF. Optionally include the repository's Wiki and GitHub Pages.

Features
--------
- Lists repo files via Git Trees (recursive) API for efficiency.
- Fetches raw Markdown via raw.githubusercontent.com.
- Converts Markdown → HTML and merges to a single HTML with a generated TOC.
- Renders HTML → PDF with WeasyPrint.
- BONUS: Includes Wiki pages (by cloning the .wiki.git) if requested.
- BONUS: Crawls GitHub Pages (auto-guess or provided URL) and appends HTML pages.

Requirements
------------
pip install requests markdown-it-py[linkify] weasyprint beautifulsoup4

Notes & References
------------------
- Git Trees API (recursive listing): https://docs.github.com/en/rest/git/trees?apiVersion=2022-11-28#get-a-tree  (recursive=1)
- Repo contents & raw URLs:
  * https://docs.github.com/en/rest/repos/contents
  * https://raw.githubusercontent.com/<owner>/<repo>/<branch>/<path>
- Wikis are separate git repos: append '.wiki.git'
  * https://gist.github.com/subfuzion/0d3f19c4f780a7d75ba2
- GitHub Pages basics and URLs:
  * https://docs.github.com/en/pages/quickstart
  * https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site
- WeasyPrint (HTML → PDF): https://weasyprint.org/

CLI Flags follow single-letter + long-form convention.
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Dict, Set
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.extensions.footnote import footnote_plugin
from markdown_it.extensions.tasklists import tasklists_plugin
from markdown_it.extensions.deflist import deflist_plugin
from markdown_it.extensions.container import container_plugin

# WeasyPrint
from weasyprint import HTML, CSS

# ----------------------------
# Helpers & Data Structures
# ----------------------------

GITHUB_API = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"

MD_EXTENSIONS = (".md", ".markdown", ".mdown", ".mkdn", ".mkd", ".mdx")
DEFAULT_BRANCH_FALLBACKS = ["main", "master"]  # Used if branch not detectable

USER_AGENT = "gh-docs-to-pdf/1.0 (https://github.com)"

@dataclass
class RepoSpec:
    owner: str
    repo: str
    branch: Optional[str] = None


def parse_repo_arg(repo: str) -> RepoSpec:
    """
    Accepts:
      - 'owner/repo'
      - full https URL like 'https://github.com/owner/repo' or 'https://github.com/owner/repo/tree/branch'
    Returns RepoSpec(owner, repo, optional branch)
    """
    if repo.startswith("http://") or repo.startswith("https://"):
        u = urlparse(repo)
        parts = [p for p in u.path.strip("/").split("/") if p]
        if len(parts) < 2:
            raise ValueError(f"Could not parse owner/repo from URL: {repo}")
        owner, name = parts[0], parts[1]
        branch = None
        # Handle .../tree/<branch>
        if len(parts) >= 4 and parts[2] == "tree":
            branch = parts[3]
        return RepoSpec(owner=owner, repo=name, branch=branch)
    # owner/repo
    if "/" not in repo:
        raise ValueError("Repo must be in form 'owner/repo' or a GitHub URL.")
    owner, name = repo.split("/", 1)
    return RepoSpec(owner=owner, repo=name, branch=None)


def github_headers(token: Optional[str]) -> Dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def detect_default_branch(spec: RepoSpec, token: Optional[str]) -> str:
    """Ask the repo API for default branch; fall back to common names."""
    url = f"{GITHUB_API}/repos/{spec.owner}/{spec.repo}"
    r = requests.get(url, headers=github_headers(token), timeout=30)
    if r.status_code == 200:
        data = r.json()
        default_branch = data.get("default_branch")
        if default_branch:
            return default_branch
    # Fallbacks if API limited or unknown
    for b in DEFAULT_BRANCH_FALLBACKS:
        if verify_branch_exists(spec, b, token):
            return b
    raise RuntimeError("Could not determine default branch; use --branch to specify explicitly.")


def verify_branch_exists(spec: RepoSpec, branch: str, token: Optional[str]) -> bool:
    url = f"{GITHUB_API}/repos/{spec.owner}/{spec.repo}/branches/{branch}"
    r = requests.get(url, headers=github_headers(token), timeout=30)
    return r.status_code == 200


def list_repo_tree(spec: RepoSpec, branch: str, token: Optional[str]) -> List[Dict]:
    """
    Use Git Trees API to get full file list (recursive).
    https://docs.github.com/en/rest/git/trees?apiVersion=2022-11-28#get-a-tree
    """
    # Need the branch commit SHA first
    ref_url = f"{GITHUB_API}/repos/{spec.owner}/{spec.repo}/git/refs/heads/{branch}"
    rr = requests.get(ref_url, headers=github_headers(token), timeout=30)
    if rr.status_code != 200:
        raise RuntimeError(f"Failed to get ref for branch '{branch}': {rr.status_code} {rr.text}")
    sha = rr.json()["object"]["sha"]

    tree_url = f"{GITHUB_API}/repos/{spec.owner}/{spec.repo}/git/trees/{sha}?recursive=1"
    tr = requests.get(tree_url, headers=github_headers(token), timeout=60)
    if tr.status_code != 200:
        raise RuntimeError(f"Failed to fetch tree: {tr.status_code} {tr.text}")
    data = tr.json()
    return data.get("tree", [])


def is_markdown_path(path: str) -> bool:
    p = path.lower()
    if p.endswith("readme") or p.endswith("readme.txt"):
        return True
    if p.endswith(MD_EXTENSIONS):
        return True
    return False


def fetch_raw_markdown(spec: RepoSpec, branch: str, path: str, token: Optional[str]) -> Optional[str]:
    """
    Fetch raw markdown via raw.githubusercontent.com
    Unauthenticated works for public; private requires token via API proxy (not covered here).
    Docs & patterns for raw URLs: discussions & SO refs.
    """
    # e.g. https://raw.githubusercontent.com/<owner>/<repo>/<branch>/<path>
    url = f"{RAW_BASE}/{spec.owner}/{spec.repo}/{branch}/{path}"
    headers = {"User-Agent": USER_AGENT}
    # (Raw endpoint doesn’t support token header for private repos; for private,
    # you’d need to use contents API and base64 decode. For public, this is fine.)
    r = requests.get(url, headers=headers, timeout=60)
    if r.status_code == 200:
        return r.text
    return None


def build_md_parser() -> MarkdownIt:
    """Markdown-it with a few helpful plugins for GitHub-flavored niceties."""
    md = (
        MarkdownIt("commonmark", {"linkify": True, "html": False})
        .use(footnote_plugin)
        .use(tasklists_plugin)
        .use(deflist_plugin)
        .use(container_plugin, "note")
        .use(container_plugin, "warning")
    )
    return md


def sanitize_title_from_path(path: str) -> str:
    name = Path(path).name
    return re.sub(r"[_\-]+", " ", name)


def md_to_html(md_text: str, rel_base_url: Optional[str] = None) -> str:
    """
    Convert Markdown to HTML. Optionally rewrite relative links to absolute if a base is provided.
    """
    parser = build_md_parser()
    html_body = parser.render(md_text)

    if rel_base_url:
        soup = BeautifulSoup(html_body, "html.parser")

        # Fix relative links and images
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not bool(urlparse(href).netloc) and not href.startswith("#"):
                a["href"] = urljoin(rel_base_url, href)
        for img in soup.find_all("img", src=True):
            src = img["src"]
            if not bool(urlparse(src).netloc) and not src.startswith("data:"):
                img["src"] = urljoin(rel_base_url, src)

        html_body = str(soup)

    return html_body


def wrap_section_html(title: str, anchor: str, body_html: str) -> str:
    return f"""
<section id="{html.escape(anchor)}" class="doc-section">
  <h1>{html.escape(title)}</h1>
  {body_html}
</section>
"""


def make_toc(entries: List[Tuple[str, str]]) -> str:
    # entries: list of (title, anchor)
    items = "\n".join(
        f'<li><a href="#{html.escape(anchor)}">{html.escape(title)}</a></li>'
        for title, anchor in entries
    )
    return f"""
<nav id="toc">
  <h1>Table of Contents</h1>
  <ol>
    {items}
  </ol>
</nav>
"""


def render_html_document(title: str, toc_html: str, sections_html: str) -> str:
    css = """
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; line-height: 1.45; }
    #toc h1 { font-size: 1.6rem; margin-bottom: 0.5rem; }
    #toc ol { padding-left: 1.2rem; }
    section.doc-section { page-break-inside: avoid; margin-top: 2rem; }
    section.doc-section h1 { font-size: 1.5rem; border-bottom: 1px solid #ccc; padding-bottom: 0.2rem; }
    pre, code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; }
    pre { background: #f7f7f7; padding: 0.8rem; border: 1px solid #eee; overflow: auto; }
    img { max-width: 100%; }
    """
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>{css}</style>
</head>
<body>
  <header>
    <h1>{html.escape(title)}</h1>
  </header>
  {toc_html}
  {sections_html}
</body>
</html>
"""


def weasyprint_html_to_pdf(html_str: str, out_path: Path) -> None:
    HTML(string=html_str).write_pdf(str(out_path))


def crawl_github_pages(start_url: str, max_pages: int = 25, same_host_only: bool = True) -> List[Tuple[str, str]]:
    """
    Crawl a GitHub Pages site (or custom domain) and return list of (title, html) pages.
    Simple BFS crawler limited to same host and <= max_pages. Deduplicates by URL path.
    """
    visited: Set[str] = set()
    out: List[Tuple[str, str]] = []

    try:
        base = urlparse(start_url)
    except Exception:
        return out

    q: List[str] = [start_url]
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    while q and len(out) < max_pages:
        url = q.pop(0)
        if url in visited:
            continue
        visited.add(url)

        try:
            r = session.get(url, timeout=30)
            if r.status_code != 200 or "text/html" not in r.headers.get("Content-Type", ""):
                continue
        except Exception:
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else url
        # Basic cleanup to remove script/style
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        body_html = str(soup.find("body")) if soup.body else r.text

        out.append((title, body_html))

        # Enqueue links
        for a in soup.find_all("a", href=True):
            link = urljoin(url, a["href"])
            lu = urlparse(link)
            if same_host_only and lu.netloc and lu.netloc != base.netloc:
                continue
            # basic doc-ish pages only
            if lu.fragment:
                link = link.split("#", 1)[0]
            if link not in visited and link.startswith(f"{base.scheme}://{base.netloc}"):
                q.append(link)

    return out


def guess_pages_url(spec: RepoSpec) -> str:
    """
    Guess GitHub Pages URL for a project site:
      https://<owner>.github.io/<repo>/
    This is a heuristic; users can override with --pages_url.
    """
    return f"https://{spec.owner}.github.io/{spec.repo}/"


def clone_wiki_to_tmp(spec: RepoSpec) -> Optional[Path]:
    """
    Clone the wiki repo (if exists) to a temp directory and return path, else None.
    Wiki clone pattern: https://github.com/<owner>/<repo>.wiki.git
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="gh_wiki_"))
    wiki_url = f"https://github.com/{spec.owner}/{spec.repo}.wiki.git"
    try:
        subprocess.run(["git", "clone", "--depth", "1", wiki_url, str(tmpdir)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return tmpdir
    except subprocess.CalledProcessError:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None


def collect_markdown_from_wiki(wiki_dir: Path) -> List[Tuple[str, str]]:
    """
    Return list of (relative_path, markdown_text) from the wiki clone.
    """
    out: List[Tuple[str, str]] = []
    for p in wiki_dir.rglob("*"):
        if p.is_file() and is_markdown_path(p.name):
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
                rel = str(p.relative_to(wiki_dir))
                out.append((rel, text))
            except Exception:
                continue
    return out


def main():
    ap = argparse.ArgumentParser(
        description="Combine GitHub repo Markdown (and optionally Wiki + Pages) into a single PDF.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("-r", "--repo", required=True, help="Repository: owner/repo OR full GitHub URL.")
    ap.add_argument("-o", "--output", required=True, help="Output PDF path.")
    ap.add_argument("-b", "--branch", help="Branch name (if omitted, detect default branch).")
    ap.add_argument("-t", "--token", help="GitHub token (optional; increases rate limits for API calls).")
    ap.add_argument("-w", "--include_wiki", action="store_true", help="Include GitHub Wiki pages if present.")
    ap.add_argument("-p", "--include_pages", action="store_true", help="Include GitHub Pages site content (best-effort).")
    ap.add_argument("-u", "--pages_url", help="Explicit GitHub Pages (or custom) URL to crawl. If omitted and -p set, guess https://<owner>.github.io/<repo>/")
    ap.add_argument("-m", "--max_pages", type=int, default=25, help="Max pages to crawl for GitHub Pages.")
    ap.add_argument("-k", "--keep_temp", action="store_true", help="Keep temporary directories (for debugging).")
    ap.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")
    args = ap.parse_args()

    spec = parse_repo_arg(args.repo)
    token = args.token

    # Determine branch
    branch = args.branch or spec.branch
    if not branch:
        branch = detect_default_branch(spec, token)

    if args.verbose:
        print(f"[INFO] Repo: {spec.owner}/{spec.repo}  Branch: {branch}")

    # 1) Gather Markdown from repo
    tree = list_repo_tree(spec, branch, token)
    md_paths = [item["path"] for item in tree if item.get("type") == "blob" and is_markdown_path(item.get("path", ""))]

    if args.verbose:
        print(f"[INFO] Found {len(md_paths)} markdown files via Git Trees.")

    md_docs: List[Tuple[str, str, str]] = []  # (title, anchor, html_body)
    toc: List[Tuple[str, str]] = []

    for path in sorted(md_paths, key=lambda p: p.lower()):
        md_text = fetch_raw_markdown(spec, branch, path, token)
        if not md_text:
            continue
        title = sanitize_title_from_path(path)
        anchor = re.sub(r"[^a-zA-Z0-9\-]+", "-", title.lower()).strip("-")
        # Base for relative links to point to HTML rendered at GitHub (fallback to repo tree)
        base_url = f"https://github.com/{spec.owner}/{spec.repo}/blob/{branch}/{path}"
        html_body = md_to_html(md_text, rel_base_url=base_url)
        md_docs.append((title, anchor, html_body))
        toc.append((title, anchor))

    # 2) (Optional) Wiki
    wiki_docs: List[Tuple[str, str, str]] = []
    if args.include_wiki:
        wiki_dir = clone_wiki_to_tmp(spec)
        if wiki_dir:
            if args.verbose:
                print(f"[INFO] Cloned wiki to {wiki_dir}")
            wiki_mds = collect_markdown_from_wiki(wiki_dir)
            for rel, md_text in sorted(wiki_mds, key=lambda t: t[0].lower()):
                title = sanitize_title_from_path(rel)
                anchor = f"wiki-{re.sub(r'[^a-zA-Z0-9\-]+','-', title.lower()).strip('-')}"
                base_url = f"https://github.com/{spec.owner}/{spec.repo}/wiki/{rel}"
                html_body = md_to_html(md_text, rel_base_url=base_url)
                wiki_docs.append((title, anchor, html_body))
                toc.append((f"[Wiki] {title}", anchor))
            if not args.keep_temp:
                shutil.rmtree(wiki_dir, ignore_errors=True)
        else:
            if args.verbose:
                print("[WARN] Wiki clone failed or does not exist; skipping wiki.")

    # 3) (Optional) GitHub Pages
    pages_docs: List[Tuple[str, str, str]] = []
    if args.include_pages:
        start_url = args.pages_url or guess_pages_url(spec)
        if args.verbose:
            print(f"[INFO] Crawling Pages: {start_url} (max {args.max_pages} pages)")
        pages = crawl_github_pages(start_url, max_pages=args.max_pages, same_host_only=True)
        for idx, (title, body_html) in enumerate(pages, start=1):
            safe_anchor = f"pages-{idx}"
            pages_docs.append((f"[Pages] {title}", safe_anchor, body_html))
            toc.append((f"[Pages] {title}", safe_anchor))

    # 4) Merge everything into a single HTML document
    sections = []
    for title, anchor, body in md_docs + wiki_docs + pages_docs:
        sections.append(wrap_section_html(title, anchor, body))
    combined_sections = "\n".join(sections)
    title = f"{spec.owner}/{spec.repo} Documentation"
    toc_html = make_toc(toc)
    full_html = render_html_document(title, toc_html, combined_sections)

    # 5) Render to PDF
    out_path = Path(args.output).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    weasyprint_html_to_pdf(full_html, out_path)

    if args.verbose:
        print(f"[DONE] Wrote PDF → {out_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INTERRUPTED]")
        sys.exit(130)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
