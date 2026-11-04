from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from .errors import JobError

T = TypeVar("T")


class JobQueue:
    """In-memory admission + FIFO semaphore; reserve before downloading any source."""

    def __init__(self, concurrency: int, queue_size: int, wait_timeout: float):
        self._slots = asyncio.Semaphore(concurrency)
        self._capacity = concurrency + queue_size
        self._wait_timeout = wait_timeout
        self._users: set[int] = set()
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    async def run(self, user_id: int, operation: Callable[[], Awaitable[T]]) -> T:
        # No await between the admission checks and reservation (single event loop).
        if self._closed:
            raise JobError("stopping")
        if user_id in self._users:
            raise JobError("duplicate")
        if len(self._users) >= self._capacity:
            raise JobError("queue_full")
        self._users.add(user_id)
        task = asyncio.current_task()
        self._tasks.add(task)
        acquired = False
        try:
            try:
                async with asyncio.timeout(self._wait_timeout):
                    await self._slots.acquire()
                    acquired = True
            except TimeoutError:
                raise JobError("queue_timeout") from None
            return await operation()
        finally:
            if acquired:
                self._slots.release()
            self._users.discard(user_id)
            self._tasks.discard(task)

    async def close(self) -> None:
        self._closed = True
        tasks = self._tasks - {asyncio.current_task()}
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
