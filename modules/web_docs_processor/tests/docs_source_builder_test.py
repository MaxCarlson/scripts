from __future__ import annotations

import json
import shutil

import pytest

from web_docs_processor import docs_source_builder as dsb

EXPECTED_MAX_PAGES = 5
DOCS_SITE_DEFAULT_MAX_PAGES = 300
SINGLE_PAGE_PREFIX_DEPTH = 2
EXPLICIT_PREFIX_DEPTH = 4
EXPLICIT_MAX_PAGES = 42
URL_FILE_COMBINED_COUNT = 3
MANIFEST_MAX_PAGES = 50
MANIFEST_DELAY_SECONDS = 0.1
MANIFEST_TIMEOUT_SECONDS = 9.0
MANIFEST_MIN_CHARS = 25
MANIFEST_PATH = dsb.Path("out") / "test-manifest.json"
URL_FILE_PATH = dsb.Path("out") / "test-urls.txt"
OUTPUT_TEST_DIR = dsb.Path("out") / "test-output-formats"
URL_FILE_TEST_DIR = dsb.Path("out") / "test-url-file"
SINGLE_PAGE_EXAMPLE_URL = "https://example.com/guide"
DOCS_SITE_EXAMPLE_URL = "https://geminicli.com/docs/"
GITHUB_WIKI_EXAMPLE_URL = "https://github.com/Homebrew/brew/wiki"
GITHUB_PAGES_EXAMPLE_URL = "https://pytest-dev.github.io/pytest/"
SITEMAP_EXAMPLE_URL = "https://example.com/sitemap.xml"
DOCS_FIXTURE_BODY = """
<main>
    <h1>{title}</h1>
    <p>{title} body text for deterministic offline extraction.</p>
    <p>This paragraph makes the fixture long enough for markdown conversion.</p>
</main>
"""


def write_test_manifest(payload: dict[str, object]) -> dsb.Path:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(payload), encoding="utf-8")
    return MANIFEST_PATH


def write_test_url_file(content: str) -> dsb.Path:
    URL_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    URL_FILE_PATH.write_text(content, encoding="utf-8")
    return URL_FILE_PATH


def make_config(**overrides: object) -> dsb.CrawlConfig:
    values: dict[str, object] = {
        "urls": ["https://example.com/docs/start"],
        "output_path": "source.md",
        "output_format": "markdown",
        "title": "Example Docs",
        "input_format": "docs-site",
        "scope": "prefix",
        "include_patterns": [],
        "exclude_patterns": [],
        "max_pages": 10,
        "delay_seconds": 0.0,
        "timeout_seconds": 5.0,
        "split_pages": False,
        "dry_run": False,
        "render_js": False,
        "user_agent": dsb.DEFAULT_USER_AGENT,
        "min_chars": 10,
        "same_prefix_depth": 1,
        "keep_query": False,
        "write_manifest": True,
        "write_candidates": True,
        "url_file": None,
        "url_file_mode": None,
        "batch_seed_url": None,
    }
    values.update(overrides)
    values["output_path"] = dsb.Path(str(values["output_path"]))
    return dsb.CrawlConfig(**values)


def make_page(title: str = "Start Here") -> dsb.PageResult:
    return dsb.PageResult(
        url="https://example.com/docs/start",
        title=title,
        markdown="Body text",
        source_index=1,
        status_code=200,
        content_sha256="abc123",
        extracted_by="test",
    )


def page_html(title: str, nav_links: str = "") -> str:
    return f"""
<!doctype html>
<html>
    <head><title>{title}</title></head>
    <body>
        <nav>{nav_links}</nav>
        {DOCS_FIXTURE_BODY.format(title=title)}
    </body>
</html>
"""


def test_normalize_url_removes_fragments_queries_and_extra_slashes() -> None:
    assert dsb.normalize_url("HTTPS://Example.COM//docs/page/?utm=1#section") == "https://example.com/docs/page"


def test_normalize_url_can_keep_query() -> None:
    assert (
        dsb.normalize_url("https://example.com/docs/page?version=1#top", keep_query=True)
        == "https://example.com/docs/page?version=1"
    )


def test_infer_input_format_detects_known_site_shapes() -> None:
    assert dsb.infer_input_format(["https://github.com/org/repo/wiki/Home"], "auto") == "github-wiki"
    assert dsb.infer_input_format(["https://project.github.io/docs"], "auto") == "github-pages"
    assert dsb.infer_input_format(["https://example.com/sitemap.xml"], "auto") == "sitemap"
    assert dsb.infer_input_format(["https://example.com/docs"], "single-page") == "single-page"


def test_coerce_input_format_rejects_unknown_values() -> None:
    assert dsb.coerce_input_format("docs-site") == "docs-site"
    assert dsb.coerce_input_format("not-real") == "auto"


def test_default_scope_for_input_format() -> None:
    assert dsb.default_scope_for_input_format("single-page", None) == "single"
    assert dsb.default_scope_for_input_format("docs-site", None) == "prefix"
    assert dsb.default_scope_for_input_format("sitemap", None) == "domain"
    assert dsb.default_scope_for_input_format("docs-site", "domain") == "domain"


def test_context_defaults_for_docs_site() -> None:
    urls = ["https://geminicli.com/docs"]

    assert dsb.default_same_prefix_depth(urls, "docs-site", None) == 1
    assert dsb.default_max_pages_for_input_format("docs-site", None) == DOCS_SITE_DEFAULT_MAX_PAGES
    assert dsb.default_render_js_for_input_format("docs-site", None)


def test_context_defaults_for_single_page() -> None:
    urls = ["https://example.com/docs/page"]

    assert dsb.default_same_prefix_depth(urls, "single-page", None) == SINGLE_PAGE_PREFIX_DEPTH
    assert dsb.default_max_pages_for_input_format("single-page", None) == 1
    assert not dsb.default_render_js_for_input_format("single-page", None)


def test_explicit_context_defaults_are_preserved() -> None:
    assert (
        dsb.default_same_prefix_depth(["https://example.com/docs"], "docs-site", EXPLICIT_PREFIX_DEPTH)
        == EXPLICIT_PREFIX_DEPTH
    )
    assert (
        dsb.default_max_pages_for_input_format("docs-site", EXPLICIT_MAX_PAGES)
        == EXPLICIT_MAX_PAGES
    )
    assert not dsb.default_render_js_for_input_format("docs-site", False)


def test_should_keep_url_respects_scope_include_and_exclude() -> None:
    config = make_config(
        include_patterns=dsb.compile_patterns(["/docs/"]),
        exclude_patterns=dsb.compile_patterns(["/archive/"]),
    )

    assert dsb.should_keep_url("https://example.com/docs/guide", config)
    assert not dsb.should_keep_url("https://example.com/blog/guide", config)
    assert not dsb.should_keep_url("https://other.example.com/docs/guide", config)
    assert not dsb.should_keep_url("https://example.com/docs/archive/old", config)
    assert not dsb.should_keep_url("https://example.com/docs/logo.png", config)


def test_should_keep_url_allows_sitemap_xml_only_for_sitemap_mode() -> None:
    docs_config = make_config(input_format="docs-site", scope="domain")
    sitemap_config = make_config(
        urls=[SITEMAP_EXAMPLE_URL],
        input_format="sitemap",
        scope="domain",
    )

    assert not dsb.should_keep_url(SITEMAP_EXAMPLE_URL, docs_config)
    assert dsb.should_keep_url(SITEMAP_EXAMPLE_URL, sitemap_config)


def test_prefix_scope_keeps_seed_url_without_trailing_slash() -> None:
    assert dsb.in_scope(
        "https://geminicli.com/docs",
        ["https://geminicli.com/docs"],
        "prefix",
        1,
    )
    assert dsb.in_scope(
        "https://geminicli.com/docs/get-started",
        ["https://geminicli.com/docs"],
        "prefix",
        1,
    )


def test_single_scope_checks_all_seed_urls() -> None:
    assert dsb.in_scope(
        "https://example.com/docs/second",
        [
            "https://example.com/docs/first",
            "https://example.com/docs/second",
        ],
        "single",
        1,
    )


def test_slugify_and_page_filename_are_stable() -> None:
    assert dsb.slugify("OpenAI Codex: Skills & Agents") == "openai-codex-skills-agents"
    assert (
        dsb.page_filename(3, "OpenAI Codex: Skills & Agents", "https://example.com/codex/skills")
        == "003-openai-codex-skills-agents.md"
    )


def test_combined_markdown_includes_toc_and_source_metadata() -> None:
    page = dsb.PageResult(
        url="https://example.com/docs/start",
        title="Start Here",
        markdown="Body text",
        source_index=1,
        status_code=200,
        content_sha256="abc123",
        extracted_by="test",
    )

    markdown = dsb.combined_markdown([page], "Example Docs")

    assert markdown.startswith("# Example Docs")
    assert "- [001. Start Here](#start-here)" in markdown
    assert "<!-- source_url: https://example.com/docs/start -->" in markdown
    assert "Body text" in markdown


def test_pages_to_json_payload_shape() -> None:
    config = make_config()
    page = make_page()

    payload = dsb.pages_to_json_payload([page], ["https://example.com/docs/start"], config)

    assert payload["title"] == "Example Docs"
    assert payload["page_count"] == 1
    assert payload["pages"][0]["title"] == "Start Here"  # type: ignore[index]
    assert payload["pages"][0]["char_count"] == len("Body text")  # type: ignore[index]


def test_default_output_path_for_build() -> None:
    output_path = dsb.default_output_path(
        ["https://geminicli.com/docs"],
        "markdown",
        dry_run=False,
        explicit_output=None,
    )

    assert output_path == dsb.Path.cwd() / "out" / "geminicli-com-docs.md"


def test_default_output_path_for_discover() -> None:
    output_path = dsb.default_output_path(
        ["https://geminicli.com/docs"],
        "markdown",
        dry_run=True,
        explicit_output=None,
    )

    assert output_path == dsb.Path.cwd() / "out" / "geminicli-com-docs-candidates.txt"


def test_default_title_from_url() -> None:
    assert dsb.title_from_url("https://geminicli.com/docs") == "Geminicli.Com Docs"


def test_read_url_file_ignores_comments_and_preserves_order() -> None:
    url_file = write_test_url_file(
        """
# Curated source list
https://example.com/second?utm_source=test

https://example.com/first
"""
    )
    try:
        urls = dsb.read_url_file(url_file)
    finally:
        url_file.unlink(missing_ok=True)

    assert urls == [
        "https://example.com/second",
        "https://example.com/first",
    ]


def test_read_url_file_reports_missing_or_invalid_file() -> None:
    with pytest.raises(RuntimeError, match="Could not read URL file"):
        dsb.read_url_file("out/does-not-exist.txt")

    url_file = write_test_url_file("not-a-url\n")
    try:
        with pytest.raises(RuntimeError, match="invalid URL on line 1"):
            dsb.read_url_file(url_file)
    finally:
        url_file.unlink(missing_ok=True)


def test_parse_build_args() -> None:
    args = dsb.parse_args(
        [
            "build",
            "-u",
            "https://example.com/docs/start",
            "-f",
            "json",
            "-o",
            "out.json",
            "-t",
            "Example Docs",
            "-S",
        ]
    )

    assert args.command == "build"
    assert args.url == ["https://example.com/docs/start"]
    assert args.format == "json"
    assert args.output == "out.json"
    assert args.title == "Example Docs"
    assert args.split_pages


def test_parse_build_args_with_url_file_modes() -> None:
    exact_args = dsb.parse_args(["build", "-F", "urls.txt", "-U", "exact"])
    expand_args = dsb.parse_args(["build", "-F", "urls.txt", "-U", "expand", "-O"])

    assert exact_args.url_file == "urls.txt"
    assert exact_args.url_file_mode == "exact"
    assert not exact_args.one_output_per_seed
    assert expand_args.url_file == "urls.txt"
    assert expand_args.url_file_mode == "expand"
    assert expand_args.one_output_per_seed


def test_parse_build_args_with_only_url() -> None:
    args = dsb.parse_args(["build", "-u", "https://geminicli.com/docs/"])

    assert args.command == "build"
    assert args.url == ["https://geminicli.com/docs/"]
    assert args.output is None
    assert args.title is None
    assert args.format == "markdown"
    assert args.max_pages is None
    assert args.same_prefix_depth is None
    assert args.render_js is None


def test_build_config_infers_docs_site_defaults() -> None:
    args = dsb.parse_args(["build", "-u", "https://geminicli.com/docs/"])

    config = dsb.build_config(args, dry_run=False)

    assert config.output_path == dsb.Path.cwd() / "out" / "geminicli-com-docs.md"
    assert config.title == "Geminicli.Com Docs"
    assert config.input_format == "docs-site"
    assert config.scope == "prefix"
    assert config.same_prefix_depth == 1
    assert config.max_pages == DOCS_SITE_DEFAULT_MAX_PAGES
    assert config.render_js


def test_build_config_respects_no_render_js() -> None:
    args = dsb.parse_args(["build", "-u", "https://geminicli.com/docs/", "-J"])

    config = dsb.build_config(args, dry_run=False)

    assert not config.render_js


def test_build_config_url_file_exact_defaults_and_cli_append() -> None:
    url_file = write_test_url_file(
        """
https://example.com/docs/first
https://example.com/docs/second
"""
    )
    try:
        args = dsb.parse_args(["build", "-F", str(url_file), "-u", "https://example.com/docs/third"])

        config = dsb.build_config(args, dry_run=False)
    finally:
        url_file.unlink(missing_ok=True)

    assert config.urls == [
        "https://example.com/docs/first",
        "https://example.com/docs/second",
        "https://example.com/docs/third",
    ]
    assert config.scope == "single"
    assert config.max_pages == URL_FILE_COMBINED_COUNT
    assert config.url_file_mode == "exact"
    assert config.output_path == dsb.Path.cwd() / "out" / "test-urls.md"


def test_build_config_url_file_expand_defaults_to_output_directory() -> None:
    url_file = write_test_url_file("https://example.com/docs/\n")
    try:
        args = dsb.parse_args(["build", "-F", str(url_file), "-U", "expand"])

        config = dsb.build_config(args, dry_run=False)
    finally:
        url_file.unlink(missing_ok=True)

    assert config.urls == ["https://example.com/docs"]
    assert config.url_file_mode == "expand"
    assert config.output_path == dsb.Path.cwd() / "out" / "test-urls"


def test_build_config_one_output_per_seed_forces_expand_output_directory() -> None:
    url_file = write_test_url_file("https://example.com/docs/\n")
    try:
        args = dsb.parse_args(["build", "-F", str(url_file), "-O"])

        config = dsb.build_config(args, dry_run=False)
    finally:
        url_file.unlink(missing_ok=True)

    assert config.url_file_mode == "expand"
    assert config.output_path == dsb.Path.cwd() / "out" / "test-urls"


def test_parse_discover_args() -> None:
    args = dsb.parse_args(
        [
            "discover",
            "-u",
            "https://example.com/docs/start",
            "-o",
            "candidates.txt",
            "-m",
            str(EXPECTED_MAX_PAGES),
        ]
    )

    assert args.command == "discover"
    assert args.output == "candidates.txt"
    assert args.max_pages == EXPECTED_MAX_PAGES


def test_discover_config_infers_default_output() -> None:
    args = dsb.parse_args(["discover", "-u", "https://geminicli.com/docs/"])

    config = dsb.build_config(args, dry_run=True)

    assert config.output_path == dsb.Path.cwd() / "out" / "geminicli-com-docs-candidates.txt"
    assert config.render_js


def test_crawl_single_page_uses_only_seed_url(monkeypatch: object) -> None:
    fixture_html = page_html(
        "Single Page",
        '<a href="https://example.com/guide/next">Next</a>',
    )

    def fake_fetch_html(_url: str, _config: dsb.CrawlConfig) -> tuple[str, int | None]:
        return fixture_html, 200

    monkeypatch.setattr(dsb, "fetch_html", fake_fetch_html)
    args = dsb.parse_args(
        [
            "build",
            "-u",
            SINGLE_PAGE_EXAMPLE_URL,
            "-I",
            "single-page",
            "-c",
            "1",
            "-J",
        ]
    )
    config = dsb.build_config(args, dry_run=False)

    pages, discovered_urls = dsb.crawl(config)

    assert [page.url for page in pages] == ["https://example.com/guide"]
    assert discovered_urls == ["https://example.com/guide"]


def test_crawl_docs_site_preserves_sidebar_order(monkeypatch: object) -> None:
    url_to_html = {
        "https://geminicli.com/docs": page_html(
            "Gemini CLI documentation",
            """
            <a href="/docs/get-started/">Get started</a>
            <a href="/docs/cli/tutorials/file-management/">File management</a>
            """,
        ),
        "https://geminicli.com/docs/get-started": page_html("Get started with Gemini CLI"),
        "https://geminicli.com/docs/cli/tutorials/file-management": page_html("File management with Gemini CLI"),
    }

    def fake_fetch_html(url: str, _config: dsb.CrawlConfig) -> tuple[str, int | None]:
        return url_to_html[url], 200

    monkeypatch.setattr(dsb, "fetch_html", fake_fetch_html)
    args = dsb.parse_args(["build", "-u", DOCS_SITE_EXAMPLE_URL, "-I", "docs-site", "-c", "1", "-J"])
    config = dsb.build_config(args, dry_run=False)

    pages, discovered_urls = dsb.crawl(config)

    assert discovered_urls == [
        "https://geminicli.com/docs",
        "https://geminicli.com/docs/get-started",
        "https://geminicli.com/docs/cli/tutorials/file-management",
    ]
    assert [page.title for page in pages] == [
        "Gemini CLI documentation",
        "Get started with Gemini CLI",
        "File management with Gemini CLI",
    ]


def test_crawl_github_wiki_uses_wiki_url_shape(monkeypatch: object) -> None:
    url_to_html = {
        "https://github.com/Homebrew/brew/wiki": page_html(
            "Homebrew Wiki",
            """
            <a href="/Homebrew/brew/wiki/Installation">Installation</a>
            <a href="/Homebrew/brew/wiki/Troubleshooting">Troubleshooting</a>
            """,
        ),
        "https://github.com/Homebrew/brew/wiki/Installation": page_html("Installation"),
        "https://github.com/Homebrew/brew/wiki/Troubleshooting": page_html("Troubleshooting"),
    }

    def fake_fetch_html(url: str, _config: dsb.CrawlConfig) -> tuple[str, int | None]:
        return url_to_html[url], 200

    monkeypatch.setattr(dsb, "fetch_html", fake_fetch_html)
    args = dsb.parse_args(["build", "-u", GITHUB_WIKI_EXAMPLE_URL, "-I", "github-wiki", "-c", "1"])
    config = dsb.build_config(args, dry_run=False)

    pages, discovered_urls = dsb.crawl(config)

    assert config.input_format == "github-wiki"
    assert discovered_urls == [
        "https://github.com/Homebrew/brew/wiki",
        "https://github.com/Homebrew/brew/wiki/Installation",
        "https://github.com/Homebrew/brew/wiki/Troubleshooting",
    ]
    assert [page.title for page in pages] == ["Homebrew Wiki", "Installation", "Troubleshooting"]


def test_crawl_github_pages_uses_github_io_url_shape(monkeypatch: object) -> None:
    url_to_html = {
        "https://pytest-dev.github.io/pytest": page_html(
            "pytest documentation",
            """
            <a href="/pytest/getting-started/">Getting started</a>
            <a href="/pytest/how-to/assert/">Assertions</a>
            """,
        ),
        "https://pytest-dev.github.io/pytest/getting-started": page_html("Getting started"),
        "https://pytest-dev.github.io/pytest/how-to/assert": page_html("Assertions"),
    }

    def fake_fetch_html(url: str, _config: dsb.CrawlConfig) -> tuple[str, int | None]:
        return url_to_html[url], 200

    monkeypatch.setattr(dsb, "fetch_html", fake_fetch_html)
    args = dsb.parse_args(["build", "-u", GITHUB_PAGES_EXAMPLE_URL, "-I", "github-pages", "-c", "1", "-J"])
    config = dsb.build_config(args, dry_run=False)

    pages, discovered_urls = dsb.crawl(config)

    assert config.input_format == "github-pages"
    assert discovered_urls == [
        "https://pytest-dev.github.io/pytest",
        "https://pytest-dev.github.io/pytest/getting-started",
        "https://pytest-dev.github.io/pytest/how-to/assert",
    ]
    assert [page.title for page in pages] == ["pytest documentation", "Getting started", "Assertions"]


def test_crawl_sitemap_discovers_pages_without_extracting_xml(monkeypatch: object) -> None:
    sitemap_xml = """
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://example.com/docs/intro/</loc></url>
    <url><loc>https://example.com/docs/reference/</loc></url>
</urlset>
"""
    url_to_html = {
        "https://example.com/sitemap.xml": sitemap_xml,
        "https://example.com/docs/intro": page_html("Intro"),
        "https://example.com/docs/reference": page_html("Reference"),
    }

    def fake_fetch_html(url: str, _config: dsb.CrawlConfig) -> tuple[str, int | None]:
        return url_to_html[url], 200

    monkeypatch.setattr(dsb, "fetch_html", fake_fetch_html)
    args = dsb.parse_args(["build", "-u", SITEMAP_EXAMPLE_URL, "-I", "sitemap", "-c", "1"])
    config = dsb.build_config(args, dry_run=False)

    pages, discovered_urls = dsb.crawl(config)

    assert config.scope == "domain"
    assert discovered_urls == [
        "https://example.com/docs/intro",
        "https://example.com/docs/reference",
    ]
    assert [page.url for page in pages] == [
        "https://example.com/docs/intro",
        "https://example.com/docs/reference",
    ]


def test_crawl_sitemap_index_follows_nested_sitemaps(monkeypatch: object) -> None:
    sitemap_index_xml = """
<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap><loc>https://example.com/docs-sitemap.xml</loc></sitemap>
</sitemapindex>
"""
    nested_sitemap_xml = """
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://example.com/docs/nested/</loc></url>
</urlset>
"""
    url_to_html = {
        "https://example.com/sitemap.xml": sitemap_index_xml,
        "https://example.com/docs-sitemap.xml": nested_sitemap_xml,
        "https://example.com/docs/nested": page_html("Nested"),
    }

    def fake_fetch_html(url: str, _config: dsb.CrawlConfig) -> tuple[str, int | None]:
        return url_to_html[url], 200

    monkeypatch.setattr(dsb, "fetch_html", fake_fetch_html)
    args = dsb.parse_args(["build", "-u", SITEMAP_EXAMPLE_URL, "-I", "sitemap", "-c", "1"])
    config = dsb.build_config(args, dry_run=False)

    pages, discovered_urls = dsb.crawl(config)

    assert discovered_urls == ["https://example.com/docs/nested"]
    assert [page.title for page in pages] == ["Nested"]


def test_run_build_url_file_exact_preserves_order_and_does_not_expand(monkeypatch: object) -> None:
    shutil.rmtree(URL_FILE_TEST_DIR, ignore_errors=True)
    url_file = URL_FILE_TEST_DIR / "exact-urls.txt"
    output_path = URL_FILE_TEST_DIR / "exact" / "source.md"
    url_file.parent.mkdir(parents=True, exist_ok=True)
    url_file.write_text(
        "\n".join(
            [
                "https://example.com/docs/second",
                "https://example.com/docs/first",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    url_to_html = {
        "https://example.com/docs/second": page_html(
            "Second",
            '<a href="https://example.com/docs/side-page">Side page</a>',
        ),
        "https://example.com/docs/first": page_html("First"),
    }
    fetched_urls: list[str] = []

    def fake_fetch_html(url: str, _config: dsb.CrawlConfig) -> tuple[str, int | None]:
        fetched_urls.append(url)
        return url_to_html[url], 200

    monkeypatch.setattr(dsb, "fetch_html", fake_fetch_html)
    try:
        args = dsb.parse_args(["build", "-F", str(url_file), "-o", str(output_path), "-c", "1", "-J"])

        result = dsb.run_build(args)

        markdown = output_path.read_text(encoding="utf-8")
        manifest = json.loads((output_path.parent / "manifest.json").read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(URL_FILE_TEST_DIR, ignore_errors=True)

    assert result == 0
    assert fetched_urls == [
        "https://example.com/docs/second",
        "https://example.com/docs/first",
    ]
    assert markdown.index("# Second") < markdown.index("# First")
    assert "side-page" not in fetched_urls
    assert manifest["url_file_mode"] == "exact"
    assert manifest["discovered_urls"] == fetched_urls


def test_run_build_url_file_exact_writes_markdown_json_and_pdf(monkeypatch: object) -> None:
    url_to_html = {
        "https://example.com/docs/one": page_html("One"),
        "https://example.com/docs/two": page_html("Two"),
    }

    def fake_fetch_html(url: str, _config: dsb.CrawlConfig) -> tuple[str, int | None]:
        return url_to_html[url], 200

    monkeypatch.setattr(dsb, "fetch_html", fake_fetch_html)
    shutil.rmtree(URL_FILE_TEST_DIR, ignore_errors=True)
    url_file = URL_FILE_TEST_DIR / "formats-urls.txt"
    url_file.parent.mkdir(parents=True, exist_ok=True)
    url_file.write_text(
        "https://example.com/docs/one\nhttps://example.com/docs/two\n",
        encoding="utf-8",
    )
    output_specs = [
        ("markdown", URL_FILE_TEST_DIR / "formats" / "source.md"),
        ("json", URL_FILE_TEST_DIR / "formats" / "source.json"),
        ("pdf", URL_FILE_TEST_DIR / "formats" / "source.pdf"),
    ]

    try:
        for output_format, output_path in output_specs:
            args = dsb.parse_args(
                [
                    "build",
                    "-F",
                    str(url_file),
                    "-f",
                    output_format,
                    "-o",
                    str(output_path),
                    "-c",
                    "1",
                    "-J",
                    "-M",
                    "-C",
                ]
            )

            assert dsb.run_build(args) == 0

        assert "# One" in output_specs[0][1].read_text(encoding="utf-8")
        payload = json.loads(output_specs[1][1].read_text(encoding="utf-8"))
        assert payload["url_file_mode"] == "exact"
        assert [page["title"] for page in payload["pages"]] == ["One", "Two"]
        assert output_specs[2][1].read_bytes().startswith(b"%PDF")
    finally:
        shutil.rmtree(URL_FILE_TEST_DIR, ignore_errors=True)


def test_run_build_url_file_expand_writes_one_output_per_seed(monkeypatch: object) -> None:
    shutil.rmtree(URL_FILE_TEST_DIR, ignore_errors=True)
    url_file = URL_FILE_TEST_DIR / "expand-urls.txt"
    output_dir = URL_FILE_TEST_DIR / "expanded"
    url_file.parent.mkdir(parents=True, exist_ok=True)
    url_file.write_text(
        "https://example.com/docs/a\nhttps://example.com/docs/b\n",
        encoding="utf-8",
    )
    url_to_html = {
        "https://example.com/docs/a": page_html(
            "Docs A",
            '<a href="https://example.com/docs/a/child">Docs A Child</a>',
        ),
        "https://example.com/docs/a/child": page_html("Docs A Child"),
        "https://example.com/docs/b": page_html(
            "Docs B",
            '<a href="https://example.com/docs/b/child">Docs B Child</a>',
        ),
        "https://example.com/docs/b/child": page_html("Docs B Child"),
    }

    def fake_fetch_html(url: str, _config: dsb.CrawlConfig) -> tuple[str, int | None]:
        return url_to_html[url], 200

    monkeypatch.setattr(dsb, "fetch_html", fake_fetch_html)
    try:
        args = dsb.parse_args(
            [
                "build",
                "-F",
                str(url_file),
                "-U",
                "expand",
                "-o",
                str(output_dir),
                "-c",
                "1",
                "-J",
            ]
        )

        result = dsb.run_build(args)

        first_output = output_dir / "example-com-docs-a.md"
        second_output = output_dir / "example-com-docs-b.md"
        first_markdown = first_output.read_text(encoding="utf-8")
        second_markdown = second_output.read_text(encoding="utf-8")
        first_candidate_path = output_dir / "example-com-docs-a-candidate-urls.txt"
        second_candidate_path = output_dir / "example-com-docs-b-candidate-urls.txt"
        first_manifest = json.loads((output_dir / "example-com-docs-a-manifest.json").read_text(encoding="utf-8"))
        second_manifest = json.loads((output_dir / "example-com-docs-b-manifest.json").read_text(encoding="utf-8"))
        first_exists = first_output.exists()
        second_exists = second_output.exists()
        first_candidate_exists = first_candidate_path.exists()
        second_candidate_exists = second_candidate_path.exists()
    finally:
        shutil.rmtree(URL_FILE_TEST_DIR, ignore_errors=True)

    assert result == 0
    assert first_exists
    assert second_exists
    assert "Docs A Child" in first_markdown
    assert "Docs B Child" in second_markdown
    assert first_manifest["batch_seed_url"] == "https://example.com/docs/a"
    assert second_manifest["batch_seed_url"] == "https://example.com/docs/b"
    assert first_candidate_exists
    assert second_candidate_exists


def test_write_output_file_markdown_json_and_pdf() -> None:
    page = make_page()
    paths = [
        OUTPUT_TEST_DIR / "source.md",
        OUTPUT_TEST_DIR / "source.json",
        OUTPUT_TEST_DIR / "source.pdf",
    ]

    try:
        markdown_config = make_config(output_path=paths[0], output_format="markdown")
        json_config = make_config(output_path=paths[1], output_format="json")
        pdf_config = make_config(output_path=paths[2], output_format="pdf")

        markdown_path = dsb.write_output_file([page], [page.url], markdown_config)
        json_path = dsb.write_output_file([page], [page.url], json_config)
        pdf_path = dsb.write_output_file([page], [page.url], pdf_config)

        assert "# Example Docs" in markdown_path.read_text(encoding="utf-8")

        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["output_format"] == "json"
        assert payload["pages"][0]["title"] == "Start Here"

        assert pdf_path.read_bytes().startswith(b"%PDF")
    finally:
        for path in paths:
            path.unlink(missing_ok=True)
        OUTPUT_TEST_DIR.rmdir()


def test_build_config_reads_manifest_urls_and_settings() -> None:
    payload = {
        "title": "Manifest Docs",
        "seed_urls": ["https://example.com/docs"],
        "input_format": "docs-site",
        "scope": "prefix",
        "same_prefix_depth": 1,
        "max_pages": MANIFEST_MAX_PAGES,
        "render_js": True,
        "delay_seconds": MANIFEST_DELAY_SECONDS,
        "timeout_seconds": MANIFEST_TIMEOUT_SECONDS,
        "min_chars": MANIFEST_MIN_CHARS,
        "keep_query": False,
        "include": ["/docs/"],
        "exclude": ["/archive/"],
        "discovered_urls": [
            "https://example.com/docs",
            "https://example.com/docs/get-started",
        ],
    }
    manifest_path = write_test_manifest(payload)
    try:
        args = dsb.parse_args(["build", "-g", str(manifest_path), "-f", "pdf"])

        config = dsb.build_config(args, dry_run=False)
    finally:
        manifest_path.unlink(missing_ok=True)

    assert config.urls == [
        "https://example.com/docs",
        "https://example.com/docs/get-started",
    ]
    assert config.title == "Manifest Docs"
    assert config.input_format == "docs-site"
    assert config.scope == "prefix"
    assert config.same_prefix_depth == 1
    assert config.max_pages == MANIFEST_MAX_PAGES
    assert config.render_js
    assert config.delay_seconds == MANIFEST_DELAY_SECONDS
    assert config.timeout_seconds == MANIFEST_TIMEOUT_SECONDS
    assert config.min_chars == MANIFEST_MIN_CHARS
    assert config.output_format == "pdf"
    assert [pattern.pattern for pattern in config.include_patterns] == ["/docs/"]
    assert [pattern.pattern for pattern in config.exclude_patterns] == ["/archive/"]


def test_build_config_manifest_can_be_overridden_by_cli_url_and_title() -> None:
    payload = {
        "title": "Manifest Docs",
        "seed_urls": ["https://example.com/docs"],
        "input_format": "docs-site",
        "discovered_urls": ["https://example.com/docs"],
    }
    manifest_path = write_test_manifest(payload)
    try:
        args = dsb.parse_args(
            [
                "build",
                "-g",
                str(manifest_path),
                "-u",
                "https://other.example/docs",
                "-t",
                "Override",
                "-J",
            ]
        )

        config = dsb.build_config(args, dry_run=False)
    finally:
        manifest_path.unlink(missing_ok=True)

    assert config.urls == ["https://other.example/docs"]
    assert config.title == "Override"
    assert not config.render_js


def test_parse_setup_browsers_args() -> None:
    args = dsb.parse_args(["setup-browsers", "-b", "chromium", "-n"])

    assert args.command == "setup-browsers"
    assert args.browser == "chromium"
    assert args.dry_run


def test_run_playwright_browser_install_dry_run(capsys: object) -> None:
    result = dsb.run_playwright_browser_install("chromium", dry_run=True)
    captured = capsys.readouterr()

    assert result == 0
    assert "playwright install chromium" in captured.out
