import asyncio
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from karity_bot.config import Settings
from karity_bot.engine import Engine, worker_environment
from karity_bot.errors import JobError

ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = Path(os.environ.get("KARITY_TEST_ENGINE_PATH", str(ROOT.parent / "lua-obfuscator"))).resolve()
if not (ENGINE_PATH / "main.py").is_file() and "KARITY_TEST_ENGINE_PATH" not in os.environ:
    ENGINE_PATH = ROOT / ".engine"


class EnvironmentTests(unittest.TestCase):
    def test_worker_does_not_inherit_secrets_or_pythonpath(self):
        with patch.dict(os.environ, {"DISCORD_TOKEN": "secret", "OTHER_SECRET": "secret", "PYTHONPATH": "bad"}):
            env = worker_environment(Path("/job"))
        for key in ("DISCORD_TOKEN", "OTHER_SECRET", "PYTHONPATH"):
            self.assertNotIn(key, env)
        self.assertEqual(env["TMP"], str(Path("/job")))


@unittest.skipUnless((ENGINE_PATH / "main.py").is_file(), "Set KARITY_TEST_ENGINE_PATH or install the pinned engine")
class EngineIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = Settings(engine_path=ENGINE_PATH, jobs_path=self.root / "jobs")
        self.engine = Engine(self.settings)

    async def asyncTearDown(self):
        if self.settings.jobs_path.exists():
            self.assertEqual(list(self.settings.jobs_path.iterdir()), [], "job workspace leaked")
        self.temp.cleanup()

    async def test_pin_and_effective_configuration(self):
        effective = await self.engine.verify()
        self.assertEqual(effective["profile"], "builtin:fast")
        self.assertEqual(effective["backend"], "bare")
        self.assertEqual(effective["lua_version"], "5.3")

    async def test_simple_programs_generate_lua_without_execution(self):
        sources = [b"print(1)", b"local t={1,2,3}; for i=1,#t do print(t[i]) end",
                   b'local function f(x) return x.."!" end; print(f("hello"))']
        for source in sources:
            with self.subTest(source=source):
                result = await self.engine.build(source)
                self.assertGreater(len(result.data), len(source))
                self.assertGreater(result.duration, 0)
                self.assertEqual(result.effective["backend"], "bare")
                result.data.decode("utf-8")

    async def test_uploaded_program_side_effects_never_run(self):
        marker = self.root / "must-not-exist.txt"
        lua_path = marker.as_posix().replace('"', '\\"')
        source = f'local f=io.open("{lua_path}","w"); if f then f:write("executed"); f:close() end'.encode()
        result = await self.engine.build(source)
        self.assertTrue(result.data)
        self.assertFalse(marker.exists())

    async def test_invalid_syntax_fails_and_cleans_workspace(self):
        with self.assertRaises(JobError) as error:
            await self.engine.build(b"local = )")
        self.assertEqual(error.exception.code, "build_failed")

    async def test_output_limit(self):
        with self.assertRaises(JobError) as error:
            await self.engine.build(b"print(1)", output_limit=16)
        self.assertEqual(error.exception.code, "output_too_large")

    async def test_directives_cannot_override_fast_bare(self):
        for source in [b'--@VM(backend="karity")\nprint(1)', b'print(STRING_OBF("secret"))',
                       b'--@NO_VM_START\nprint(1)\n--@NO_VM_END']:
            with self.subTest(source=source), self.assertRaises(JobError) as error:
                await self.engine.build(source)
            self.assertEqual(error.exception.code, "custom_settings")

    async def test_marker_text_inside_string_remains_supported(self):
        result = await self.engine.build(b'print("--@VM(backend=karity)")')
        self.assertTrue(result.data)

    async def test_timeout_and_cancellation_clean_workspace(self):
        engine = Engine(replace(self.settings, job_timeout=0.001))
        with self.assertRaises(JobError) as error:
            await engine.build(b"print(1)")
        self.assertEqual(error.exception.code, "timeout")
        task = asyncio.create_task(self.engine.build(b"print(1)"))
        await asyncio.sleep(0.25)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
