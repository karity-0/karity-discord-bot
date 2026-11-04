import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from karity_bot.bot import KarityBot, ObfuscateHandler
from karity_bot.config import Settings
from karity_bot.engine import BuildResult
from karity_bot.errors import JobError
from karity_bot.jobs import JobQueue


class CommandTests(unittest.IsolatedAsyncioTestCase):
    def make_handler(self):
        engine = SimpleNamespace(build=AsyncMock(return_value=BuildResult(b"protected", 1.25, {})))
        handler = ObfuscateHandler(Settings(), engine, JobQueue(1, 1, 5), object())
        self.uploads = []
        async def edit(**kwargs):
            for attachment in kwargs.get("attachments", []):
                self.uploads.append((attachment.filename, attachment.fp.read()))
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()),
                                      edit_original_response=AsyncMock(side_effect=edit),
                                      user=SimpleNamespace(id=1), filesize_limit=100)
        attachment = SimpleNamespace(filename="../../hello.lua", size=8,
                                     url="https://cdn.discordapp.com/attachments/1/2/hello.lua")
        return handler, interaction, attachment

    async def test_success_is_private_and_returns_attachment_and_duration(self):
        handler, interaction, attachment = self.make_handler()
        with patch("karity_bot.bot.download_attachment", AsyncMock(return_value=b"print(1)")):
            await handler.handle(interaction, attachment)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        handler.engine.build.assert_awaited_once_with(b"print(1)", output_limit=100)
        self.assertEqual(self.uploads, [("hello_obfuscated.lua", b"protected")])
        text = interaction.edit_original_response.call_args.kwargs["content"]
        self.assertIn("Fast + Bare", text)
        self.assertIn("1.25s", text)

    async def test_invalid_attachment_never_downloads_or_builds(self):
        handler, interaction, attachment = self.make_handler()
        attachment.filename = "script.exe"
        with patch("karity_bot.bot.download_attachment", AsyncMock()) as download:
            await handler.handle(interaction, attachment)
        download.assert_not_awaited()
        handler.engine.build.assert_not_awaited()
        self.assertIn(".lua", interaction.edit_original_response.call_args.kwargs["content"])

    async def test_engine_failure_is_concise(self):
        handler, interaction, attachment = self.make_handler()
        handler.engine.build.side_effect = JobError("timeout")
        with patch("karity_bot.bot.download_attachment", AsyncMock(return_value=b"print(1)")):
            await handler.handle(interaction, attachment)
        text = interaction.edit_original_response.call_args.kwargs["content"]
        self.assertIn("time limit", text)
        self.assertNotIn("Traceback", text)
        self.assertEqual(self.uploads, [])

    async def test_unexpected_exception_does_not_disclose_source_paths_or_tokens(self):
        handler, interaction, attachment = self.make_handler()
        private = "SECRET_SOURCE C:/private/path SECRET_TOKEN"
        handler.engine.build.side_effect = RuntimeError(private)
        with patch("karity_bot.bot.download_attachment", AsyncMock(return_value=b"print(1)")):
            with self.assertLogs("karity_bot.bot") as logs:
                await handler.handle(interaction, attachment)
        self.assertNotIn(private, " ".join(logs.output))
        self.assertNotIn(private, interaction.edit_original_response.call_args.kwargs["content"])

    async def test_full_queue_does_not_download(self):
        handler, interaction, attachment = self.make_handler()
        handler.queue = SimpleNamespace(run=AsyncMock(side_effect=JobError("queue_full")))
        with patch("karity_bot.bot.download_attachment", AsyncMock()) as download:
            await handler.handle(interaction, attachment)
        download.assert_not_awaited()
        self.assertIn("queue is full", interaction.edit_original_response.call_args.kwargs["content"])

    async def test_user_reservation_covers_attachment_delivery(self):
        handler, interaction, attachment = self.make_handler()
        delivering = asyncio.Event()
        release = asyncio.Event()
        async def slow_upload(**kwargs):
            if kwargs.get("attachments"):
                delivering.set()
                await release.wait()
        interaction.edit_original_response.side_effect = slow_upload
        with patch("karity_bot.bot.download_attachment", AsyncMock(return_value=b"print(1)")) as download:
            task = asyncio.create_task(handler.handle(interaction, attachment))
            await delivering.wait()
            await handler.handle(interaction, attachment)
            self.assertIn("already", interaction.edit_original_response.call_args.kwargs["content"])
            download.assert_awaited_once()
            release.set()
            await task

    async def test_real_slash_command_registration_requires_attachment_and_no_intents(self):
        bot = KarityBot(Settings(guild_id=123))
        bot.engine.verify = AsyncMock(return_value={"version": "1.6.0", "profile": "builtin:fast", "backend": "bare"})
        bot.tree.sync = AsyncMock(return_value=[])
        try:
            await bot.setup_hook()
            command = bot.tree.get_command("obfuscate", guild=discord.Object(id=123))
            payload = command.to_dict(bot.tree)
            self.assertEqual(payload["options"][0]["name"], "file")
            self.assertEqual(payload["options"][0]["type"], 11)  # Discord attachment option
            self.assertTrue(payload["options"][0]["required"])
            self.assertEqual(bot.intents.value, 0)
            self.assertEqual(bot.tree.sync.call_args.kwargs["guild"].id, 123)
        finally:
            await bot.close()
