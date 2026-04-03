# Resumable Downloads (.part File Feature)

## Overview

The `.part` file feature enables resumable downloads for aebndl, similar to yt-dlp's partial download functionality. Downloads can now be interrupted (via Ctrl+C, crashes, or network issues) and seamlessly resumed from where they left off.

## Key Features

### 1. Automatic Progress Tracking
- Creates `.part` files alongside output files during downloads
- Tracks all downloaded segments for both audio and video streams
- Stores byte counts and total sizes for progress estimation
- Saves metadata including URL, resolution, scene number, etc.

### 2. Resume Capability
- Automatically detects existing `.part` files on startup
- Validates URL and configuration match before resuming
- Skips already-downloaded segments
- Updates progress bars to reflect resumed state

### 3. Graceful Interruption Handling
- **Ctrl+C**: Saves progress and exits cleanly
- **Unexpected errors**: Triggers automatic progress save
- **Periodic saves**: Updates `.part` file every 10 seconds during download

### 4. Automatic Cleanup
- `.part` files are automatically removed on successful completion
- Failed downloads preserve `.part` files for later resumption

### 5. CLI Control
- New `--no-part` flag to disable feature if needed
- Enabled by default for seamless operation

## Implementation Details

### File Location
`.part` files are **always** created in the output directory (not the work directory):
```python
# For output: /path/to/output/Movie Name 1080p.mp4
# Part file:  /path/to/output/Movie Name 1080p.mp4.part
```

### File Format
`.part` files use JSON format with the following structure:
```json
{
    "url": "https://straight.aebn.com/straight/movies/123456/movie-name",
    "movie_id": "123456",
    "target_height": 1080,
    "scene_n": null,
    "target_stream": null,
    "streams": {
        "a": {
            "stream_id": "audio_stream_id",
            "downloaded_segments": [
                "/path/to/work/123456/a_audio_stream_id_0.mp4",
                "/path/to/work/123456/a_audio_stream_id_1.mp4"
            ],
            "downloaded_bytes": 2048000,
            "total_size": 10240000
        },
        "v": {
            "stream_id": "video_stream_id",
            "downloaded_segments": [
                "/path/to/work/123456/v_video_stream_id_0.mp4"
            ],
            "downloaded_bytes": 5120000,
            "total_size": 51200000
        }
    },
    "timestamp": "2025-01-07T12:34:56.789"
}
```

### Resume Validation
The system performs strict validation before resuming:

1. **URL Match**: `.part` file URL must exactly match current download URL
2. **Stream ID Validation**: Checks that stream IDs match between saved state and current manifest
3. **Segment Existence**: Filters out segments that no longer exist on disk
4. **Configuration Match**: Resolution, scene number, and stream type are preserved

### Integration with ytaedl and procparsers

The `.part` file feature integrates seamlessly with the existing ecosystem:

- **ytaedl**: Calls aebndl with `--json` flag; `.part` files work transparently
- **procparsers**: Parses JSON events including `destination` and `progress` events
- **JSON Output**: All `.part` file operations are invisible to ytaedl's event stream

## Usage

### Basic Usage
```bash
# Start download
aebndl https://straight.aebn.com/straight/movies/123456/movie-name -o ./output

# Interrupt with Ctrl+C
^C
# Progress saved to: ./output/Studio - Movie Name 1080p.mp4.part

# Resume download (automatically detected)
aebndl https://straight.aebn.com/straight/movies/123456/movie-name -o ./output
# INFO: Found existing .part file, resuming download
```

### Disable .part Files
```bash
aebndl <url> --no-part
```

### With Different Resolutions
Different resolutions create different output files (and thus different `.part` files):
```bash
# Download 720p
aebndl <url> -r 720  # Creates: Movie 720p.mp4.part

# Download 1080p (different part file)
aebndl <url> -r 1080  # Creates: Movie 1080p.mp4.part
```

## Testing

### Test Coverage
The feature includes comprehensive test coverage:

- **Unit Tests** (tests/test_part_file.py): 11 tests
  - `.part` file creation and structure
  - Loading and validation logic
  - URL matching and mismatching
  - Invalid JSON handling
  - Missing field validation
  - Segment restoration
  - Cleanup on success
  - `--no-part` flag behavior

- **Integration Tests** (tests/test_part_integration.py): 3 tests
  - Segment skip on resume
  - ytaedl format compatibility
  - Different resolution handling

### Running Tests
```bash
# Run all aebndl tests
pytest tests/ -v

# Run only .part file tests
pytest tests/test_part_file.py tests/test_part_integration.py -v

# Run ytaedl tests (integration check)
cd ytaedl && pytest tests/ -v

# Run procparsers tests (integration check)
cd procparsers && pytest tests/ -v
```

### Test Results
```
tests/ - 15 passed, 1 skipped
ytaedl/tests/ - 73 passed, 1 skipped
procparsers/tests/ - 21 passed
```

## Code Changes

### Modified Files

1. **aebn_dl/downloader.py**:
   - Added `.part` file management methods
   - Integrated resume logic into `run()` method
   - Added periodic saving during downloads
   - Added graceful interrupt handling
   - Lines: 1-20 (imports), 115-242 (part file methods), 209-248 (run method)

2. **aebn_dl/cli.py**:
   - Added `--no-part` CLI argument
   - Line 104, 32

3. **tests/base_test.py**:
   - Fixed proxy availability check to skip gracefully

4. **tests/test_part_file.py**:
   - Comprehensive unit tests for `.part` functionality

5. **tests/test_part_integration.py**:
   - Integration tests for resume behavior

## Behavior Details

### Segment Download Logic
When downloading a segment:
1. Check if segment file exists on disk
2. If exists and not in `overwrite_existing_files` mode:
   - Add to `downloaded_segments` list (if not already present)
   - Update byte count from file size
   - Skip download
3. If doesn't exist:
   - Download from server
   - Save to disk
   - Update progress

### Periodic Saving
During download, the `.part` file is saved:
- Every 10 seconds (configurable via `part_save_interval`)
- On Ctrl+C interrupt
- On any exception
- Uses `force=True` to ensure save even when download is ongoing

### Exit Handler
An `atexit` handler ensures `.part` file is saved even on unexpected termination:
```python
if not self.no_part:
    atexit.register(self._save_part_file_on_exit)
```

## Limitations and Considerations

1. **Work Directory Changes**: If work directory changes between runs, segment paths in `.part` file may become invalid (filtered out on restore)

2. **Stream ID Changes**: If the server provides different stream IDs on subsequent requests, resume may not work (validation fails)

3. **No Cross-Version Compatibility**: `.part` file format is versioned by implementation, not explicitly

4. **Disk Space**: `.part` files are small (typically <10KB) but persist until download completes

5. **Manual Cleanup**: If output directory is moved, `.part` files may be orphaned

## Future Enhancements

Potential improvements for future versions:

1. **Explicit Version Field**: Add version number to `.part` file format
2. **Checksum Validation**: Verify segment integrity before skipping
3. **Bandwidth Estimation**: Use `.part` data to estimate completion time on resume
4. **Progress Persistence**: Save more granular progress (e.g., partial segment downloads)
5. **Cross-Machine Resume**: Support resuming on different machines (path normalization)

## Compatibility

- **Python**: 3.10+
- **Dependencies**: No new dependencies added
- **Backward Compatible**: Existing code continues to work without `.part` files
- **ytaedl Integration**: Fully compatible with ytaedl's subprocess-based invocation
- **procparsers**: JSON events are unaffected by `.part` file operations

## Summary

The `.part` file feature provides robust resumable downloads for aebndl with:
- ✅ Automatic progress tracking
- ✅ Graceful interrupt handling
- ✅ URL and configuration validation
- ✅ Comprehensive test coverage
- ✅ Full ytaedl/procparsers integration
- ✅ Zero breaking changes
- ✅ Optional disable flag

Downloads can now be safely interrupted and resumed, making aebndl more resilient to network issues, system crashes, and user interruptions.
