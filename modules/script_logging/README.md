# script_logging

Reusable event and run history for Python modules in this repository. The package uses the Python standard library and does not configure the root logger on import.

`HistoryStore` persists generic events and runs in SQLite. Records have stable IDs, entity references, timestamps, outcomes, optional stdout/stderr, and JSON metadata. `prune_output` expires large output while retaining compact run facts for statistics.

`EventFormatter` chooses the text fields and order. Supported fields are `date`, `time`, `level`, `type`, `source`, `name`, and `message`. Date/time formats, separator, and ANSI level colors are independent settings; pass `color_map={"ERROR": "\x1b[35m"}` to choose your own color. `text_file_handler` always writes plain text.

```python
import logging
from pathlib import Path
from script_logging import EventFormatter, HistoryStore, StoreHandler

store = HistoryStore(Path("history.sqlite3"))
logger = logging.getLogger("my_module")
logger.addHandler(StoreHandler(store, source="my_module"))
console = logging.StreamHandler()
console.setFormatter(EventFormatter(fields=("time", "type", "message"), colors=True))
logger.addHandler(console)
logger.info("Job started", extra={"event_type": "JOB_START"})
```

Applications own their event names, entity IDs, schedules, and statistics. Call `store.clear(source="my_module")` to remove only that application's history.
