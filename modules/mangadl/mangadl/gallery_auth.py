from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

BROWSERS = ("chrome", "edge", "firefox")
DEFAULT_BROWSER = "chrome"
DEFAULT_AUTH_SITE = "manganelo"
BUILTIN_TARGETS = {
    "manganelo": "https://www.mangakakalot.gg/manga/lets-play-hooky",
}
DEFAULT_DEBUG_PORTS = {"chrome": 9222, "edge": 9223}
CHALLENGE_MARKERS = (
    "challengeerror",
    "cloudflare challenge",
    "http 403",
    "403 forbidden",
    "http 401",
    "401 unauthorized",
)
AUTH_MARKERS = ("authentication required", "login required", "authorization required")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def domain_for(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"//{value}")
    host = (parsed.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or any(character in host for character in "/\\ "):
        raise ValueError(f"could not determine a domain from {value!r}")
    return host


def default_auth_dir() -> Path:
    override = os.environ.get("MANGADL_AUTH_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return (base / "mangadl" / "auth").resolve()


def _atomic_write(path: Path, content: str, *, secret: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if secret:
            try:
                os.chmod(temporary_path, 0o600)
            except OSError:
                pass
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


@dataclass(frozen=True, slots=True)
class AuthProfile:
    domain: str
    user_agent: str
    browser: str
    created_at: str
    updated_at: str
    cookie_file: str
    source: str

    @property
    def cookie_path(self) -> Path:
        return Path(self.cookie_file).expanduser().resolve()


@dataclass(frozen=True, slots=True)
class CookieSummary:
    count: int
    names: tuple[str, ...]
    earliest_expiry: int | None
    expired: bool


@dataclass(frozen=True, slots=True)
class ProbeResult:
    status: str
    returncode: int
    message: str

    @property
    def success(self) -> bool:
        return self.status == "success"


@dataclass(frozen=True, slots=True)
class GallerySite:
    name: str
    extractor_count: int
    examples: tuple[str, ...]
    target_url: str | None = None


def site_for_url(url: str) -> str:
    try:
        from gallery_dl import extractor
    except ImportError as exc:  # pragma: no cover - package dependency
        raise RuntimeError("gallery-dl is required to inspect authentication targets") from exc
    match = extractor.find(url)
    if match is None:
        raise ValueError(f"gallery-dl does not recognize this URL: {url}")
    return match.__class__.__module__.rsplit(".", 1)[-1].lower()


def gallery_sites(targets: "TargetStore | None" = None) -> list[GallerySite]:
    try:
        from gallery_dl import extractor
    except ImportError as exc:  # pragma: no cover - package dependency
        raise RuntimeError("gallery-dl is required to list supported sites") from exc
    grouped: dict[str, dict[str, Any]] = {}
    for cls in extractor.extractors():
        name = cls.__module__.rsplit(".", 1)[-1].lower()
        entry = grouped.setdefault(name, {"count": 0, "examples": []})
        entry["count"] += 1
        example = getattr(cls, "example", None)
        values = example if isinstance(example, (tuple, list)) else (example,)
        for value in values:
            if isinstance(value, str) and value and value not in entry["examples"]:
                entry["examples"].append(value)
    known = targets.all() if targets else {}
    return [
        GallerySite(
            name=name,
            extractor_count=data["count"],
            examples=tuple(data["examples"][:3]),
            target_url=known.get(name),
        )
        for name, data in sorted(grouped.items())
    ]


class TargetStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_auth_dir()).expanduser().resolve()
        self.path = self.root / "targets.json"

    def _saved(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        values = payload.get("targets", {}) if isinstance(payload, dict) else {}
        return {
            str(site).lower(): str(url)
            for site, url in values.items()
            if isinstance(site, str) and isinstance(url, str)
        }

    def all(self) -> dict[str, str]:
        return {**BUILTIN_TARGETS, **self._saved()}

    def url_for(self, site: str) -> str | None:
        return self.all().get(site.lower())

    def save(self, site: str, url: str) -> None:
        actual_site = site_for_url(url)
        requested = site.lower()
        if actual_site != requested:
            raise ValueError(
                f"URL belongs to gallery-dl site {actual_site!r}, not selected site {requested!r}: {url}"
            )
        targets = self._saved()
        targets[requested] = url
        payload = {"schema": 1, "updated_at": _utc_now(), "targets": dict(sorted(targets.items()))}
        _atomic_write(self.path, json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def resolve_site(self, value: str) -> str:
        query = value.lower().strip()
        sites = gallery_sites(self)
        names = {site.name for site in sites}
        if query in names:
            return query
        domain_matches = [
            name for name, url in self.all().items() if domain_for(url) == query.removeprefix("www.")
        ]
        if len(domain_matches) == 1:
            return domain_matches[0]
        partial = [name for name in names if query in name]
        if len(partial) == 1:
            return partial[0]
        if not partial:
            raise ValueError(f"the installed gallery-dl has no site matching {value!r}")
        raise ValueError(f"site {value!r} is ambiguous; matches: {', '.join(sorted(partial)[:12])}")


class ProfileStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_auth_dir()).expanduser().resolve()

    def profile_dir(self, value: str) -> Path:
        return self.root / domain_for(value)

    def profile_path(self, value: str) -> Path:
        return self.profile_dir(value) / "profile.json"

    def default_cookie_path(self, value: str) -> Path:
        return self.profile_dir(value) / "cookies.txt"

    def load(self, value: str) -> AuthProfile | None:
        path = self.profile_path(value)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            profile = AuthProfile(**data)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if profile.domain != domain_for(value) or not profile.user_agent or not profile.cookie_path.is_file():
            return None
        return profile

    def save(
        self,
        value: str,
        cookies: str,
        user_agent: str,
        browser: str,
        *,
        source: str,
        cookie_file: Path | None = None,
    ) -> AuthProfile:
        domain = domain_for(value)
        existing = self.load(domain)
        now = _utc_now()
        destination = (cookie_file or self.default_cookie_path(domain)).expanduser().resolve()
        _atomic_write(destination, cookies, secret=True)
        profile = AuthProfile(
            domain=domain,
            user_agent=user_agent,
            browser=browser,
            created_at=existing.created_at if existing else now,
            updated_at=now,
            cookie_file=str(destination),
            source=source,
        )
        _atomic_write(self.profile_path(domain), json.dumps(asdict(profile), indent=2, sort_keys=True) + "\n")
        return profile

    def clear(self, value: str) -> bool:
        directory = self.profile_dir(value)
        profile = self.load(value)
        removed = False
        managed_cookie = profile.cookie_path if profile else self.default_cookie_path(value)
        if managed_cookie.is_file():
            managed_cookie.unlink()
            removed = True
        path = self.profile_path(value)
        if path.is_file():
            path.unlink()
            removed = True
        try:
            directory.rmdir()
        except OSError:
            pass
        return removed


def relevant_cookies(cookies: Iterable[dict[str, Any]], value: str) -> list[dict[str, Any]]:
    host = domain_for(value)
    selected = []
    for cookie in cookies:
        cookie_domain = str(cookie.get("domain", "")).lower().lstrip(".").rstrip(".")
        if cookie_domain and (host == cookie_domain or host.endswith(f".{cookie_domain}")):
            selected.append(cookie)
    return selected


def netscape_cookie_text(cookies: Iterable[dict[str, Any]], value: str) -> str:
    lines = ["# Netscape HTTP Cookie File", "# Generated by mangadl; cookie values are confidential."]
    for cookie in relevant_cookies(cookies, value):
        raw_domain = str(cookie.get("domain", ""))
        domain = f"#HttpOnly_{raw_domain}" if cookie.get("httpOnly") else raw_domain
        include_subdomains = "TRUE" if raw_domain.startswith(".") else "FALSE"
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        try:
            expiry = max(0, int(float(cookie.get("expires", cookie.get("expirationDate", 0)) or 0)))
        except (TypeError, ValueError):
            expiry = 0
        name = str(cookie.get("name", ""))
        value_text = str(cookie.get("value", ""))
        if not name or any("\t" in item or "\n" in item for item in (domain, name, value_text)):
            continue
        lines.append(
            "\t".join(
                (domain, include_subdomains, str(cookie.get("path", "/")), secure, str(expiry), name, value_text)
            )
        )
    return "\n".join(lines) + "\n"


def cookie_summary(path: Path, *, now: float | None = None) -> CookieSummary:
    names: list[str] = []
    expiries: list[int] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return CookieSummary(0, (), None, True)
    for line in lines:
        candidate = line[len("#HttpOnly_") :] if line.startswith("#HttpOnly_") else line
        if not candidate or candidate.startswith("#"):
            continue
        parts = candidate.split("\t")
        if len(parts) != 7:
            continue
        try:
            expiry = int(parts[4])
        except ValueError:
            expiry = 0
        names.append(parts[5])
        if expiry > 0:
            expiries.append(expiry)
    current = time.time() if now is None else now
    unexpired = any(expiry > current for expiry in expiries) or bool(names) and not expiries
    return CookieSummary(len(names), tuple(sorted(set(names))), min(expiries) if expiries else None, not unexpired)


def default_cookie_output(value: str, directory: Path | None = None) -> Path:
    return (directory or Path.cwd()).resolve() / f"{domain_for(value)}-cookies.txt"


def classify_probe(returncode: int, output: str) -> ProbeResult:
    lowered = output.lower()
    last_line = next((line.strip() for line in reversed(output.splitlines()) if line.strip()), "")
    message = last_line[:500] if last_line else f"gallery-dl exited {returncode}"
    if returncode == 0:
        return ProbeResult("success", returncode, "gallery-dl simulation succeeded")
    if any(marker in lowered for marker in CHALLENGE_MARKERS):
        return ProbeResult("challenge", returncode, message)
    if any(marker in lowered for marker in AUTH_MARKERS):
        return ProbeResult("auth_failure", returncode, message)
    if "unsupported url" in lowered or "no suitable extractor" in lowered:
        return ProbeResult("unsupported", returncode, message)
    return ProbeResult("other_failure", returncode, message)


def probe_gallery_dl(
    url: str,
    cookie_file: Path,
    user_agent: str,
    *,
    timeout: float = 60.0,
    progress: Callable[[str], None] | None = None,
) -> ProbeResult:
    command = [
        sys.executable,
        "-m",
        "gallery_dl",
        "--verbose",
        "--simulate",
        "--cookies",
        str(cookie_file),
        "--user-agent",
        user_agent,
        url,
    ]
    if progress is None:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ProbeResult("other_failure", 124, "gallery-dl validation timed out")
        return classify_probe(result.returncode, f"{result.stdout}\n{result.stderr}")

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, text=True)
        deadline = time.monotonic() + timeout
        next_notice = time.monotonic() + 5
        while process.poll() is None:
            now = time.monotonic()
            if now >= deadline:
                process.kill()
                process.wait()
                return ProbeResult("other_failure", 124, "gallery-dl validation timed out")
            if now >= next_notice:
                progress(f"gallery-dl validation is still running ({max(0, int(deadline - now))}s remaining)")
                next_notice = now + 5
            time.sleep(0.25)
        output.seek(0)
        return classify_probe(process.returncode, output.read())


def _json_endpoint(port: int, route: str) -> Any:
    request = Request(f"http://127.0.0.1:{port}{route}", headers={"Accept": "application/json"})
    with urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def _open_cdp_target(port: int, url: str) -> None:
    request = Request(
        f"http://127.0.0.1:{port}/json/new?{quote(url, safe='')}",
        headers={"Accept": "application/json"},
        method="PUT",
    )
    with urlopen(request, timeout=2) as response:
        response.read()


def find_browser(browser: str) -> Path:
    if browser not in BROWSERS:
        raise ValueError(f"unsupported browser: {browser}")
    program_files = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")]
    relative = {
        "chrome": Path("Google/Chrome/Application/chrome.exe"),
        "edge": Path("Microsoft/Edge/Application/msedge.exe"),
        "firefox": Path("Mozilla Firefox/firefox.exe"),
    }[browser]
    candidates = [Path(base) / relative for base in program_files if base]
    names = {
        "chrome": ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"),
        "edge": ("msedge", "microsoft-edge", "microsoft-edge-stable"),
        "firefox": ("firefox",),
    }[browser]
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            candidates.append(Path(resolved))
    if sys.platform == "darwin":
        candidates.append({
            "chrome": Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            "edge": Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            "firefox": Path("/Applications/Firefox.app/Contents/MacOS/firefox"),
        }[browser])
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"could not find {browser}; install it or make its executable available on PATH")


def _launch_cdp_browser(browser: str, url: str, port: int, profile_dir: Path) -> subprocess.Popen[bytes]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        [
            str(find_browser(browser)),
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )


def _launch_firefox(url: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [str(find_browser("firefox")), "-new-window", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )


def _cdp_cookies(websocket_url: str) -> list[dict[str, Any]]:
    try:
        import websocket
    except ImportError as exc:  # pragma: no cover - packaging guarantees this dependency
        raise RuntimeError("websocket-client is required for Chrome/Edge cookie extraction") from exc
    connection = websocket.create_connection(websocket_url, timeout=5, suppress_origin=True)
    try:
        connection.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
        while True:
            response = json.loads(connection.recv())
            if response.get("id") == 1:
                if "error" in response:
                    raise RuntimeError(f"browser cookie extraction failed: {response['error'].get('message', 'CDP error')}")
                return list(response.get("result", {}).get("cookies", []))
    finally:
        connection.close()


def _capture_cdp(
    url: str,
    browser: str,
    port: int,
    *,
    no_launch: bool,
    allow_launch: bool,
    auth_root: Path,
    force_open: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    try:
        version = _json_endpoint(port, "/json/version")
    except (OSError, URLError, ValueError):
        if no_launch:
            raise RuntimeError(f"no {browser} debugger is listening on 127.0.0.1:{port}")
        if allow_launch:
            _launch_cdp_browser(browser, url, port, auth_root / ".browser-profiles" / browser)
            raise RuntimeError("browser-starting")
        raise RuntimeError("browser-not-ready")
    if force_open:
        _open_cdp_target(port, url)
        raise RuntimeError("target-opening")
    targets = _json_endpoint(port, "/json")
    requested = urlparse(url)
    requested_domain = domain_for(url)
    requested_path = requested.path.rstrip("/") or "/"
    target = None
    for item in targets:
        candidate_url = str(item.get("url", ""))
        try:
            candidate = urlparse(candidate_url)
            matches = (
                domain_for(candidate_url) == requested_domain
                and (candidate.path.rstrip("/") or "/") == requested_path
            )
        except ValueError:
            matches = False
        if matches and item.get("webSocketDebuggerUrl"):
            target = item
            break
    if not target:
        try:
            _open_cdp_target(port, url)
        except (OSError, URLError, ValueError):
            pass
        raise RuntimeError("target-not-ready")
    return _cdp_cookies(target["webSocketDebuggerUrl"]), str(version.get("User-Agent", ""))


def _refresh_firefox(url: str, timeout: float, user_agent: str | None) -> tuple[str, str, ProbeResult]:
    selected_ua = user_agent or "browser"
    with tempfile.TemporaryDirectory(prefix="mangadl-firefox-") as folder:
        output = Path(folder) / "cookies.txt"
        command = [
            sys.executable,
            "-m",
            "gallery_dl",
            "--verbose",
            "--simulate",
            "--cookies-from-browser",
            "firefox",
            "--cookies-export",
            str(output),
            "--user-agent",
            selected_ua,
            url,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "", selected_ua, ProbeResult("other_failure", 124, "Firefox cookie extraction timed out")
        probe = classify_probe(result.returncode, f"{result.stdout}\n{result.stderr}")
        return (output.read_text(encoding="utf-8", errors="replace") if output.is_file() else ""), selected_ua, probe


def refresh_profile(
    url: str,
    *,
    store: ProfileStore,
    browser: str = DEFAULT_BROWSER,
    debug_port: int | None = None,
    timeout: float = 180.0,
    no_launch: bool = False,
    cookie_file: Path | None = None,
    user_agent: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[AuthProfile | None, ProbeResult]:
    if browser not in BROWSERS:
        raise ValueError(f"browser must be one of: {', '.join(BROWSERS)}")
    notify = progress or (lambda _message: None)
    domain = domain_for(url)
    destination = (cookie_file or default_cookie_output(domain)).expanduser().resolve()
    notify(f"[{domain}] preparing {browser} authentication for {url}")
    if browser == "firefox":
        if not no_launch:
            _launch_firefox(url)
            notify(f"[{domain}] opened the exact target URL in Firefox; complete any browser verification")
        else:
            notify(f"[{domain}] using an existing Firefox session; open the exact target URL if needed")
        last_firefox_probe = ProbeResult("challenge", 1, "browser authentication is not complete")
        next_firefox_notice = time.monotonic()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            notify(f"[{domain}] extracting Firefox cookies and validating the exact target URL")
            cookies, ua, last_firefox_probe = _refresh_firefox(
                url,
                min(30.0, max(1.0, deadline - time.monotonic())),
                user_agent,
            )
            if last_firefox_probe.success and cookies:
                profile = store.save(
                    domain,
                    cookies,
                    ua,
                    browser,
                    source="gallery-dl-browser",
                    cookie_file=destination,
                )
                notify(f"[{domain}] validation succeeded; wrote {destination.name}")
                return profile, last_firefox_probe
            if last_firefox_probe.status not in {"challenge", "auth_failure", "other_failure"}:
                return None, last_firefox_probe
            now = time.monotonic()
            if now >= next_firefox_notice:
                notify(
                    f"[{domain}] waiting for Firefox verification and refreshed cookies "
                    f"({max(0, int(deadline - now))}s remaining)"
                )
                next_firefox_notice = now + 5
            time.sleep(2)
        return None, ProbeResult(
            last_firefox_probe.status,
            last_firefox_probe.returncode,
            f"browser authentication was not completed within {timeout:g} seconds",
        )

    port = debug_port or DEFAULT_DEBUG_PORTS[browser]
    deadline = time.monotonic() + timeout
    launched_notice = False
    target_opened = False
    next_wait_notice = time.monotonic()
    phase = "waiting for the browser debugger"
    last_probe = ProbeResult("challenge", 1, "browser authentication is not complete")
    while time.monotonic() < deadline:
        try:
            cookies, ua = _capture_cdp(
                url,
                browser,
                port,
                no_launch=no_launch,
                allow_launch=not launched_notice,
                force_open=not target_opened,
                auth_root=store.root,
            )
        except RuntimeError as exc:
            if str(exc) == "browser-starting" and not launched_notice:
                notify(f"[{domain}] opened {browser}; complete any browser verification")
                launched_notice = True
                target_opened = True
                phase = "waiting for the browser to start"
            elif str(exc) == "target-opening":
                target_opened = True
                phase = "waiting for the exact target page and its cookies"
                notify(f"[{domain}] opened the exact target URL in {browser}")
            elif str(exc) == "target-not-ready":
                phase = "waiting for the exact target tab"
            elif str(exc) == "browser-not-ready":
                phase = "waiting for the browser debugger"
            else:
                raise
            now = time.monotonic()
            if now >= next_wait_notice:
                notify(f"[{domain}] {phase} ({max(0, int(deadline - now))}s remaining)")
                next_wait_notice = now + 5
            time.sleep(0.5)
            continue
        selected = relevant_cookies(cookies, domain)
        if not selected or not ua:
            phase = "waiting for relevant browser cookies; complete any visible challenge"
            now = time.monotonic()
            if now >= next_wait_notice:
                notify(f"[{domain}] {phase} ({max(0, int(deadline - now))}s remaining)")
                next_wait_notice = now + 5
            time.sleep(1)
            continue
        content = netscape_cookie_text(selected, domain)
        with tempfile.TemporaryDirectory(prefix="mangadl-auth-") as folder:
            candidate = Path(folder) / "cookies.txt"
            candidate.write_text(content, encoding="utf-8", newline="\n")
            notify(f"[{domain}] captured {len(selected)} relevant cookie(s); validating the exact target URL")
            last_probe = probe_gallery_dl(
                url,
                candidate,
                user_agent or ua,
                timeout=min(60.0, max(1.0, deadline - time.monotonic())),
                progress=lambda message: notify(f"[{domain}] {message}"),
            )
        if last_probe.success:
            profile = store.save(
                domain,
                content,
                user_agent or ua,
                browser,
                source=f"{browser}-cdp",
                cookie_file=destination,
            )
            notify(f"[{domain}] validation succeeded; wrote {destination.name}")
            return profile, last_probe
        if last_probe.status not in {"challenge", "auth_failure"}:
            return None, last_probe
        phase = "browser challenge is still active; complete it in the opened target tab"
        notify(f"[{domain}] {phase} ({max(0, int(deadline - time.monotonic()))}s remaining)")
        next_wait_notice = time.monotonic() + 5
        time.sleep(2)
    return None, ProbeResult(last_probe.status, last_probe.returncode, f"browser authentication was not completed within {timeout:g} seconds")
