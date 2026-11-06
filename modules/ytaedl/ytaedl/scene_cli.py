"""Inspect AEBN movie and scene metadata without starting a download."""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urldefrag, urlsplit

from .downloader import _extract_aebn_scene_id, _read_urls


def _session():
    from aebn_dl.custom_session import CustomSession

    session = CustomSession(impersonate="chrome")
    session.timeout = 30
    session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"
    session.cookies.update({"ageGated": "true", "terms": "true"})
    return session


def inspect_urls(urls, movie_factory=None, session=None):
    if movie_factory is None:
        from aebn_dl.movie_scraper import Movie
        movie_factory = Movie
    if session is None:
        session = _session()
    cache = {}
    results = []
    for url in urls:
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or not parsed.hostname.lower().endswith(".aebn.com"):
                raise ValueError("Expected an AEBN movie URL")
            parts = parsed.path.strip("/").split("/")
            if len(parts) < 4 or parts[1] != "movies" or not parts[2].isdigit():
                raise ValueError("Expected an AEBN movie URL")
            scene_id = _extract_aebn_scene_id(url)
            movie_url, _ = urldefrag(url)
            if movie_url not in cache:
                cache[movie_url] = movie_factory(movie_url, session)
            movie = cache[movie_url]
            ordinal = movie.scene_ordinal_for_id(scene_id) if scene_id is not None else None
            results.append({"url": url, "title": movie.title, "scene_id": scene_id,
                            "scene_ordinal": ordinal, "scene_count": len(movie.scenes),
                            "status": "selected" if scene_id is not None else "no_scene_requested"})
        except Exception as exc:
            results.append({"url": url, "status": "error", "error": str(exc) or type(exc).__name__})
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect AEBN scene metadata without downloading media")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("-u", "--url")
    source.add_argument("-f", "--file", type=Path)
    parser.add_argument("-j", "--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        urls = [args.url] if args.url else _read_urls(args.file)
        if not urls:
            raise ValueError("URL file contains no URLs")
        results = inspect_urls(urls)
    except Exception as exc:
        results = [{"status": "error", "error": str(exc) or type(exc).__name__}]
    if args.json:
        print(json.dumps(results, ensure_ascii=False))
    else:
        for result in results:
            if result["status"] == "error":
                print(f"{result.get('url', '')}: {result['error']}", file=sys.stderr)
            else:
                selection = (f"scene {result['scene_ordinal']}/{result['scene_count']} (ID {result['scene_id']})"
                             if result["scene_id"] else "no scene requested")
                print(f"{result['title']}: {selection} — {result['url']}")
    return int(any(result["status"] == "error" for result in results))
