downloads_dlpn/manga-mgmt/model_manager/model_manager.py
downloads_dlpn/manga-mgmt/quantize-manga.py
downloads_dlpn/manga-mgmt/summarize-manga.py

# Refactoring Plan: Manga Analyzer

**Goal:** Create a dedicated project for the AI-powered manga analysis suite, to be named `manga-analyzer` and located in `pyprjs/`.

### Source Files to Migrate:

- `downloads_dlpn/manga-mgmt/summarize-manga.py`
- `downloads_dlpn/manga-mgmt/quantize-manga.py`
- `downloads_dlpn/manga-mgmt/model_manager/` (entire subdirectory)

### Execution Plan:

1.  **Create Project:** Create a new directory `pyprjs/manga-analyzer`.
2.  **Migrate Core Logic:** Move the three source items listed above directly into the new project directory.
3.  **Establish Project Structure:** Create a `pyproject.toml` file to manage dependencies (`transformers`, `torch`, `bitsandbytes`, `accelerate`, `llama_cpp`, `pytesseract`, etc.) and define a CLI entry point if desired.
4.  **Separate Data Acquisition:** The script `downloads_dlpn/manga-mgmt/scrape-nhentai-tags.py` should **not** be included in this project. Its purpose is data acquisition, and it should be moved into the proposed `media-dl` project. The `poptags.json` file it produces can be considered a shared artifact that this `manga-analyzer` project consumes.
5.  **Note on `model_manager`:** The `model_manager` is a highly reusable component. For now, it will reside within this project. If other projects begin to require local LLM management, it should be promoted to a shared module at `modules/llm_manager`.

### Files to Delete Post-Refactoring:

- The entire `downloads_dlpn/manga-mgmt/` directory, after its contents have been migrated to `pyprjs/manga-analyzer` and `pyprjs/media-dl`.