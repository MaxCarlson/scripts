# Content-Aware, Display-Limited Image Compression – Implementation Plan

This document adds **perceptual, device-aware** logic to `imgshrink` without breaking existing interfaces.
The goal is to compress *to the edge of visibility*, given a target device (screen size, resolution, viewing distance).

## New modules (additive, no existing files changed)

- `imgshrink/display.py` – device/profile math (PPI, visual angle, PPD) and helpers to compute a **target source size**.
- `imgshrink/more_metrics.py` – lightweight content metrics: colorfulness, edge density, Otsu separability, noise proxy, JPEG quant summary, simple content classifier (line-art vs photo).
- `imgshrink/perceptual.py` – SSIM on luminance and a **binary search** to find the smallest quality that meets a perceptual threshold vs a reference at **display scale**.

## Wiring guide (minimal diffs)

1. **Collect extra metrics** during `analyze_images`:

    ```python
    from imgshrink.more_metrics import quick_content_metrics
    # ...
    with Image.open(path) as im:
        q = quick_quality_tuple(im)             # existing (entropy_bits, lap_var)
        extra = quick_content_metrics(im, file_bytes=path.stat().st_size)
        info.extra = extra   # attach to your Info dataclass as a Dict[str, float]
    ```

    Extend your per-folder Stats aggregation to compute min/avg/max for:
    `megapixels, file_bpp, bytes_per_mp, colorfulness, edge_density, otsu_sep, noise_proxy, jpeg_q_est, is_grayscale`.

2. **Compute device PPD & target source size** when deciding a plan:

    ```python
    from imgshrink.display import DeviceProfile, target_source_size_from_ppd

    # Example device profile (supply via CLI flags):
    prof = DeviceProfile(diagonal_in=6.7, width_px=2400, height_px=1080, viewing_distance_cm=35)

    # Pick PPD targets based on content type (line art needs more):
    ppd_photo = 60.0
    ppd_line  = 75.0

    # For each image (or use folder medians):
    src_wh = (info.width, info.height)
    content = "lineart" if info.extra.get("is_grayscale", 0) > 0.5 and info.extra["edge_density"] >= 0.06 else "photo"
    want_ppd = ppd_line if content == "lineart" else ppd_photo

    tgt_w, tgt_h, ratio = target_source_size_from_ppd(src_wh, prof, fit_mode="fit-longer", ppd_target=want_ppd, safety_scale=1.0)
    # Use the MIN ratio across the folder as your plan.downsample_ratio
    ```

3. **Perceptual guardrail during encoding** (optional but recommended):

    - Build the **reference** as the downscaled original at the *final on-screen size* (what users will actually see).
    - Search the lowest acceptable quality with `binary_search_quality` at that display scale.

    ```python
    from imgshrink.perceptual import binary_search_quality, PerceptualThresholds

    ref = original_image.resize((disp_w, disp_h), resample=Image.LANCZOS)
    dec, bytes_used, q, ssim_val = binary_search_quality(ref, fmt="WEBP", q_lo=45, q_hi=90, thresholds=PerceptualThresholds(ssim_min=0.990))
    # Use `q` for the real encode at the (possibly larger) target source size.
    ```

## Policy (deterministic, explainable)

1. **Classify** each page as `lineart` or `photo` via the lightweight metrics.
2. **Pick PPD** target: `~75` for line art, `~60` for photo.
3. **Compute ratio** via `target_source_size_from_ppd` and update `plan.downsample_ratio` (use folder median or p25 for safety).
4. **Codec choice**: palette-PNG/WebP-lossless for line art; WebP/JPEG (mozjpeg) for photo; keep **4:4:4** chroma for line art.
5. **Perceptual check** at display scale with SSIM≥0.990 (line art) / 0.985 (photo).

## CLI additions (suggested)

- `--display-diagonal, -D` (inches)
- `--display-res, -R` (e.g., `2400x1080`)
- `--viewing-distance, -V` (cm)
- `--ppd-photo, -P` (default 60)
- `--ppd-line, -L` (default 75)
- `--perceptual-guard, -G` (SSIM min; default 0.990 for line art, 0.985 for photo)

These flags simply populate a `DeviceProfile` and toggle the perceptual binary search during compression.

## Testing ideas

- Synthetic pages: pure grayscale line art (thin strokes), halftone screens, noisy scans, colorful covers.
- Assert monotonicity: higher PPD target → never smaller target size.
- SSIM sanity: identical → SSIM≈1; blurred → SSIM drops below threshold.

---

This path keeps the existing public surface intact while enabling “compress to the edge of visibility” using **PPD-limited downsampling + a perceptual guardrail**.
