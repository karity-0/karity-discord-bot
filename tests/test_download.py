import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from karity_bot.download import download_attachment
from karity_bot.errors import JobError


class Response:
    def __init__(self, chunks, *, status=200, content_length=None):
        self.chunks = chunks
        self.status = status
        self.content_length = content_length
        self.content = SimpleNamespace(iter_chunked=self.iter_chunked)

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            yield chunk

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    url = "https://cdn.discordapp.com/attachments/1/2/test.lua?ex=signed"

    async def test_stream_download(self):
        session = SimpleNamespace(get=MagicMock(return_value=Response([b"print", b"(1)"])))
        self.assertEqual(await download_attachment(session, self.url, 8), b"print(1)")
        session.get.assert_called_once_with(self.url, allow_redirects=False)

    async def test_untrusted_hosts_and_ports_never_requested(self):
        session = SimpleNamespace(get=MagicMock())
        for url in ["https://example.com/attachments/x", "http://cdn.discordapp.com/attachments/x",
                    "https://cdn.discordapp.com.evil.example/attachments/x", "https://127.0.0.1/x",
                    "https://cdn.discordapp.com:444/attachments/x", "https://cdn.discordapp.com/api/x"]:
            with self.subTest(url=url), self.assertRaises(JobError):
                await download_attachment(session, url, 10)
        session.get.assert_not_called()

    async def test_stream_limit_is_enforced_without_trusting_metadata(self):
        session = SimpleNamespace(get=MagicMock(return_value=Response([b"12345", b"6789"], content_length=None)))
        with self.assertRaises(JobError) as error:
            await download_attachment(session, self.url, 8)
        self.assertEqual(error.exception.code, "input_too_large")

    async def test_http_errors_redirects_and_large_content_length(self):
        for response, code in [(Response([], status=302), "download_failed"),
                               (Response([], status=404), "download_failed"),
                               (Response([], content_length=999), "input_too_large")]:
            session = SimpleNamespace(get=MagicMock(return_value=response))
            with self.subTest(code=code), self.assertRaises(JobError) as error:
                await download_attachment(session, self.url, 8)
            self.assertEqual(error.exception.code, code)
