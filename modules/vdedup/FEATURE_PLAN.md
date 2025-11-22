# vdedup Feature Requests & Improvements

## High Priority

### 1. Fix Duplicate Count Display Issue
**Status**: TODO
**Priority**: HIGH
**Description**: Duplicates Found shows 0 during early stages (Q1-Q2) even when duplicates exist, then suddenly shows correct count (892+) in later stages (Q3-Q4).

**Root Cause**: The `duplicates_found` counter is only updated when groups are reported via `report_groups()`, which happens at the end of each stage. Early stages don't report intermediate duplicate counts.

**Solution**:
- Update `duplicates_found` incrementally as groups are discovered within each stage
- Q1 (size bucketing): Report size-duplicate count immediately
- Q2 (hashing): Report hash-duplicate count as files are hashed
- Display running total across all stages

**Files to modify**:
- `progress.py`: Add method to update duplicates incrementally
- `pipeline.py`: Call duplicate update method during Q1/Q2 processing
- Ensure UI updates every ~100 files to show progress

---

### 2. Fix "Recent Activity" Box Always Empty
**Status**: TODO
**Priority**: HIGH
**Description**: The Recent Activity panel never shows log entries despite log messages being generated.

**Root Cause**: The `add_log()` method exists but is never called from pipeline stages. Only status updates are made, not log entries.

**Solution**:
- Add `reporter.add_log()` calls at key points in pipeline:
  - Stage start/completion
  - Every N files processed (configurable, default 500)
  - When duplicates are found
  - Cache hits/misses
  - Errors/warnings
- Ensure Recent Activity shows last 12 log entries with timestamps
- Format: `[HH:MM:SS] LEVEL: message`

**Files to modify**:
- `pipeline.py`: Add log calls throughout processing
- `video_dedupe.py`: Add log calls for major events
- `progress.py`: Ensure `_render_footer()` displays logs properly

---

### 3. Improve Cache File Format (Binary Representation)
**Status**: TODO
**Priority**: MEDIUM
**Description**: Current cache uses JSONL format which is human-readable but inefficient for storage and I/O.

**Current Issues**:
- Large file sizes (JSON overhead)
- Slow parsing for large caches
- No built-in integrity checking

**Proposed Solution**:
- Use MessagePack or similar binary format for cache entries
- Maintain JSONL as legacy/fallback format
- Add format version header to cache file
- Implement automatic migration from JSONL to binary on first load

**Benefits**:
- ~50-70% smaller cache files
- Faster load/save times
- Better compression potential
- Built-in schema validation

**Files to modify**:
- `cache.py`: Add BinaryHashCache class
- Support both formats during transition period
- Add migration utility

**Implementation Steps**:
1. Create new `BinaryHashCache` class using MessagePack
2. Add format detection (check first bytes for magic header)
3. Auto-migrate JSONL → Binary on load
4. Keep JSONL export option for debugging

---

### 4. Add Audio Hashing to Partial Hash Stage
**Status**: TODO
**Priority**: MEDIUM
**Description**: Currently only video content is hashed in Q2 partial stage. Audio track hashing would improve duplicate detection for videos with same visual content but different audio.

**Use Cases**:
- Videos re-encoded with different audio tracks
- Dubbed versions
- Videos with commentary added
- Music videos with different mixes

**Proposed Implementation**:
- Extract audio fingerprint during Q2 partial hash
- Use chromaprint/acoustid for audio fingerprinting
- Store audio hash alongside video hash in cache
- Add optional audio similarity comparison in Q6 stage

**Files to modify**:
- `hashers.py`: Add audio extraction and hashing
- `cache.py`: Add `audio_hash` field to schema
- `pipeline.py`: Integrate audio hashing into Q2 stage
- Add `--audio-hash` flag to enable/disable

**Dependencies**:
- `chromaprint` library for audio fingerprinting
- `ffmpeg` for audio extraction (already required)

---

### 5. Ensure Cache Crash Recovery & Incremental Progress
**Status**: TODO
**Priority**: HIGH
**Description**: If the program crashes or is interrupted, cache should remain valid and allow resuming from last successful point.

**Current Issues**:
- JSONL append-only is good, but no fsync after writes
- No validation on cache load
- Partial entries from crashes might corrupt cache
- No way to verify cache integrity

**Proposed Solution**:
1. **Atomic Writes**:
   - Write to `.cache.tmp` first
   - Flush and fsync after each entry
   - Rename to `.cache` on clean shutdown
   - On startup, check for `.cache.tmp` and recover

2. **Entry Validation**:
   - Add CRC32/SHA256 checksum to each cache entry
   - Validate checksums on load
   - Skip/warn on corrupted entries
   - Auto-repair by removing bad entries

3. **Progress Markers**:
   - Write stage progress markers to cache
   - On resume, skip files already in cache for current stage
   - Allow `--resume` flag to continue interrupted scans

4. **Graceful Shutdown**:
   - Catch SIGINT/SIGTERM properly (already done)
   - Ensure cache flush before exit
   - Write shutdown marker to cache

**Files to modify**:
- `cache.py`: Add checksums, atomic writes, validation
- `video_dedupe.py`: Add `--resume` flag
- `pipeline.py`: Check cache for existing results before processing

**Implementation Priority**:
- Phase 1: Add fsync and basic validation (HIGH)
- Phase 2: Add checksums and auto-repair (MEDIUM)
- Phase 3: Add `--resume` functionality (MEDIUM)

---

## Medium Priority

### 6. Stage-Specific Stats Pages (Keyboard Navigation)
**Status**: TODO
**Priority**: MEDIUM
**Description**: Press 1-7 keys to view detailed stats for specific pipeline stages instead of just summary view.

**Proposed UI**:
- Default view (0 or no key): Overall pipeline stats
- Press 1: Stage 1 (Q1 Size Bucketing) detailed stats
- Press 2: Stage 2 (Q2 Partial Hash) detailed stats
- Press 3: Stage 3 (Q2 SHA256) detailed stats
- ...and so on

**Per-Stage Stats Should Show**:
- Files processed vs total for that stage
- Throughput (MB/s or files/s)
- Cache hit rate for that stage
- Groups found in that stage
- Stage-specific metrics (e.g., collision rate for Q2)
- Timeline of processing (heatmap/histogram)

**Files to modify**:
- `progress.py`: Add keyboard input handling
- `progress.py`: Create per-stage stat tracking
- `progress.py`: Add separate render methods for each stage detail view

---

### 7. Fix Progress Bar Color Tags
**Status**: TODO
**Priority**: LOW
**Description**: Progress bar shows `[green]████[/green][grey30]░░░░` instead of applying the colors.

**Root Cause**: Rich markup tags are being rendered as literal text instead of being parsed.

**Solution**:
- Ensure progress bar text uses `Text.from_markup()` or similar
- Or use Rich's `BarColumn` for proper color rendering
- Check `console.print()` vs `console.log()` usage

**Files to modify**:
- `progress.py`: Fix progress bar rendering in `_render_header()`

---

## Feature Request Categories

### Performance Enhancements
- [ ] Binary cache format (#3)
- [ ] Incremental resume capability (#5)
- [ ] Parallel audio fingerprinting (#4)

### User Experience
- [ ] Real-time duplicate counter (#1)
- [ ] Recent Activity logs (#2)
- [ ] Stage-specific stats views (#6)
- [ ] Color-coded progress bars (#7)

### Robustness
- [ ] Crash recovery (#5)
- [ ] Cache validation & repair (#5)
- [ ] Atomic cache writes (#5)

---

## Implementation Order (Recommended)

1. **Fix Recent Activity logs** - Quick win, improves UX immediately
2. **Fix duplicate counter display** - Makes progress visible, builds confidence
3. **Add fsync and basic cache validation** - Critical for data integrity
4. **Audio hashing feature** - Enhances detection capabilities
5. **Binary cache format** - Performance improvement, requires migration plan
6. **Stage-specific stats pages** - Nice-to-have enhancement
7. **Full crash recovery with --resume** - Complex but valuable

---

## Notes

- All cache format changes should maintain backward compatibility
- Add comprehensive tests for cache validation and recovery
- Document all new CLI flags in help text and examples
- Consider adding `--cache-check` utility command to validate/repair cache
