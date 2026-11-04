from __future__ import annotations

import asyncio
import io
import logging
import time

import aiohttp
import discord
from discord import app_commands

from .config import Settings
from .download import download_attachment
from .engine import Engine
from .errors import JobError
from .jobs import JobQueue
from .validation import output_filename, validate_attachment

log = logging.getLogger(__name__)


class ObfuscateHandler:
    def __init__(self, settings: Settings, engine: Engine, queue: JobQueue,
                 session: aiohttp.ClientSession):
        self.settings, self.engine, self.queue, self.session = settings, engine, queue, session

    async def deliver(self, interaction: discord.Interaction, **kwargs) -> None:
        async with asyncio.timeout(45):
            await interaction.edit_original_response(**kwargs)

    async def handle(self, interaction: discord.Interaction, attachment: discord.Attachment) -> None:
        started = time.perf_counter()
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            validate_attachment(attachment.filename, attachment.size, self.settings.max_input_bytes)
            limit = min(self.settings.max_output_bytes, interaction.filesize_limit)

            async def operation():
                data = await download_attachment(self.session, attachment.url, self.settings.max_input_bytes)
                result = await self.engine.build(data, output_limit=limit)
                # Retain admission until delivery completes, bounding buffered results too.
                with io.BytesIO(result.data) as buffer:
                    file = discord.File(buffer, filename=output_filename(attachment.filename))
                    try:
                        await self.deliver(
                            interaction,
                            content=(f"Done · Fast + Bare · Lua 5.3\nBuild: {result.duration:.2f}s · "
                                     f"Total before upload: {time.perf_counter() - started:.2f}s · Output: {len(result.data):,} bytes"),
                            attachments=[file], allowed_mentions=discord.AllowedMentions.none())
                    finally:
                        file.close()
                log.info("job succeeded build_seconds=%.2f output_bytes=%d", result.duration, len(result.data))

            await self.queue.run(interaction.user.id, operation)
        except JobError as error:
            log.info("job failed code=%s", error.code)
            await self.deliver(interaction, content=f"Failed · {error}\nTotal: {time.perf_counter() - started:.2f}s")
        except asyncio.CancelledError:
            # close() cancels queued and running callbacks; the engine cleans its process tree.
            try:
                await self.deliver(interaction, content=str(JobError("stopping")))
            except (discord.HTTPException, TimeoutError):
                pass
            raise
        except (discord.HTTPException, TimeoutError):
            # Avoid logging HTTP exceptions: webhook URLs carry interaction credentials.
            log.warning("Discord could not deliver the job response")
        except Exception:
            log.error("job failed code=internal")
            await self.deliver(interaction, content=str(JobError("internal")))


class KarityBot(discord.Client):
    def __init__(self, settings: Settings):
        super().__init__(intents=discord.Intents.none(), allowed_mentions=discord.AllowedMentions.none())
        self.settings = settings
        self.tree = app_commands.CommandTree(self)
        self.engine = Engine(settings)
        self.queue = JobQueue(settings.concurrency, settings.queue_size, settings.queue_timeout)
        self.download_session: aiohttp.ClientSession | None = None
        self.tree.on_error = self.command_error

    async def setup_hook(self) -> None:
        effective = await self.engine.verify()
        log.info("engine ready version=%s profile=%s backend=%s", effective["version"],
                 effective["profile"], effective["backend"])
        self.download_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.settings.download_timeout),
            connector=aiohttp.TCPConnector(limit=self.settings.concurrency),
            auto_decompress=False, trust_env=False)
        handler = ObfuscateHandler(self.settings, self.engine, self.queue, self.download_session)

        @self.tree.command(name="obfuscate", description="Obfuscate a Lua 5.3 file with Karity (Fast + Bare).")
        @app_commands.describe(file="A UTF-8 .lua source file. The result is visible only to you.")
        @app_commands.guild_only()
        async def obfuscate(interaction: discord.Interaction, file: discord.Attachment):
            await handler.handle(interaction, file)

        if self.settings.guild_id:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("commands synced to development server")
        else:
            await self.tree.sync()
            log.info("commands synced globally")

    async def command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        log.error("command failed")
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(content=str(JobError("internal")))
            else:
                await interaction.response.send_message(str(JobError("internal")), ephemeral=True)
        except discord.HTTPException:
            log.warning("Discord could not deliver the error response")

    async def on_ready(self) -> None:
        log.info("Karity bot connected")

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        log.error("Discord event handler failed")

    async def close(self) -> None:
        await self.queue.close()
        if self.download_session:
            await self.download_session.close()
        await super().close()
