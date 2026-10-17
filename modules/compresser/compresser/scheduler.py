"""Bounded per-job memory reservations with finite FIFO-head bypass."""

from typing import Generic, Sequence, TypeVar

Job = TypeVar("Job")


class MemoryScheduler(Generic[Job]):
    def __init__(self, jobs: Sequence[tuple[Job, int]], budget: int, slots: int):
        if budget <= 0 or slots < 0 or (jobs and slots == 0) or any(not 0 < cost <= budget for _, cost in jobs):
            raise ValueError("Invalid memory reservation budget, worker slots or job cost")
        self.pending = list(jobs)
        self.budget = budget
        self.slots = slots
        self.reserved_bytes = 0
        self.peak_reserved_bytes = 0
        self._head = None
        self._bypasses = 0

    def next_job(self) -> tuple[Job, int] | None:
        if not self.pending:
            return None
        head = id(self.pending[0][0])
        if head != self._head:
            self._head, self._bypasses = head, 0
        available = self.budget - self.reserved_bytes
        index = 0
        if self.pending[0][1] > available:
            if self._bypasses >= self.slots:
                return None
            index = next((index for index, (_, cost) in enumerate(self.pending) if cost <= available), None)
            if index is None:
                return None
            self._bypasses += 1
        job, cost = self.pending.pop(index)
        self.reserved_bytes += cost
        self.peak_reserved_bytes = max(self.peak_reserved_bytes, self.reserved_bytes)
        return job, cost

    def release(self, cost: int) -> None:
        self.reserved_bytes -= cost
        if self.reserved_bytes < 0:
            raise RuntimeError("Memory reservation accounting underflow")
