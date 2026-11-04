from __future__ import annotations

from urllib.parse import urlsplit

import aiohttp

from .errors import JobError


async def download_attachment(session: aiohttp.ClientSession, url: str, maximum: int) -> bytes:
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname in {"cdn.discordapp.com", "media.discordapp.net"}
                 and parsed.port in {None, 443} and not parsed.username and not parsed.password
                 and parsed.path.startswith(("/attachments/", "/ephemeral-attachments/")))
    except ValueError:
        valid = False
    if not valid:
        raise JobError("download_failed")
    try:
        async with session.get(url, allow_redirects=False) as response:
            if response.status != 200:
                raise JobError("download_failed")
            if response.content_length is not None and response.content_length > maximum:
                raise JobError("input_too_large")
            result = bytearray()
            async for chunk in response.content.iter_chunked(16384):
                if len(result) + len(chunk) > maximum:
                    raise JobError("input_too_large")
                result.extend(chunk)
            return bytes(result)
    except (aiohttp.ClientError, TimeoutError):
        # URLs contain signed query parameters; never log the originating exception.
        raise JobError("download_failed") from None
