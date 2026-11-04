from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class Settings:
    token: str = field(default="", repr=False)
    engine_path: Path = field(default_factory=lambda: Path(".engine").resolve())
    jobs_path: Path = field(default_factory=lambda: Path(".jobs").resolve())
    guild_id: int | None = None
    max_input_bytes: int = 256 * 1024
    max_output_bytes: int = 8 * 1024 * 1024
    memory_mb: int = 512
    max_workspace_bytes: int = 128 * 1024 * 1024
    concurrency: int = 1
    queue_size: int = 4
    job_timeout: float = 120
    queue_timeout: float = 120
    download_timeout: float = 30

    def __post_init__(self) -> None:
        for name in ("max_input_bytes", "max_output_bytes", "memory_mb",
                     "max_workspace_bytes", "concurrency", "job_timeout",
                     "queue_timeout", "download_timeout"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.queue_size < 0:
            raise ValueError("queue_size must be zero or positive")
        if self.memory_mb < 128:
            raise ValueError("memory_mb must be at least 128")
        if self.max_workspace_bytes < max(self.max_input_bytes, self.max_output_bytes):
            raise ValueError("max_workspace_bytes must cover input and output limits")
        # Leave at least one minute for delivery before Discord's 15-minute expiry.
        if self.queue_timeout + self.download_timeout + self.job_timeout > 780:
            raise ValueError("queue + download + job timeouts must total at most 780 seconds")
        if self.guild_id is not None and self.guild_id <= 0:
            raise ValueError("DISCORD_GUILD_ID must be a positive server ID")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, require_token: bool = True) -> Settings:
        env = os.environ if env is None else env
        token = env.get("DISCORD_TOKEN", "").strip()
        if require_token and not token:
            raise ValueError("Set DISCORD_TOKEN in the environment or .env")
        def integer(key: str, default: int) -> int:
            try:
                return int(env.get(key, str(default)))
            except ValueError:
                raise ValueError(f"{key} must be an integer") from None
        return cls(
            token=token,
            engine_path=Path(env.get("KARITY_ENGINE_PATH", ".engine")).expanduser().resolve(),
            jobs_path=Path(env.get("KARITY_JOBS_PATH", ".jobs")).expanduser().resolve(),
            guild_id=integer("DISCORD_GUILD_ID", 0) if env.get("DISCORD_GUILD_ID") else None,
            max_input_bytes=integer("MAX_INPUT_BYTES", 262144),
            max_output_bytes=integer("MAX_OUTPUT_BYTES", 8388608),
            memory_mb=integer("JOB_MEMORY_MB", 512),
            max_workspace_bytes=integer("MAX_WORKSPACE_BYTES", 134217728),
            concurrency=integer("MAX_CONCURRENCY", 1),
            queue_size=integer("MAX_QUEUE_SIZE", 4),
            job_timeout=integer("JOB_TIMEOUT_SECONDS", 120),
            queue_timeout=integer("QUEUE_TIMEOUT_SECONDS", 120),
            download_timeout=integer("DOWNLOAD_TIMEOUT_SECONDS", 30),
        )
