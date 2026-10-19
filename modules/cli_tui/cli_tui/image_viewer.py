from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Optional, Tuple

from .preview_set import PreviewItem, PreviewSet, PreviewVariant, scan_preview_directory


def calculate_fit_dimensions(
    image_w: int, image_h: int, max_w: int, max_h: int
) -> Tuple[int, int]:
    """Calculate scaled dimensions preserving aspect ratio to fit within container bounds."""
    if image_w <= 0 or image_h <= 0 or max_w <= 0 or max_h <= 0:
        return (max(1, max_w), max(1, max_h))
    scale = min(max_w / image_w, max_h / image_h)
    new_w = max(1, int(round(image_w * scale)))
    new_h = max(1, int(round(image_h * scale)))
    return (new_w, new_h)


class ImageViewerState:
    """State manager for side-by-side image comparison navigation."""

    def __init__(self, preview_set: PreviewSet) -> None:
        self.preview_set = preview_set
        self.is_zoomed_1_to_1: bool = False
        self.is_closed: bool = False

    @property
    def current_item(self) -> Optional[PreviewItem]:
        return self.preview_set.current_item

    @property
    def current_variant(self) -> Optional[PreviewVariant]:
        return self.preview_set.current_variant

    def handle_key(self, keysym: str) -> bool:
        """Process keyboard keysym and update state."""
        if keysym in ("Escape", "q", "Q"):
            self.is_closed = True
            return True
        elif keysym in ("Left", "h", "H"):
            self.preview_set.prev_variant()
            return True
        elif keysym in ("Right", "l", "L"):
            self.preview_set.next_variant()
            return True
        elif keysym in ("Up", "k", "K"):
            self.preview_set.prev_image()
            return True
        elif keysym in ("Down", "j", "J"):
            self.preview_set.next_image()
            return True
        elif keysym == "space":
            self.is_zoomed_1_to_1 = not self.is_zoomed_1_to_1
            return True
        return False


def _format_bytes(size: int) -> str:
    """Format bytes into human-readable KiB / MiB."""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.2f} MiB"


class SideBySideImageViewer:
    """Native Tkinter side-by-side image comparator."""

    def __init__(self, root: Any, state: ImageViewerState) -> None:
        self.root = root
        self.state = state

        self.root.title("MangaDL Side-by-Side Comparison Viewer")
        self.root.geometry("1400x900")
        self.root.minsize(800, 500)
        self.root.configure(bg="#181818")

        # Top Header Bar
        self.header_frame = self._create_header()

        # Center Container with Left & Right Panels
        self.center_frame = self._create_center_panels()

        # Bottom Instructions Footer Bar
        self.footer_frame = self._create_footer()

        # Bind Key & Resize events
        self.root.bind("<Key>", self._on_key)
        self.root.bind("<Configure>", self._on_resize)
        self._last_width = 1400
        self._last_height = 900

        self.left_photo = None
        self.right_photo = None

        self.render()

    def _create_header(self) -> Any:
        import tkinter as tk

        frame = tk.Frame(self.root, bg="#242424", height=40)
        frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(8, 4))

        self.lbl_left_title = tk.Label(
            frame,
            text="Original (Unchanged)",
            bg="#242424",
            fg="#FFFFFF",
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        )
        self.lbl_left_title.pack(side=tk.LEFT, padx=12, pady=6)

        self.lbl_right_title = tk.Label(
            frame,
            text="Candidate",
            bg="#242424",
            fg="#68D391",
            font=("Segoe UI", 11, "bold"),
            anchor="e",
        )
        self.lbl_right_title.pack(side=tk.RIGHT, padx=12, pady=6)
        return frame

    def _create_center_panels(self) -> Any:
        import tkinter as tk

        container = tk.Frame(self.root, bg="#181818")
        container.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=4)

        # Left Panel (Original)
        self.left_canvas = tk.Canvas(
            container, bg="#111111", highlightthickness=1, highlightbackground="#333333"
        )
        self.left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        # Right Panel (Candidate)
        self.right_canvas = tk.Canvas(
            container, bg="#111111", highlightthickness=1, highlightbackground="#333333"
        )
        self.right_canvas.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(4, 0))

        return container

    def _create_footer(self) -> Any:
        import tkinter as tk

        frame = tk.Frame(self.root, bg="#242424", height=35)
        frame.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(4, 8))

        self.lbl_nav_hint = tk.Label(
            frame,
            text="[← / →] Quality Level    [↑ / ↓] Sample Image    [Space] Zoom (Fit / 1:1)    [q / Esc] Close",
            bg="#242424",
            fg="#A0AEC0",
            font=("Segoe UI", 10),
            anchor="w",
        )
        self.lbl_nav_hint.pack(side=tk.LEFT, padx=12, pady=6)

        self.lbl_progress = tk.Label(
            frame,
            text="Image 1 of 1",
            bg="#242424",
            fg="#ECC94B",
            font=("Segoe UI", 10, "bold"),
            anchor="e",
        )
        self.lbl_progress.pack(side=tk.RIGHT, padx=12, pady=6)
        return frame

    def _on_key(self, event: Any) -> None:
        handled = self.state.handle_key(event.keysym)
        if handled:
            if self.state.is_closed:
                self.root.destroy()
            else:
                self.render()

    def _on_resize(self, event: Any) -> None:
        if event.widget is self.root:
            if (
                abs(event.width - self._last_width) > 20
                or abs(event.height - self._last_height) > 20
            ):
                self._last_width = event.width
                self._last_height = event.height
                self.render()

    def render(self) -> None:
        """Render both original and candidate images on dual canvas panels."""
        from PIL import Image, ImageTk

        item = self.state.current_item
        variant = self.state.current_variant
        if not item:
            return

        ps = self.state.preview_set
        current_num = ps.item_index + 1
        total_num = len(ps.items)
        self.lbl_progress.configure(text=f"Image {current_num} of {total_num}")

        # Update Titles
        orig_name = item.source_path.name
        orig_size_str = _format_bytes(item.size_bytes)
        self.lbl_left_title.configure(text=f"Original: {orig_name} ({orig_size_str})")

        if variant:
            var_size_str = _format_bytes(variant.size_bytes)
            saved = variant.original_size_bytes - variant.size_bytes
            saved_str = _format_bytes(max(0, saved))
            pct = variant.savings_percent
            self.lbl_right_title.configure(
                text=f"Candidate: {variant.recipe} ({var_size_str})  —  Saved: {saved_str} ({pct}%)"
            )
        else:
            self.lbl_right_title.configure(text="Candidate: None available")

        # Render Left Image
        self.left_canvas.update_idletasks()
        cw = max(100, self.left_canvas.winfo_width())
        ch = max(100, self.left_canvas.winfo_height())

        if item.source_path.exists():
            try:
                with Image.open(item.source_path) as orig_img:
                    orig_img = orig_img.convert("RGBA")
                    iw, ih = orig_img.size
                    if self.state.is_zoomed_1_to_1:
                        target_w, target_h = iw, ih
                    else:
                        target_w, target_h = calculate_fit_dimensions(
                            iw, ih, cw - 20, ch - 20
                        )
                    resized = orig_img.resize(
                        (target_w, target_h), Image.Resampling.LANCZOS
                    )
                    self.left_photo = ImageTk.PhotoImage(resized)
                    self.left_canvas.delete("all")
                    self.left_canvas.create_image(
                        cw // 2, ch // 2, image=self.left_photo, anchor="center"
                    )
            except Exception as e:
                self.left_canvas.delete("all")
                self.left_canvas.create_text(
                    cw // 2,
                    ch // 2,
                    text=f"Failed to load image:\n{e}",
                    fill="#E53E3E",
                    font=("Segoe UI", 11),
                )

        # Render Right Image
        self.right_canvas.update_idletasks()
        rw = max(100, self.right_canvas.winfo_width())
        rh = max(100, self.right_canvas.winfo_height())

        if variant and variant.path.exists():
            try:
                with Image.open(variant.path) as cand_img:
                    cand_img = cand_img.convert("RGBA")
                    iw, ih = cand_img.size
                    if self.state.is_zoomed_1_to_1:
                        target_w, target_h = iw, ih
                    else:
                        target_w, target_h = calculate_fit_dimensions(
                            iw, ih, rw - 20, rh - 20
                        )
                    resized = cand_img.resize(
                        (target_w, target_h), Image.Resampling.LANCZOS
                    )
                    self.right_photo = ImageTk.PhotoImage(resized)
                    self.right_canvas.delete("all")
                    self.right_canvas.create_image(
                        rw // 2, rh // 2, image=self.right_photo, anchor="center"
                    )
            except Exception as e:
                self.right_canvas.delete("all")
                self.right_canvas.create_text(
                    rw // 2,
                    rh // 2,
                    text=f"Failed to load candidate:\n{e}",
                    fill="#E53E3E",
                    font=("Segoe UI", 11),
                )


def launch_image_viewer(
    preview_set: Optional[PreviewSet] = None,
    destination: Optional[Path | str] = None,
) -> int:
    """Launch the interactive side-by-side image comparison viewer."""
    if preview_set is None:
        if destination is None:
            destination = Path(".")
        preview_set = scan_preview_directory(destination)

    if not preview_set or not preview_set.items:
        print("No preview images found to display.", file=sys.stderr)
        return 0

    try:
        import tkinter as tk

        root = tk.Tk()
    except Exception as exc:
        print(f"Could not open GUI window ({exc}).", file=sys.stderr)
        print("Preview images available at:")
        for item in preview_set.items:
            print(f"  Original: {item.source_path}")
            for var in item.variants:
                print(f"    - {var.recipe}: {var.path}")
        return 0

    try:
        state = ImageViewerState(preview_set)
        _app = SideBySideImageViewer(root, state)
        root.mainloop()
        return 0
    except Exception as exc:
        print(f"Error running comparison viewer: {exc}", file=sys.stderr)
        return 1
