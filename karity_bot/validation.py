import re
import unicodedata

from .errors import JobError


def validate_attachment(filename: str, size: int, maximum: int) -> None:
    if not filename.lower().endswith(".lua") or size <= 0:
        raise JobError("invalid_file")
    if size > maximum:
        raise JobError("input_too_large")


def validate_source(data: bytes, maximum: int) -> bytes:
    if len(data) > maximum:
        raise JobError("input_too_large")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise JobError("invalid_source") from None
    if not text.strip() or "\x00" in text or "\x1b" in text:
        raise JobError("invalid_source")
    return text.encode("utf-8")


def output_filename(filename: str) -> str:
    # This is only a Discord display name; disk paths are always fixed by us.
    basename = unicodedata.normalize("NFKC", filename).replace("\\", "/").rsplit("/", 1)[-1]
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", basename[:-4]).strip("_")[:64] or "script"
    return f"{stem}_obfuscated.lua"
