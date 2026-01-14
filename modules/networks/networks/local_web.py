#!/usr/bin/env python3
"""
Local Web Access - Fetch HTML and screenshots from local/LAN URLs.

AI CLI tools (Claude Code, Codex, etc.) cannot access private network URLs
because their requests go through cloud servers. This module runs locally
and can access any URL your machine can reach.

Features:
- Fetch HTML content from local/LAN URLs
- Take screenshots using headless browser (playwright)
- LLM-optimized output (JSON, minimal) and human-friendly output
"""
import base64
import json
import logging
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """Result of fetching a URL."""
    url: str
    success: bool
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    content: Optional[str] = None
    content_length: Optional[int] = None
    error: Optional[str] = None
    headers: Optional[Dict[str, str]] = None

    def to_json(self) -> str:
        """Serialize to JSON for LLM consumption."""
        return json.dumps(asdict(self), indent=2)

    def to_human(self) -> str:
        """Format for human-readable output."""
        if not self.success:
            return f"✗ Failed to fetch {self.url}\n  Error: {self.error}"

        lines = [
            f"✓ {self.url}",
            f"  Status: {self.status_code}",
            f"  Type: {self.content_type}",
            f"  Size: {self.content_length} bytes",
        ]
        if self.content:
            preview = self.content[:500] + "..." if len(self.content) > 500 else self.content
            lines.append(f"\n{preview}")
        return "\n".join(lines)


@dataclass
class ScreenshotResult:
    """Result of taking a screenshot."""
    url: str
    success: bool
    output_path: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    error: Optional[str] = None
    base64_data: Optional[str] = None  # For inline LLM consumption

    def to_json(self) -> str:
        """Serialize to JSON for LLM consumption."""
        data = asdict(self)
        # Don't include huge base64 in JSON by default
        if self.base64_data and len(self.base64_data) > 1000:
            data['base64_data'] = f"<{len(self.base64_data)} bytes - use --inline to include>"
        return json.dumps(data, indent=2)

    def to_human(self) -> str:
        """Format for human-readable output."""
        if not self.success:
            return f"✗ Failed to screenshot {self.url}\n  Error: {self.error}"
        return f"✓ Screenshot saved: {self.output_path} ({self.width}x{self.height})"


def is_local_url(url: str) -> bool:
    """Check if URL points to local/private network."""
    parsed = urlparse(url)
    host = parsed.hostname or ""

    # Localhost variants
    if host in ('localhost', '127.0.0.1', '::1'):
        return True

    # Private IP ranges
    try:
        import ipaddress
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback
    except ValueError:
        # Not an IP, could be a hostname
        pass

    # .local domains
    if host.endswith('.local'):
        return True

    return False


def fetch_url(
    url: str,
    timeout: float = 10.0,
    include_headers: bool = False,
    verify_ssl: bool = True,
) -> FetchResult:
    """
    Fetch HTML content from a URL.

    Works with local/LAN URLs that cloud AI tools cannot access.

    Args:
        url: The URL to fetch
        timeout: Request timeout in seconds
        include_headers: Include response headers in result
        verify_ssl: Verify SSL certificates (disable for self-signed)

    Returns:
        FetchResult with content or error information
    """
    logger.info(f"Fetching URL: {url}")

    try:
        # Create SSL context if needed
        context = None
        if not verify_ssl:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        # Create request with user agent
        request = urllib.request.Request(
            url,
            headers={'User-Agent': 'local-web/1.0 (AI Agent Tool)'}
        )

        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            content = response.read()
            charset = response.headers.get_content_charset() or 'utf-8'

            try:
                content_str = content.decode(charset)
            except UnicodeDecodeError:
                content_str = content.decode('utf-8', errors='replace')

            headers = dict(response.headers) if include_headers else None

            return FetchResult(
                url=url,
                success=True,
                status_code=response.status,
                content_type=response.headers.get('Content-Type'),
                content=content_str,
                content_length=len(content),
                headers=headers,
            )

    except urllib.error.HTTPError as e:
        return FetchResult(
            url=url,
            success=False,
            status_code=e.code,
            error=f"HTTP {e.code}: {e.reason}",
        )
    except urllib.error.URLError as e:
        return FetchResult(
            url=url,
            success=False,
            error=f"URL Error: {e.reason}",
        )
    except socket.timeout:
        return FetchResult(
            url=url,
            success=False,
            error=f"Timeout after {timeout}s",
        )
    except Exception as e:
        return FetchResult(
            url=url,
            success=False,
            error=str(e),
        )


def screenshot_url(
    url: str,
    output_path: Optional[Path] = None,
    width: int = 1280,
    height: int = 720,
    full_page: bool = True,
    timeout: float = 30.0,
    include_base64: bool = False,
) -> ScreenshotResult:
    """
    Take a screenshot of a URL using headless browser.

    Requires playwright to be installed:
        pip install playwright
        playwright install chromium

    Args:
        url: The URL to screenshot
        output_path: Where to save the screenshot (default: temp file)
        width: Viewport width
        height: Viewport height
        full_page: Capture full scrollable page
        timeout: Page load timeout in seconds
        include_base64: Include base64 data in result for LLM inline viewing

    Returns:
        ScreenshotResult with file path or error information
    """
    logger.info(f"Taking screenshot of: {url}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ScreenshotResult(
            url=url,
            success=False,
            error="playwright not installed. Run: pip install playwright && playwright install chromium",
        )

    # Default output path
    if output_path is None:
        import tempfile
        output_path = Path(tempfile.mktemp(suffix='.png', prefix='screenshot_'))
    else:
        output_path = Path(output_path)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': width, 'height': height})

            # Navigate with timeout
            page.goto(url, wait_until='networkidle', timeout=timeout * 1000)

            # Take screenshot
            page.screenshot(path=str(output_path), full_page=full_page)

            browser.close()

        # Read base64 if requested
        base64_data = None
        if include_base64:
            with open(output_path, 'rb') as f:
                base64_data = base64.b64encode(f.read()).decode('ascii')

        return ScreenshotResult(
            url=url,
            success=True,
            output_path=str(output_path),
            width=width,
            height=height,
            base64_data=base64_data,
        )

    except Exception as e:
        return ScreenshotResult(
            url=url,
            success=False,
            error=str(e),
        )


def check_local_access(url: str, timeout: float = 5.0) -> Tuple[bool, str]:
    """
    Quick check if a local URL is accessible.

    Args:
        url: URL to check
        timeout: Connection timeout

    Returns:
        Tuple of (is_accessible, message)
    """
    parsed = urlparse(url)
    host = parsed.hostname or 'localhost'
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)

    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True, f"✓ {host}:{port} is accessible"
    except socket.timeout:
        return False, f"✗ {host}:{port} timed out after {timeout}s"
    except ConnectionRefusedError:
        return False, f"✗ {host}:{port} connection refused (service not running?)"
    except socket.gaierror as e:
        return False, f"✗ {host} - DNS resolution failed: {e}"
    except Exception as e:
        return False, f"✗ {host}:{port} - {e}"


# Convenience aliases for LLM-friendly naming
fetch = fetch_url
screenshot = screenshot_url
check = check_local_access
