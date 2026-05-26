<!-- version: 0.1.0 -->
# procparsers

Parsers for subprocess output streams, currently including `yt-dlp` and `aebn-dl` event parsing for downloader managers.

## Usage

This is a Python library module. Import its stream parsers from consuming downloader or monitoring code.

```python
from procparsers import iter_parsed_events, parse_ytdlp_line
```
