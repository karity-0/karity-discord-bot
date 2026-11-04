import unittest

from karity_bot.config import Settings
from karity_bot.errors import JobError
from karity_bot.validation import output_filename, validate_attachment, validate_source


class ValidationTests(unittest.TestCase):
    def test_attachment_boundaries(self):
        validate_attachment("Hello.LUA", 10, 10)
        for filename, size, code in [("a.txt", 1, "invalid_file"), ("a.lua", 0, "invalid_file"),
                                     ("a.lua", 11, "input_too_large")]:
            with self.subTest(filename=filename, size=size), self.assertRaises(JobError) as error:
                validate_attachment(filename, size, 10)
            self.assertEqual(error.exception.code, code)

    def test_utf8_bom_is_normalized(self):
        self.assertEqual(validate_source(b"\xef\xbb\xbfprint(1)", 100), b"print(1)")

    def test_binary_empty_and_oversized_rejected(self):
        for source in [b"", b" \n", b"\x1bLua", b"a\x00b", b"\xff", b"x" * 101]:
            with self.subTest(source=source), self.assertRaises(JobError):
                validate_source(source, 100)

    def test_display_filename_cannot_contain_paths_or_mentions(self):
        self.assertEqual(output_filename("../../evil.lua"), "evil_obfuscated.lua")
        self.assertEqual(output_filename("C:\\path\\@everyone.lua"), "everyone_obfuscated.lua")
        self.assertEqual(output_filename("한글.lua"), "script_obfuscated.lua")
        self.assertLess(len(output_filename("x" * 500 + ".lua")), 100)

    def test_configuration_rejects_unbounded_limits_and_long_interactions(self):
        for env in [{"MAX_CONCURRENCY": "0"}, {"MAX_QUEUE_SIZE": "-1"}, {"JOB_MEMORY_MB": "1"},
                    {"MAX_INPUT_BYTES": "abc"}, {"JOB_TIMEOUT_SECONDS": "700"}, {"DISCORD_GUILD_ID": "0"}]:
            with self.subTest(env=env), self.assertRaises(ValueError):
                Settings.from_env(env, require_token=False)
        self.assertEqual(Settings.from_env({"MAX_QUEUE_SIZE": "0"}, require_token=False).queue_size, 0)

    def test_token_required_and_not_in_repr(self):
        with self.assertRaises(ValueError):
            Settings.from_env({})
        self.assertNotIn("secret", repr(Settings(token="secret")))
