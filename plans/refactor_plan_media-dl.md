# Refactoring Plan: Media Downloader

**Goal:** Create a unified, extensible media downloading framework named `media-dl` under `pyprjs`.

### Source Files to Merge:

- **Core Runner:** `downloads_dlpn/scripts/roundrobin_ytdlp.py`
- **Downloader Logic:**
  - `downloads_dlpn/scripts/aebndl_dlpn.py`
  - `downloads_dlpn/nhentai-dl/dlnh.py` & `dlnhv2.py`
- **Extractor Logic:**
  - `pscripts/video/m3u8_extractor2.py`
  - `downloads_dlpn/scripts/roundrr.py` (for its `pyppeteer` logic)
- **Utilities:**
  - `downloads_dlpn/manga-mgmt/scrape-nhentai-tags.py`

### Execution Plan:

1.  **Create Project:** Create a new directory `pyprjs/media-dl`.
2.  **Establish Core:** Use `roundrobin_ytdlp.py` and its `termdash`-based UI as the core parallel runner for the application.
3.  **Develop Plugin System:** Design a simple plugin or configuration-based architecture where different downloaders can be specified for different URL patterns or types.
4.  **Implement Backends:**
    -   Create a `ytdlp` backend using the existing logic.
    -   Create an `aebndl` backend by adapting the wrapper logic from `aebndl_dlpn.py`.
    -   Create an `nhentai` backend by merging `dlnh.py` and `dlnhv2.py`.
    -   Create a `manifest` extractor using the `pyppeteer` logic from `m3u8_extractor2.py` and `roundrr.py`, to be used as a fallback for difficult sites.
5.  **Integrate Utilities:** Move the tag scraper into this project as a utility script (`pyprjs/media-dl/utils/scrape_tags.py`).

### Files to Delete Post-Refactoring:

- All source scripts listed above.
- The `downloads_dlpn/nhentai-dl/` directory.
