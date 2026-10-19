# Stage 3: Side-by-Side Comparison Image Viewer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this stage task-by-task.

**Goal:** Build an interactive side-by-side image comparison viewer using Python's built-in `tkinter` + `Pillow` (zero external dependencies) that renders unchanged original images on the left and compressed candidate images on the right, allowing the user to cycle through quality levels of the same image using `Left/Right` arrow keys and cycle through different images using `Up/Down` arrow keys, with `Space` for 1:1 zoom toggle and `Esc`/`q` to close.

---

### Task 3.1: Preview Set Scanner & Data Model (`cli_tui.preview_set`)

**Files:**
- Create: `modules/cli_tui/cli_tui/preview_set.py`
- Test: `modules/cli_tui/tests/test_preview_set.py`

**Interfaces:**
- Produces:
  - `PreviewVariant`: Info about a compressed variant (recipe label e.g. `"WebP q85"`, file path, size in bytes, savings percent, dimensions).
  - `PreviewItem`: Info about a source sample image (source path, file size, dimensions, dictionary of available variants `{label: PreviewVariant}`).
  - `PreviewSet`: Collection of `PreviewItem`s with active sample index and active variant index.
  - `scan_preview_directory(directory: Path) -> PreviewSet`: Automatically finds and pairs original and candidate images produced by `preview` commands.

**Steps:**
- [ ] **Step 3.1.1: Write failing test for scanning and grouping preview variants**
  Test pairing `sample_01.orig.png` with `sample_01.webp-85.webp` and `sample_01.webp-70.webp`.
- [ ] **Step 3.1.2: Run test to verify failure**
- [ ] **Step 3.1.3: Implement `cli_tui/preview_set.py`**
- [ ] **Step 3.1.4: Run test to verify pass**
- [ ] **Step 3.1.5: Commit Task 3.1**

---

### Task 3.2: Native GUI Side-by-Side Viewer (`cli_tui.image_viewer`)

**Files:**
- Create: `modules/cli_tui/cli_tui/image_viewer.py`
- Test: `modules/cli_tui/tests/test_image_viewer.py`

**Interfaces:**
- Produces:
  - `SideBySideImageViewer`: Tkinter-based dual-panel viewer window.
  - Left panel: Original (unchanged) image with label and size.
  - Right panel: Selected candidate variant with format, quality label, file size, and calculated byte savings / percentage.
  - Key bindings:
    - `Left Arrow`: Select previous quality level/variant of the same image.
    - `Right Arrow`: Select next quality level/variant of the same image.
    - `Up Arrow`: Previous image in the preview set.
    - `Down Arrow`: Next image in the preview set.
    - `Space`: Toggle 1:1 pixel zoom vs fit-to-panel.
    - `Esc` / `q` / `Q`: Close window immediately and return control.
  - Headless/no-display fallback: Detects `_tkinter.TclError` / missing display, printing clear diagnostic and preview file paths rather than crashing.

**Steps:**
- [ ] **Step 3.2.1: Write unit tests for viewer navigation logic, index wrapping, and key event handlers**
- [ ] **Step 3.2.2: Run test to verify failure**
- [ ] **Step 3.2.3: Implement `cli_tui/image_viewer.py`**
- [ ] **Step 3.2.4: Run test to verify pass**
- [ ] **Step 3.2.5: Commit Task 3.2**

---

### Task 3.3: Integration with MangaDL & Standalone CLI

**Files:**
- Modify: `modules/compresser/compresser/preview.py`
- Modify: `modules/mangadl/mangadl/compress.py`
- Modify: `modules/mangadl/mangadl/tui.py`
- Test: `modules/mangadl/tests/compress_test.py`

**Interfaces:**
- Produces:
  - Add `--view` flag to `compress preview` (`mangadl compress preview --view`), automatically opening the side-by-side viewer when previews are generated.
  - Direct menu entry in `mangadl tui`: `[ 🔍 View Side-by-Side Previews ]`.
  - Automatic prompt in TUI runner when preview finishes: `[ View Previews (v) ]`.

**Steps:**
- [ ] **Step 3.3.1: Write failing test for `--view` argument and viewer trigger**
- [ ] **Step 3.3.2: Run test to verify failure**
- [ ] **Step 3.3.3: Implement `--view` flag and TUI runner link**
- [ ] **Step 3.3.4: Run test to verify pass**
- [ ] **Step 3.3.5: Commit Task 3.3**
