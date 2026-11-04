from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

from .config import Settings
from .errors import JobError
from .validation import validate_source

LOCK = json.loads(Path(__file__).with_name("engine.lock.json").read_text(encoding="utf-8"))
WORKER = Path(__file__).with_name("worker.py").resolve()


@dataclass(frozen=True)
class BuildResult:
    data: bytes
    duration: float
    effective: dict


def worker_environment(folder: Path) -> dict[str, str]:
    # Do not pass DISCORD_TOKEN, interaction tokens, proxies, or arbitrary secrets.
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE"}}
    env.update(TMPDIR=str(folder), TEMP=str(folder), TMP=str(folder),
               PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    return env


def workspace_usage(folder: Path) -> int:
    total = 0
    for directory, _, files in os.walk(folder):
        for name in files:
            try:
                total += (Path(directory) / name).stat().st_size
            except FileNotFoundError:
                pass  # Engine intermediates can disappear between scan and stat.
    return total


async def terminate_process(process: asyncio.subprocess.Process) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.returncode is None:
        # The worker-owned Windows Job Object kills compiler descendants on exit.
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.wait()


class Engine:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def verify(self) -> dict:
        engine = self.settings.engine_path
        if not (engine / "main.py").is_file():
            raise JobError("engine_unavailable")
        # Per-invocation safe.directory only; never change the operator's Git config.
        for arguments in (("rev-parse", "HEAD"), ("diff", "--quiet", "HEAD", "--")):
            try:
                process = await asyncio.create_subprocess_exec(
                    "git", "-c", f"safe.directory={engine.as_posix()}", "-C", str(engine), *arguments,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                try:
                    async with asyncio.timeout(15):
                        stdout, _ = await process.communicate()
                finally:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
            except (OSError, TimeoutError):
                raise JobError("engine_unavailable") from None
            if process.returncode or (arguments[0] == "rev-parse" and stdout.decode().strip() != LOCK["commit"]):
                raise JobError("engine_unavailable")
        _, report = await self._run(None, self.settings.max_output_bytes)
        return report["effective"]

    async def build(self, source: bytes, *, output_limit: int | None = None) -> BuildResult:
        source = validate_source(source, self.settings.max_input_bytes)
        maximum = self.settings.max_output_bytes if output_limit is None else min(self.settings.max_output_bytes, output_limit)
        if maximum <= 0:
            raise JobError("output_too_large")
        data, report = await self._run(source, maximum)
        return BuildResult(data, report["duration"], report["effective"])

    async def _run(self, source: bytes | None, output_limit: int) -> tuple[bytes, dict]:
        settings = self.settings
        await asyncio.to_thread(settings.jobs_path.mkdir, parents=True, exist_ok=True, mode=0o700)
        temporary = await asyncio.to_thread(tempfile.TemporaryDirectory, prefix="job-", dir=settings.jobs_path)
        folder = Path(temporary.name)
        try:
            if source is not None:
                await asyncio.to_thread((folder / "input.lua").write_bytes, source)
            command = [sys.executable, "-I", "-B", str(WORKER), "--engine", str(settings.engine_path),
                       "--memory-mb", str(settings.memory_mb), "--timeout", str(settings.job_timeout),
                       "--workspace-bytes", str(settings.max_workspace_bytes),
                       "--output-bytes", str(output_limit)]
            if source is None:
                command.append("--check")
            kwargs = {"start_new_session": True} if os.name == "posix" else {"creationflags": subprocess.CREATE_NO_WINDOW}
            try:
                process = await asyncio.create_subprocess_exec(
                    *command, cwd=folder, env=worker_environment(folder),
                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL, **kwargs)
            except OSError:
                raise JobError("engine_unavailable") from None
            waiter = asyncio.create_task(process.wait())
            try:
                async with asyncio.timeout(settings.job_timeout):
                    while True:
                        try:
                            await asyncio.wait_for(asyncio.shield(waiter), 0.1)
                            break
                        except TimeoutError:
                            if await asyncio.to_thread(workspace_usage, folder) > settings.max_workspace_bytes:
                                raise JobError("workspace_limit")
                            output = folder / "output.lua"
                            if output.exists() and output.stat().st_size > output_limit:
                                raise JobError("output_too_large")
            except TimeoutError:
                raise JobError("timeout") from None
            finally:
                await terminate_process(process)
                await waiter
            if await asyncio.to_thread(workspace_usage, folder) > settings.max_workspace_bytes:
                raise JobError("workspace_limit")
            report_path = folder / "report.json"
            if process.returncode or not report_path.is_file() or report_path.stat().st_size > 16384:
                raise JobError("build_failed")
            report = json.loads(await asyncio.to_thread(report_path.read_text, encoding="utf-8"))
            if "error" in report:
                raise JobError(report["error"])
            effective = report.get("effective", {})
            if (effective.get("profile"), effective.get("backend"), effective.get("lua_version")) != ("builtin:fast", "bare", "5.3"):
                raise JobError("engine_unavailable")
            if source is None:
                return b"", report
            output = folder / "output.lua"
            if not output.is_file() or output.stat().st_size > output_limit:
                raise JobError("output_too_large")
            data = await asyncio.to_thread(output.read_bytes)
            if not data:
                raise JobError("build_failed")
            return data, report
        finally:
            await asyncio.to_thread(temporary.cleanup)
