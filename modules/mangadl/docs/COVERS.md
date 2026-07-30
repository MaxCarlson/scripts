# Managed Source Covers

MangaDL can preserve the cover advertised by a source series page and optionally upload that image to Kavita as a locked series cover.

## Managed files

For a matched series folder, MangaDL writes:

```text
Series Name/
├── ... downloaded chapters or pages ...
└── _mangadl/
    ├── cover-original.<ext>
    ├── source.json
    ├── cover-applied.json          # after a successful Kavita upload
    └── cover-kavita-pending.json   # when Kavita has not indexed/matched the series yet
```

Add this exclusion pattern to the relevant Kavita library:

```text
**/_mangadl/*
```

MangaDL excludes `_mangadl` from its own image/page counts. Existing managed covers are retained unless `-F/--force` is used. Replaced covers and manifests are preserved as timestamped `previous-*` files.

## Backfill from a URL folder

`-U/--urls-folder` is scanned recursively. Every regular file whose name starts with `url` and ends with `.txt`, case-insensitively, is treated as a URL list. Blank lines, comments, duplicates, and malformed lines use the normal MangaDL input parser.

Dry-run is the default:

```powershell
mangadl covers -U 'C:\path\to\url-files' -d 'B:\Manga'
```

Download covers and write `_mangadl` metadata:

```powershell
mangadl covers -U 'C:\path\to\url-files' -d 'B:\Manga' -f
```

Use `-d/--destination` more than once when the URL files may correspond to multiple library roots. Results distinguish matched, ambiguous, not-downloaded, unsupported, and failed URLs. Ambiguous matches are never written automatically.

## Kavita application

Create a Kavita Auth Key and place it in an environment variable rather than a command-line argument:

```powershell
$env:KAVITA_API_KEY = '<auth-key>'
```

Apply and lock matched covers:

```powershell
mangadl covers -U 'C:\path\to\url-files' -d 'B:\Manga' -f -K -k 'http://192.168.50.100:5000'
```

When MangaDL and Kavita see different paths, add one or more local-to-Kavita mappings:

```powershell
mangadl covers -U 'C:\path\to\url-files' -d 'B:\Manga' -f -K -k 'http://192.168.50.100:5000' -M 'B:\Manga=/manga'
```

Kavita matching prefers exact `folderPath`/`lowestFolderPath` matches. A unique normalized series-name match is only a fallback. If Kavita has not indexed a newly downloaded series, MangaDL writes `cover-kavita-pending.json`; rerunning `mangadl covers ... -f -K` after a Kavita scan applies it.

## Automatic covers during downloads

Normal `mangadl run` jobs automatically scrape and save a managed cover after a successful download from a configured source. A cover failure is logged but does not convert a successful manga download into a failed job.

Disable automatic cover downloads for a run:

```powershell
mangadl run -i .\urls.txt -d 'B:\Manga' -a .\archive.sqlite3 -X
```

Kavita application is an explicit external write and is configured through the advanced run surface:

```powershell
$env:KAVITA_API_KEY = '<auth-key>'
mangadl run config -i .\urls.txt -d 'B:\Manga' -a .\archive.sqlite3 -F -j 'http://192.168.50.100:5000'
```

For a containerized Kavita path:

```powershell
mangadl run config -i .\urls.txt -d 'B:\Manga' -a .\archive.sqlite3 -F -j 'http://192.168.50.100:5000' -L 'B:\Manga=/manga'
```

Run flags:

- `-X/--no-download-covers`: disable managed cover fetching.
- `-F/--apply-kavita-covers`: upload and lock covers in Kavita.
- `-j/--kavita-url`: Kavita base URL.
- `-S/--kavita-api-key-env`: environment variable containing the Auth Key; default `KAVITA_API_KEY`.
- `-L/--kavita-path-map`: repeatable `LOCAL=KAVITA` path mapping.

## Current source adapters

The first implementation recognizes `manga18fx.com` and `simply-hentai.com`. Extraction is layered rather than tied to a single fragile selector:

1. Open Graph image/title metadata.
2. Twitter image/title metadata.
3. JSON-LD image/title metadata.
4. Manga18FX/Madara-style `.summary_image` images.
5. `itemprop="image"` images.
6. Page heading/title fallbacks for the series title.

The live DOM and response behavior for each site must still be validated with representative URLs. Site-specific selectors can then be tightened without changing folder matching, storage, or Kavita integration.
