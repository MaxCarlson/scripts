from __future__ import annotations

import io
import json
from email.message import Message
from pathlib import Path

import pytest

from mangadl.covers import (
    METADATA_DIR_NAME,
    SOURCE_MANIFEST_NAME,
    _pick_metadata,
    collect_url_folder,
    discover_url_files,
    match_folder,
    parse_path_maps,
    tree_stats_without_metadata,
    write_cover_for_folder,
)


class FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        super().__init__(payload)
        headers = Message()
        headers["Content-Type"] = content_type
        self.headers = headers

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class FakeOpener:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses

    def open(self, request: object, timeout: float) -> FakeResponse:
        url = request.full_url
        response = self.responses[url]
        return FakeResponse(response.getvalue(), response.headers.get("Content-Type", "application/octet-stream"))


def jpeg_payload() -> bytes:
    return b"\xff\xd8\xff" + b"x" * 2048


def test_discover_url_files_is_recursive_case_insensitive_and_sorted(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "url2.txt").write_text("https://manga18fx.com/manga/two/\n", encoding="utf-8")
    (tmp_path / "nested" / "URL1.TXT").write_text("https://simply-hentai.com/one/\n", encoding="utf-8")
    (tmp_path / "other.txt").write_text("ignored\n", encoding="utf-8")

    files = discover_url_files(tmp_path)

    assert {path.name for path in files} == {"url2.txt", "URL1.TXT"}
    inputs, rejected, loaded = collect_url_folder(tmp_path)
    assert len(inputs) == 2
    assert not rejected
    assert loaded == files


def test_page_parser_prefers_open_graph_and_resolves_relative_cover() -> None:
    metadata = _pick_metadata(
        """
        <html><head>
          <meta property="og:title" content="Example Series">
          <meta property="og:image" content="/covers/example.webp">
          <link rel="canonical" href="https://manga18fx.com/manga/example/">
        </head><body><h1>Wrong title</h1></body></html>
        """,
        "https://manga18fx.com/manga/example/",
    )

    assert metadata.title == "Example Series"
    assert metadata.cover_url == "https://manga18fx.com/covers/example.webp"
    assert metadata.canonical_url == "https://manga18fx.com/manga/example/"


def test_match_folder_uses_authoritative_source_manifest(tmp_path: Path) -> None:
    folder = tmp_path / "Different Display Name"
    metadata_dir = folder / METADATA_DIR_NAME
    metadata_dir.mkdir(parents=True)
    (folder / "0001.jpg").write_bytes(jpeg_payload())
    (metadata_dir / SOURCE_MANIFEST_NAME).write_text(
        json.dumps({"canonical_url": "https://manga18fx.com/manga/example/"}),
        encoding="utf-8",
    )

    match, candidates = match_folder("https://manga18fx.com/manga/example/", [folder])

    assert match is not None
    assert match.folder == folder
    assert match.method == "source-metadata"
    assert candidates == [match]


def test_write_cover_is_dry_run_by_default_and_apply_writes_manifest(tmp_path: Path) -> None:
    folder = tmp_path / "Example Series"
    folder.mkdir()
    (folder / "0001.jpg").write_bytes(jpeg_payload())
    html = b'<meta property="og:title" content="Example Series"><meta property="og:image" content="/cover.jpg">'
    opener = FakeOpener(
        {
            "https://manga18fx.com/manga/example/": FakeResponse(html),
            "https://manga18fx.com/cover.jpg": FakeResponse(jpeg_payload(), "image/jpeg"),
        }
    )

    planned = write_cover_for_folder(
        "https://manga18fx.com/manga/example/",
        folder,
        apply=False,
        opener=opener,
    )
    assert planned.status == "planned"
    assert not (folder / METADATA_DIR_NAME).exists()

    written = write_cover_for_folder(
        "https://manga18fx.com/manga/example/",
        folder,
        apply=True,
        opener=opener,
    )
    assert written.status == "downloaded"
    manifest = json.loads((folder / METADATA_DIR_NAME / SOURCE_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["canonical_url"] == "https://manga18fx.com/manga/example/"
    assert manifest["cover_sha256"]
    assert Path(written.cover_file).is_file()


def test_tree_stats_excludes_managed_cover(tmp_path: Path) -> None:
    (tmp_path / "Series" / METADATA_DIR_NAME).mkdir(parents=True)
    (tmp_path / "Series" / "0001.jpg").write_bytes(jpeg_payload())
    (tmp_path / "Series" / METADATA_DIR_NAME / "cover-original.jpg").write_bytes(jpeg_payload())

    images, size = tree_stats_without_metadata(tmp_path)

    assert images == 1
    assert size == len(jpeg_payload())


def test_parse_path_maps_rejects_invalid_values() -> None:
    assert parse_path_maps([r"B:\\Manga=/manga"]) == [(r"B:\\Manga", "/manga")]
    with pytest.raises(ValueError):
        parse_path_maps(["invalid"])


def test_page_parser_falls_back_to_madara_summary_image_and_json_ld_title() -> None:
    metadata = _pick_metadata(
        """
        <html><head>
          <script type="application/ld+json">
            {"@type": "Book", "name": "JSON Title"}
          </script>
        </head><body>
          <div class="summary_image"><img data-src="/covers/summary.jpg"></div>
        </body></html>
        """,
        "https://manga18fx.com/manga/example/",
    )

    assert metadata.title == "JSON Title"
    assert metadata.cover_url == "https://manga18fx.com/covers/summary.jpg"


def test_supported_cover_hosts_include_both_initial_sites() -> None:
    from mangadl.covers import supports_cover_url

    assert supports_cover_url("https://manga18fx.com/manga/example/")
    assert supports_cover_url("https://simply-hentai.com/example/")
    assert not supports_cover_url("https://example.com/example/")


def test_kavita_path_mapping_matches_container_visible_folder(tmp_path: Path) -> None:
    from mangadl.covers import KavitaClient

    folder = tmp_path / "Manga" / "Example Series"
    folder.mkdir(parents=True)
    client = KavitaClient(
        "http://kavita.invalid",
        "secret",
        path_maps=[(str(tmp_path / "Manga"), "/manga")],
        opener=object(),
    )

    matched = client.match_series(
        folder,
        [
            {
                "id": 42,
                "name": "Example Series",
                "folderPath": "/manga/example series",
                "lowestFolderPath": "/manga/example series",
            }
        ],
    )

    assert matched is not None
    assert matched["id"] == 42


class FakeKavitaClient:
    def __init__(self, series: dict[str, object] | None) -> None:
        self.series = series
        self.applied: list[tuple[int, Path]] = []

    def list_series(self) -> list[dict[str, object]]:
        return [self.series] if self.series is not None else []

    def match_series(self, folder: Path, series: object) -> dict[str, object] | None:
        return self.series

    def apply_cover(self, series_id: int, cover: Path) -> None:
        self.applied.append((series_id, cover))


def test_apply_kavita_cover_records_pending_then_applied(tmp_path: Path) -> None:
    from mangadl.covers import (
        COVER_APPLIED_NAME,
        COVER_PENDING_NAME,
        CoverResult,
        apply_kavita_cover,
    )

    folder = tmp_path / "Example"
    metadata_dir = folder / METADATA_DIR_NAME
    metadata_dir.mkdir(parents=True)
    cover = metadata_dir / "cover-original.jpg"
    cover.write_bytes(jpeg_payload())
    result = CoverResult(
        url="https://manga18fx.com/manga/example/",
        status="downloaded",
        folder=str(folder),
        cover_file=str(cover),
    )

    pending = apply_kavita_cover(
        result,
        folder,
        kavita_url="http://kavita.invalid",
        api_key="secret",
        client=FakeKavitaClient(None),
    )
    assert pending.status == "kavita_pending"
    assert (metadata_dir / COVER_PENDING_NAME).is_file()

    client = FakeKavitaClient({"id": 42, "name": "Example"})
    applied = apply_kavita_cover(
        result,
        folder,
        kavita_url="http://kavita.invalid",
        api_key="secret",
        client=client,
    )
    assert applied.status == "applied_kavita"
    assert applied.kavita_series_id == 42
    assert client.applied == [(42, cover)]
    assert (metadata_dir / COVER_APPLIED_NAME).is_file()
    assert not (metadata_dir / COVER_PENDING_NAME).exists()
