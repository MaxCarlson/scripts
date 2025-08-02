#!/usr/bin/env python3
"""
banghist_reminder.py

Uses the HistoryWatcher module to remind the user of banghist
operations they could use.
"""
from pathlib import Path
from history_watcher import HistoryWatcher

# Configuration
HISTORY_PATH = Path.home() / ".zsh_history"
POLL_INTERVAL = 1.0
MAX_HISTORY_BUFFER = 10

# Instantiate watcher and register rules at import time
watcher = HistoryWatcher(
    history_file=HISTORY_PATH,
    interval=POLL_INTERVAL,
    max_buffer=MAX_HISTORY_BUFFER
)

@watcher.rule("Use `!!` for exact repeats")
def suggest_bangbang(cmd, buf, suggested_set):
    if len(buf) >= 1 and buf[0] == cmd and len(cmd.split()) > 1:
        key = ("!!", cmd)
        if key not in suggested_set:
            suggested_set.add(key)
            return f"You just ran `{cmd}` twice. Try:  !!"

@watcher.rule("Use `!$` for reusing the last argument")
def suggest_bang_dollar(cmd, buf, suggested_set):
    if len(buf) >= 1:
        prev = buf[0]
        last_arg = prev.split()[-1]
        if cmd != prev and cmd.endswith(last_arg):
            key = ("!$", cmd)
            if key not in suggested_set:
                suggested_set.add(key)
                return f"You reused `{last_arg}`. Try:  !$"

@watcher.rule("Use `!-n` for recent repeats")
def suggest_negative_index(cmd, buf, suggested_set):
    for idx in range(1, min(len(buf), MAX_HISTORY_BUFFER)):
        if buf[idx] == cmd:
            n = idx + 1
            key = (f"!-{n}", cmd)
            if key not in suggested_set:
                suggested_set.add(key)
                return f"You ran `{cmd}` {n} commands ago. Try:  !-{n}"
            break

def main():
    if not HISTORY_PATH.is_file():
        print(f"[Error] history file not found: {HISTORY_PATH}")
    else:
        watcher.start()

if __name__ == "__main__":
    main()
