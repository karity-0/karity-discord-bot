import asyncio
from dataclasses import replace
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from karity_bot.config import Settings
from karity_bot.engine import Engine
from karity_bot.errors import JobError

ROOT = Path(__file__).resolve().parents[1]


def process_running(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259)
        finally:
            kernel.CloseHandle(handle)
    state = Path(f"/proc/{pid}/stat")
    if state.exists() and state.read_text().split()[2] == "Z":
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class ResourceLimitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.settings = Settings(jobs_path=self.folder / "jobs", memory_mb=128, job_timeout=3)
        self.worker = self.folder / "fake_worker.py"
        self.prefix = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"

    async def asyncTearDown(self):
        if self.settings.jobs_path.exists():
            self.assertEqual(list(self.settings.jobs_path.iterdir()), [])
        self.temp.cleanup()

    async def test_memory_limit_rejects_large_allocation(self):
        # Trusted Python fixture, not submitted Lua. This tests the real OS limit.
        code = self.prefix + """
from karity_bot.limits import apply_limits
apply_limits(128, 10, 1048576)
try:
    allocation = bytearray(256 * 1024 * 1024)
except MemoryError:
    print('limited')
else:
    raise SystemExit(1)
"""
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", code, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        self.assertEqual(process.returncode, 0, stderr.decode(errors="replace"))
        self.assertEqual(stdout.strip(), b"limited")

    def child_worker(self):
        marker = self.folder / "child.pid"
        self.worker.write_text(self.prefix + f"""
from karity_bot.limits import apply_limits
from pathlib import Path
import subprocess
import time
apply_limits(128, 60, 1048576)
child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'])
Path({str(marker)!r}).write_text(str(child.pid))
time.sleep(60)
""", encoding="utf-8")
        return marker

    async def assert_child_stopped(self, marker):
        self.assertTrue(marker.exists(), "fixture child was not started")
        pid = int(marker.read_text())
        for _ in range(30):
            if not process_running(pid):
                return
            await asyncio.sleep(0.05)
        self.fail("worker descendant survived termination")

    async def test_timeout_kills_descendants(self):
        marker = self.child_worker()
        with patch("karity_bot.engine.WORKER", self.worker):
            with self.assertRaises(JobError) as error:
                await Engine(self.settings).build(b"print(1)")
        self.assertEqual(error.exception.code, "timeout")
        await self.assert_child_stopped(marker)

    async def test_cancellation_kills_descendants(self):
        marker = self.child_worker()
        with patch("karity_bot.engine.WORKER", self.worker):
            task = asyncio.create_task(Engine(replace(self.settings, job_timeout=10)).build(b"print(1)"))
            for _ in range(100):
                if marker.exists():
                    break
                await asyncio.sleep(0.03)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        await self.assert_child_stopped(marker)

    async def test_workspace_limit_is_enforced(self):
        self.worker.write_text("from pathlib import Path\nimport time\nPath('large.bin').write_bytes(b'x'*8192)\ntime.sleep(60)\n")
        settings = replace(self.settings, max_input_bytes=1024, max_output_bytes=1024, max_workspace_bytes=4096)
        with patch("karity_bot.engine.WORKER", self.worker):
            with self.assertRaises(JobError) as error:
                await Engine(settings).build(b"print(1)")
        self.assertEqual(error.exception.code, "workspace_limit")
