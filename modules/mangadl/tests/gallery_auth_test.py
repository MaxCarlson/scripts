from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from mangadl import gallery_auth
from mangadl.gallery_auth import (
    AuthProfile,
    ProbeResult,
    ProfileStore,
    TargetStore,
    classify_probe,
    cookie_summary,
    default_cookie_output,
    domain_for,
    gallery_sites,
    netscape_cookie_text,
    refresh_profile,
    relevant_cookies,
    site_for_url,
)


def sample_cookies() -> list[dict[str, object]]:
    return [
        {
            "domain": ".mangakakalot.gg",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "expires": 2_000_000_000.9,
            "name": "cf_clearance",
            "value": "secret-cookie-value",
        },
        {
            "domain": ".example.com",
            "path": "/",
            "secure": False,
            "httpOnly": False,
            "expires": 0,
            "name": "unrelated",
            "value": "not-selected",
        },
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://www.MangaKakalot.gg/manga/title", "mangakakalot.gg"),
        ("mangakakalot.gg", "mangakakalot.gg"),
        ("sub.example.com", "sub.example.com"),
    ],
)
def test_domain_normalization(value: str, expected: str) -> None:
    assert domain_for(value) == expected


def test_cookie_filter_and_netscape_writer_do_not_mix_domains() -> None:
    selected = relevant_cookies(sample_cookies(), "https://www.mangakakalot.gg/manga/title")
    assert [cookie["name"] for cookie in selected] == ["cf_clearance"]

    output = netscape_cookie_text(sample_cookies(), "mangakakalot.gg")
    assert "#HttpOnly_.mangakakalot.gg\tTRUE\t/\tTRUE\t2000000000\tcf_clearance\tsecret-cookie-value" in output
    assert "unrelated" not in output


def test_profile_persistence_and_status_summary_are_secret_free(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "auth")
    output = netscape_cookie_text(sample_cookies(), "mangakakalot.gg")
    profile = store.save(
        "https://www.mangakakalot.gg/manga/title",
        output,
        "Example Browser UA",
        "chrome",
        source="chrome-cdp",
    )

    loaded = store.load("mangakakalot.gg")
    assert loaded == profile
    assert profile.cookie_path.read_text(encoding="utf-8") == output
    metadata = store.profile_path("mangakakalot.gg").read_text(encoding="utf-8")
    assert "secret-cookie-value" not in metadata
    summary = cookie_summary(profile.cookie_path, now=1_900_000_000)
    assert summary.count == 1
    assert summary.names == ("cf_clearance",)
    assert not summary.expired


def test_profile_cookie_file_is_deleted_when_profile_is_cleared(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "auth")
    external = tmp_path / "exported-cookies.txt"
    store.save("example.com", "# Netscape HTTP Cookie File\n", "UA", "edge", source="edge-cdp", cookie_file=external)

    assert store.clear("example.com")
    assert not external.exists()
    assert store.load("example.com") is None


@pytest.mark.parametrize(
    ("output", "status"),
    [
        ("gallery_dl.exception.ChallengeError: Cloudflare challenge", "challenge"),
        ("HTTP 403 Forbidden", "challenge"),
        ("Authentication required", "auth_failure"),
        ("Unsupported URL", "unsupported"),
        ("HTTP 404 Not Found", "other_failure"),
    ],
)
def test_probe_classification_is_bounded(output: str, status: str) -> None:
    assert classify_probe(1, output).status == status


def test_cdp_refresh_captures_matching_ua_and_persists_after_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    store = ProfileStore(tmp_path / "auth")
    captures: list[dict[str, object]] = []

    def fake_capture(*args, **kwargs):
        captures.append(kwargs)
        return sample_cookies(), "Captured Chrome UA"

    monkeypatch.setattr(gallery_auth, "_capture_cdp", fake_capture)
    monkeypatch.setattr(
        gallery_auth,
        "probe_gallery_dl",
        lambda url, cookie_file, user_agent, timeout=60, progress=None: ProbeResult("success", 0, "ok"),
    )

    profile, probe = refresh_profile(
        "https://www.mangakakalot.gg/manga/title",
        store=store,
        browser="chrome",
        timeout=1,
    )

    assert probe.success
    assert profile is not None
    assert profile.user_agent == "Captured Chrome UA"
    assert profile.browser == "chrome"
    assert profile.cookie_path == tmp_path / "mangakakalot.gg-cookies.txt"
    assert captures[0]["allow_launch"] is True
    assert "secret-cookie-value" not in json.dumps(profile.__dict__ if hasattr(profile, "__dict__") else {})


def test_cdp_websocket_reads_only_matching_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class Connection:
        def __init__(self) -> None:
            self.sent = ""
            self.responses = [
                json.dumps({"method": "Network.cookieChanged"}),
                json.dumps({"id": 1, "result": {"cookies": sample_cookies()}}),
            ]
            self.closed = False

        def send(self, value: str) -> None:
            self.sent = value

        def recv(self) -> str:
            return self.responses.pop(0)

        def close(self) -> None:
            self.closed = True

    connection = Connection()
    websocket = ModuleType("websocket")
    websocket.create_connection = lambda *args, **kwargs: connection  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "websocket", websocket)

    cookies = gallery_auth._cdp_cookies("ws://debugger")

    assert cookies == sample_cookies()
    assert json.loads(connection.sent) == {"id": 1, "method": "Network.getAllCookies"}
    assert connection.closed


def test_cdp_capture_selects_exact_target_and_matching_ua(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = {
        "/json/version": {"User-Agent": "Exact UA"},
        "/json": [
            {"url": "chrome://newtab", "webSocketDebuggerUrl": "ws://ignored"},
            {
                "url": "https://www.mangakakalot.gg/manga/exact-target",
                "webSocketDebuggerUrl": "ws://selected",
            },
        ],
    }
    monkeypatch.setattr(gallery_auth, "_json_endpoint", lambda port, route: responses[route])
    monkeypatch.setattr(gallery_auth, "_cdp_cookies", lambda url: sample_cookies() if url == "ws://selected" else [])

    cookies, user_agent = gallery_auth._capture_cdp(
        "https://www.mangakakalot.gg/manga/exact-target",
        "chrome",
        9222,
        no_launch=False,
        allow_launch=True,
        auth_root=tmp_path,
    )

    assert cookies == sample_cookies()
    assert user_agent == "Exact UA"


def test_cdp_capture_opens_exact_target_when_only_homepage_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = {
        "/json/version": {"User-Agent": "Exact UA"},
        "/json": [
            {"url": "https://www.mangakakalot.gg/", "webSocketDebuggerUrl": "ws://homepage"}
        ],
    }
    opened: list[str] = []
    monkeypatch.setattr(gallery_auth, "_json_endpoint", lambda port, route: responses[route])
    monkeypatch.setattr(gallery_auth, "_open_cdp_target", lambda port, url: opened.append(url))
    target = "https://www.mangakakalot.gg/manga/exact-target"

    with pytest.raises(RuntimeError, match="target-not-ready"):
        gallery_auth._capture_cdp(
            target,
            "chrome",
            9222,
            no_launch=False,
            allow_launch=True,
            auth_root=tmp_path,
        )

    assert opened == [target]


def test_cdp_browser_launch_includes_exact_target_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    browser = tmp_path / "chrome.exe"
    browser.write_text("", encoding="utf-8")
    monkeypatch.setattr(gallery_auth, "find_browser", lambda value: browser)

    def fake_popen(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace()

    monkeypatch.setattr(gallery_auth.subprocess, "Popen", fake_popen)
    target = "https://www.mangakakalot.gg/manga/exact-target"
    gallery_auth._launch_cdp_browser("chrome", target, 9222, tmp_path / "profile")

    assert captured["command"][-1] == target


def test_firefox_refresh_uses_gallery_dl_cookie_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    store = ProfileStore(tmp_path / "auth")
    cookies = netscape_cookie_text(sample_cookies(), "mangakakalot.gg")
    monkeypatch.setattr(
        gallery_auth,
        "_refresh_firefox",
        lambda url, timeout, user_agent: (cookies, user_agent or "browser", ProbeResult("success", 0, "ok")),
    )

    profile, probe = refresh_profile(
        "https://mangakakalot.gg/manga/title",
        store=store,
        browser="firefox",
        user_agent="Firefox UA",
        no_launch=True,
    )

    assert probe.success
    assert profile is not None
    assert profile.browser == "firefox"
    assert profile.user_agent == "Firefox UA"


def test_refresh_forces_target_navigation_and_reports_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    calls = 0
    messages: list[str] = []

    def fake_capture(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert kwargs["force_open"] is True
            raise RuntimeError("target-opening")
        assert kwargs["force_open"] is False
        return sample_cookies(), "Chrome UA"

    monkeypatch.setattr(gallery_auth, "_capture_cdp", fake_capture)
    monkeypatch.setattr(
        gallery_auth,
        "probe_gallery_dl",
        lambda *args, **kwargs: ProbeResult("success", 0, "ok"),
    )

    profile, probe = refresh_profile(
        "https://www.mangakakalot.gg/manga/title",
        store=ProfileStore(tmp_path / "auth"),
        timeout=3,
        progress=messages.append,
    )

    assert probe.success and profile is not None
    assert any("preparing chrome authentication" in message for message in messages)
    assert any("opened the exact target URL" in message for message in messages)
    assert any("validating the exact target URL" in message for message in messages)
    assert any("validation succeeded" in message for message in messages)


def test_firefox_refresh_launches_exact_target_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    launched: list[str] = []
    cookies = netscape_cookie_text(sample_cookies(), "mangakakalot.gg")
    monkeypatch.setattr(gallery_auth, "_launch_firefox", lambda url: launched.append(url))
    monkeypatch.setattr(
        gallery_auth,
        "_refresh_firefox",
        lambda url, timeout, user_agent: (cookies, "Firefox UA", ProbeResult("success", 0, "ok")),
    )
    target = "https://www.mangakakalot.gg/manga/title"

    profile, probe = refresh_profile(target, store=ProfileStore(tmp_path / "auth"), browser="firefox")

    assert probe.success and profile is not None
    assert launched == [target]


def test_profile_metadata_never_contains_cookie_values(tmp_path: Path) -> None:
    profile = AuthProfile(
        domain="example.com",
        user_agent="UA",
        browser="chrome",
        created_at="now",
        updated_at="now",
        cookie_file=str(tmp_path / "cookies.txt"),
        source="chrome-cdp",
    )
    assert "secret-cookie-value" not in repr(profile)


def test_target_store_seeds_manganelo_and_replaces_valid_url(tmp_path: Path) -> None:
    targets = TargetStore(tmp_path / "auth")
    assert targets.url_for("manganelo") == "https://www.mangakakalot.gg/manga/lets-play-hooky"

    replacement = "https://www.mangakakalot.gg/manga/like-no-other"
    targets.save("manganelo", replacement)

    assert targets.url_for("manganelo") == replacement
    assert site_for_url(replacement) == "manganelo"


def test_target_store_rejects_url_from_different_gallery_site(tmp_path: Path) -> None:
    targets = TargetStore(tmp_path / "auth")
    with pytest.raises(ValueError, match="not selected site"):
        targets.save("manganelo", "https://nhentai.net/g/123/")


def test_gallery_sites_come_from_installed_registry_and_include_saved_target(tmp_path: Path) -> None:
    sites = gallery_sites(TargetStore(tmp_path / "auth"))
    manganelo = next(site for site in sites if site.name == "manganelo")
    assert manganelo.extractor_count >= 1
    assert any("mangakakalot.gg" in example for example in manganelo.examples)
    assert manganelo.target_url == "https://www.mangakakalot.gg/manga/lets-play-hooky"


def test_default_cookie_output_uses_invocation_directory_and_domain_prefix(tmp_path: Path) -> None:
    assert default_cookie_output("https://www.mangakakalot.gg/manga/title", tmp_path) == (
        tmp_path / "mangakakalot.gg-cookies.txt"
    )
