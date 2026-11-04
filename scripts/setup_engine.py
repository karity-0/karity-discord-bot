"""Fetch the locked engine into a NEW directory; never update an existing checkout."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT / ".engine")
    args = parser.parse_args()
    destination = args.destination.expanduser().resolve()
    lock = json.loads((ROOT / "karity_bot" / "engine.lock.json").read_text(encoding="utf-8"))
    if destination.exists():
        parser.exit(1, "Destination already exists. Keep it, or select a NEW --destination; nothing was changed.\n")
    try:
        subprocess.run(["git", "init", str(destination)], check=True, timeout=30)
        # No remote is created for the bot repository. Only read the engine upstream.
        subprocess.run(["git", "-C", str(destination), "fetch", "--depth", "1", lock["repository"], lock["commit"]],
                       check=True, timeout=300)
        subprocess.run(["git", "-C", str(destination), "checkout", "--detach", "FETCH_HEAD"], check=True, timeout=60)
    except (subprocess.SubprocessError, OSError):
        parser.exit(1, "Engine setup failed. Check Git/network access and the locked commit. Partial destination was kept.\n")
    print(f"Installed Karity {lock['version']} at {lock['commit']}")


if __name__ == "__main__":
    main()
