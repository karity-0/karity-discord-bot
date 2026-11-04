from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
import signal

import aiohttp
import discord
from dotenv import load_dotenv

from .bot import KarityBot
from .config import Settings
from .engine import Engine
from .errors import JobError


async def run(settings: Settings, check: bool, smoke: bool) -> None:
    loop = asyncio.get_running_loop()
    signal_handler = False
    try:
        # Docker/systemd normally stop the bot with SIGTERM. Cancel gracefully so
        # workers are killed and temporary sources are removed before exit.
        loop.add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
        signal_handler = True
    except NotImplementedError:
        pass  # Windows' event loop uses asyncio.run's normal Ctrl+C handling.
    try:
        await run_mode(settings, check, smoke)
    finally:
        if signal_handler:
            loop.remove_signal_handler(signal.SIGTERM)


async def run_mode(settings: Settings, check: bool, smoke: bool) -> None:
    if check or smoke:
        engine = Engine(settings)
        print(json.dumps(await engine.verify(), indent=2))
        if smoke:
            for source in (b"print(1)", b"local t={1,2,3}; for i=1,#t do print(t[i]) end",
                           b"local function add(a,b) return a+b end; print(add(2,3))"):
                result = await engine.build(source)
                print(f"Generated {len(result.data):,} bytes in {result.duration:.2f}s (not executed)")
        return
    async with KarityBot(settings) as bot:
        await bot.start(settings.token)


def main() -> None:
    parser = argparse.ArgumentParser(description="Karity Discord Bot v0.1.0")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check-engine", action="store_true", help="check engine pin, limits and Fast + Bare; no token needed")
    modes.add_argument("--smoke-test", action="store_true", help="build three built-in examples without executing them")
    args = parser.parse_args()
    load_dotenv(Path.cwd() / ".env", override=False)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("discord").setLevel(logging.CRITICAL)
    try:
        settings = Settings.from_env(require_token=not (args.check_engine or args.smoke_test))
        asyncio.run(run(settings, args.check_engine, args.smoke_test))
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    except (ValueError, JobError) as error:
        parser.exit(1, f"Startup failed: {error}\n")
    except discord.LoginFailure:
        parser.exit(1, "Startup failed: Discord rejected DISCORD_TOKEN. Check the bot token.\n")
    except (aiohttp.ClientError, discord.HTTPException, OSError):
        parser.exit(1, "Startup failed: check network access, Discord permissions and local setup.\n")


if __name__ == "__main__":
    main()
