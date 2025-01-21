import asyncio
import re
from typing import Optional, Dict, Any
import parallel_runner  # Import the module directly
import random
import time
import os

def example_parser(stdout: str, stderr: str) -> Optional[Dict[str, Any]]:
    match = re.search(r"Instance: (.+), Progress: (\d+)/(\d+), Speed: (.+)", stdout)
    if match:
        try:
            instance_name = match.group(1)
            current = int(match.group(2))
            total = int(match.group(3))
            speed = match.group(4)
            return {"current": current, "total": total, "speed": speed}
        except ValueError:
            import logging
            logging.warning(f"Could not parse progress from stdout: {stdout}")
    return None

def example_aggregator(parsed_outputs: Dict[int, Any]) -> Optional[Dict[str, Any]]:
    total_speed = 0
    active_tasks = 0
    for output in parsed_outputs.values():
        if output and 'speed' in output:
            try:
                speed_value = float(output['speed'].split()[0])
                total_speed += speed_value
                active_tasks += 1
            except (ValueError, IndexError):
                pass
    if active_tasks > 0:
        return {"overall_speed": f"{total_speed:.1f} MB/s"}
    else:
        return {"overall_speed": "N/A"}

async def main():
    command_template = ["python", "simulate_progress.py"]
    instance_args = [["Task1", "10"], ["Task2", "20"], ["Task3", "30"]] # Pass desired duration

    runner = parallel_runner.ParallelRunner(  # Access the class through the module
        command_template=command_template,
        instance_args=instance_args,
        parser_func=example_parser,
        aggregate_func=example_aggregator,
        restart_on_failure=True,
        log_output=True,
        allow_pause_resume=True,
    )
    results = await runner.run()
    print("\nResults:", results)

if __name__ == "__main__":
    asyncio.run(main())
