# Parallel Runner - Concurrent Process Execution and Monitoring

`parallel_runner` is a Python module designed to efficiently execute and monitor multiple subprocesses concurrently. It leverages `asyncio` for asynchronous operations and `rich` for creating an interactive and visually informative terminal user interface, complete with real-time progress updates and aggregated statistics.

## Features

*   **Concurrent Execution**: Run multiple commands or scripts in parallel as separate subprocesses.
*   **Real-time Progress Monitoring**: Displays individual progress bars for each running instance and an overall progress bar.
*   **Customizable Output Parsing**: Define a `parser_func` to extract relevant data (e.g., progress, speed) from the stdout/stderr of each subprocess.
*   **Aggregated Statistics**: Provide an `aggregate_func` to combine parsed data from all instances into a single, overall status displayed on the main progress bar.
*   **Failure Handling**: Configurable options for restarting failed processes up to a maximum number of retries.
*   **Output Logging**: Option to log the stdout and stderr of each subprocess to separate files.
*   **Interactive Control**: Optional pause and resume functionality for all running tasks.
*   **Rich UI**: Utilizes the `rich` library for a dynamic and aesthetically pleasing terminal interface.

## Core Components

*   **`ParallelRunner` Class**: The main class that orchestrates the parallel execution. It takes a command template, arguments for each instance, and custom parsing/aggregation functions.

    ```python
    # Basic Initialization
    runner = ParallelRunner(
        command_template=["python", "your_script.py"],
        instance_args=[["arg1"], ["arg2"]], # Arguments for each instance
        parser_func=your_parser_function,
        aggregate_func=your_aggregator_function,
        # ... other options
    )
    results = await runner.run()
    ```

*   **`parser_func` (Callable)**: A function that takes `stdout` and `stderr` strings from a subprocess and returns a dictionary of parsed data. This data is then used to update individual progress bars and is fed into the `aggregate_func`.

*   **`aggregate_func` (Callable)**: A function that takes a dictionary of parsed outputs from all active instances and returns a dictionary of aggregated statistics. This is used to update the overall progress bar's description and fields.

## Example Usage

The `example_parallel_runner.py` script demonstrates how to use the `ParallelRunner` with a simulated progress script (`simulate_progress.py`).

To run the example:

```bash
python -m parallel_runner.example_parallel_runner
```

This example showcases:

*   Defining a `parser_func` to extract progress and speed information.
*   Defining an `aggregate_func` to calculate overall speed.
*   Running multiple instances of `simulate_progress.py` concurrently.
*   Displaying real-time progress and aggregated speed in the terminal.

## Installation

(Assuming Python 3 and `pip` are installed)

```bash
# Navigate to the module directory
cd /data/data/com.termux/files/home/scripts/modules/parallel_runner

# Install required libraries (rich, asyncio is built-in)
pip install rich
```
