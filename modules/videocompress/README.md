# videocompress 0.1.0

Estimation-first media-aware video compression, analysis, and preservation backend for `scripts`.

## Key Capabilities

- **Strict Mode Discipline**: `inventory`, `plan`, and metadata `estimate` **never** encode video.
- **Media Preservation**: Preserves all audio, subtitle, chapter, attachment, and metadata streams by default.
- **Estimation-First**: Predicts compression feasibility and potential savings before committing hours of compute.
- **Hardware-Aware**: Integrates with local FFmpeg and NVIDIA NVENC (RTX 5090 Blackwell) hardware encoding.
- **Crash-Safe & Journaled**: Atomic, journaled staging and publication with robust non-clobber guarantees.

## CLI Usage

```powershell
# Standalone entry point
vcompress --help
vcompress capabilities
vcompress inventory -i <directory-or-file> -I <workspace> -B 4M -R 1920x1080
vcompress plan -i <directory-or-file> -I <workspace> -B 4M -R 1920x1080
vcompress estimate -i <directory-or-file> -I <workspace> -r <plan-id> -E metadata
vcompress preview -i <directory-or-file> -I <workspace> -r <plan-id> -n 3
vcompress apply -i <directory-or-file> -I <workspace> -r <plan-id>
```
