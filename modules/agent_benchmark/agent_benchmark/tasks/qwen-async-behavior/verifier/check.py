import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path


async def check(module):
    if await module.run_bounded([], lambda value: value, 1) != []:
        raise AssertionError("empty input must return an empty list")
    try:
        await module.run_bounded([1], lambda value: value, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("zero concurrency must raise ValueError")

    active = 0
    peak = 0

    async def worker(value):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01 * (5 - value))
        active -= 1
        return value * 10

    result = await module.run_bounded([1, 2, 3, 4], worker, 2)
    if result != [10, 20, 30, 40] or peak != 2:
        raise AssertionError("work must be bounded and results must preserve input order")

    started = asyncio.Event()
    cleaned = 0

    async def waiting_worker(_value):
        nonlocal cleaned
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned += 1

    pending = asyncio.create_task(module.run_bounded([1, 2, 3], waiting_worker, 2))
    await asyncio.wait_for(started.wait(), timeout=1)
    await asyncio.sleep(0)
    pending.cancel()
    try:
        await pending
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("cancellation must propagate")
    if cleaned != 2:
        raise AssertionError("cancellation must reach active workers")

    async def failing_worker(_value):
        raise LookupError("worker failure")

    try:
        await module.run_bounded([1], failing_worker, 1)
    except LookupError:
        pass
    else:
        raise AssertionError("worker errors must propagate")
    return 6


def main():
    path = Path(sys.argv[1]) / "src/async_jobs.py"
    spec = importlib.util.spec_from_file_location("candidate_async_jobs", path)
    if spec is None or spec.loader is None:
        raise SystemExit(1)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checks = asyncio.run(check(module))
    receipt = os.environ.get("AGENT_BENCH_COMPLETION_PATH")
    if receipt:
        Path(receipt).write_text(json.dumps({"nonce": os.environ["AGENT_BENCH_VERIFICATION_NONCE"],
                                            "status": "passed", "checks_completed": checks}), encoding="utf-8")
    print("PASS: bounded async work, ordering, errors, and cancellation")


if __name__ == "__main__":
    main()
