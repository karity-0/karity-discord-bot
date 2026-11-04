import asyncio
import unittest

from karity_bot.errors import JobError
from karity_bot.jobs import JobQueue


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_capacity_duplicate_and_fifo(self):
        queue = JobQueue(1, 1, 5)
        entered = asyncio.Event()
        release = asyncio.Event()
        order = []
        async def first():
            order.append(1)
            entered.set()
            await release.wait()
            return 1
        async def second():
            order.append(2)
            return 2
        a = asyncio.create_task(queue.run(1, first))
        await entered.wait()
        b = asyncio.create_task(queue.run(2, second))
        await asyncio.sleep(0)
        for user, code in [(1, "duplicate"), (3, "queue_full")]:
            with self.assertRaises(JobError) as error:
                await queue.run(user, second)
            self.assertEqual(error.exception.code, code)
        self.assertEqual(order, [1])
        release.set()
        self.assertEqual(await asyncio.gather(a, b), [1, 2])
        self.assertEqual(order, [1, 2])
        self.assertEqual(await queue.run(1, second), 2)

    async def test_wait_timeout_releases_user_reservation(self):
        queue = JobQueue(1, 1, 0.03)
        entered = asyncio.Event()
        release = asyncio.Event()
        async def blocked():
            entered.set()
            await release.wait()
        task = asyncio.create_task(queue.run(1, blocked))
        await entered.wait()
        with self.assertRaises(JobError) as error:
            await queue.run(2, blocked)
        self.assertEqual(error.exception.code, "queue_timeout")
        release.set()
        await task
        await queue.run(2, blocked)

    async def test_concurrency_is_bounded(self):
        queue = JobQueue(2, 10, 5)
        running = peak = 0
        async def work():
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1
        await asyncio.gather(*(queue.run(user, work) for user in range(10)))
        self.assertEqual(peak, 2)

    async def test_errors_cancellation_and_shutdown_release_slots(self):
        queue = JobQueue(1, 1, 5)
        async def broken():
            raise JobError("build_failed")
        with self.assertRaises(JobError):
            await queue.run(1, broken)
        entered = asyncio.Event()
        async def blocked():
            entered.set()
            await asyncio.Event().wait()
        a = asyncio.create_task(queue.run(1, blocked))
        await entered.wait()
        b = asyncio.create_task(queue.run(2, blocked))
        await asyncio.sleep(0)
        await queue.close()
        self.assertTrue(a.cancelled())
        self.assertTrue(b.cancelled())
        with self.assertRaises(JobError) as error:
            await queue.run(3, broken)
        self.assertEqual(error.exception.code, "stopping")
