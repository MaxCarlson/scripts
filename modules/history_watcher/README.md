# History Watcher

`history_watcher` is a Python module designed to monitor a Zsh history file in real-time, applying custom, pluggable rules to new commands as they are executed. It provides a framework for creating interactive reminders or suggestions based on command-line usage patterns.

## Features

*   **Real-time Monitoring**: Continuously tails a specified Zsh history file.
*   **Pluggable Rule System**: Easily define and register custom rules to analyze new commands.
*   **Contextual Suggestions**: Rules can access a buffer of recent commands to provide context-aware suggestions.
*   **Throttle Mechanism**: Prevents repetitive suggestions for the same rule and command combination.
*   **History File Robustness**: Handles history file rotation and truncation gracefully.
*   **Rich Output**: Utilizes the `rich` library for visually appealing console output.

## Core Components

*   **`HistoryWatcher`**: The central class that orchestrates the monitoring process. It manages the registration of rules, reads new commands from the history file using `HistoryTailer`, and applies the defined rules.

    ```python
    # Example of rule registration
    from history_watcher import HistoryWatcher
    watcher = HistoryWatcher(history_file="/path/to/.zsh_history")

    @watcher.rule("My Custom Rule")
    def my_rule(cmd, buffer, suggested_set):
        # Implement your logic here
        if "something" in cmd:
            return "Consider doing something else!"
    ```

*   **`HistoryTailer`**: A utility class responsible for efficiently reading new lines from the history file. It intelligently handles file descriptor management and inode changes to adapt to history file rotations or truncations.

*   **`parse_zsh_history_line`**: A helper function to extract the actual command string from a raw Zsh history line, which typically includes a timestamp and duration.

## Example Usage: `banghist_reminder.py`

The `actors/banghist_reminder.py` script serves as a practical example of how to use the `history_watcher` module. It implements several rules to suggest common Zsh bang history expansions to the user, such as:

*   **`!!`**: For repeating the exact previous command.
*   **`!$`**: For reusing the last argument of the previous command.
*   **`!-n`**: For repeating a command from `n` commands ago.

To run the `banghist_reminder` example:

```bash
python -m history_watcher.actors.banghist_reminder
```

This will start the watcher, and as you type commands in your Zsh terminal, it will provide suggestions in a separate terminal where the script is running.
