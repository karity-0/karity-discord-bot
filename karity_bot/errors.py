"""Only these fixed messages may be shown to users or written to logs."""

MESSAGES = {
    "invalid_file": "Upload a non-empty .lua source file.",
    "input_too_large": "The input file exceeds this bot's size limit.",
    "invalid_source": "Use a non-empty UTF-8 Lua source file, not binary bytecode.",
    "custom_settings": "This bot uses Fast + Bare only. Remove Karity macros and protection directives.",
    "duplicate": "You already have a queued or running job. Please wait for it to finish.",
    "queue_full": "The bot is busy and its queue is full. Please try again later.",
    "queue_timeout": "The queue wait limit was reached. Please try again later.",
    "timeout": "The build exceeded its time limit. Try a smaller file.",
    "memory_limit": "The build exceeded its memory limit. Try a smaller file.",
    "output_too_large": "The result exceeds the output or Discord attachment size limit.",
    "workspace_limit": "The build exceeded its temporary storage limit. Try a smaller file.",
    "download_failed": "The attachment could not be downloaded. Upload it again and retry.",
    "build_failed": "Karity could not process this file. Check that it is valid, supported Lua 5.3 source.",
    "engine_unavailable": "The obfuscator is unavailable. Please contact the bot operator.",
    "limits_unavailable": "The worker could not apply resource limits. Please contact the bot operator.",
    "stopping": "The bot is shutting down. Please try again later.",
    "internal": "The job could not be completed. Please try again later.",
}


class JobError(Exception):
    def __init__(self, code: str):
        self.code = code if code in MESSAGES else "internal"
        super().__init__(MESSAGES[self.code])
