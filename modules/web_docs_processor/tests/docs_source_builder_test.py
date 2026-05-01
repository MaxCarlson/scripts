from __future__ import annotations

import json

from web_docs_processor import docs_source_builder as dsb

EXPECTED_MAX_PAGES = 5
DOCS_SITE_DEFAULT_MAX_PAGES = 300
SINGLE_PAGE_PREFIX_DEPTH = 2
EXPLICIT_PREFIX_DEPTH = 4
EXPLICIT_MAX_PAGES = 42
MANIFEST_MAX_PAGES = 50
MANIFEST_DELAY_SECONDS = 0.1
MANIFEST_TIMEOUT_SECONDS = 9.0
MANIFEST_MIN_CHARS = 25
MANIFEST_PATH = dsb.Path("out") / "test-manifest.json"


def write_test_manifest(payload: dict[str, object]) -> dsb.Path:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(payload), encoding="utf-8")
    return MANIFEST_PATH


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
    }
    values.update(overrides)
    values["output_path"] = dsb.Path(str(values["output_path"]))
    return dsb.CrawlConfig(**values)


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
    page = dsb.PageResult(
        url="https://example.com/docs/start",
        title="Start Here",
        markdown="Body text",
        source_index=1,
        status_code=200,
        content_sha256="abc123",
        extracted_by="test",
    )

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
