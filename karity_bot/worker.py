"""Private subprocess entry point. Never executes submitted Lua or output Lua."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time


def resolve_engine(engine: Path, lock: dict):
    sys.path.insert(0, str(engine))
    spec = importlib.util.spec_from_file_location("_karity_engine_cli", engine / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from obfuscator import __version__
    from obfuscator.presets import PRESETS, REVISION
    if __version__ != lock["version"] or REVISION != lock["preset_revision"]:
        raise RuntimeError("engine version mismatch")
    # Reuse exactly the CLI's resolver. No engine-local config/GUI snapshot is loaded.
    config = module.resolve_config_profile({
        "target": {"lua_version": "5.3", "environment": "standalone", "compatibility": "runtime_specific"},
        "vm_options": {"backend": "bare"},
    }, "builtin:fast")
    module.validate_config(config)
    module.validate_deployment_config(config)
    expected_vm = {**PRESETS["fast"]["vm_options"], "backend": "bare"}
    if config.get("_profile") != "builtin:fast" or config.get("vm_options") != expected_vm:
        raise RuntimeError("incorrect effective protection")
    for key, value in PRESETS["fast"].items():
        if key != "vm_options" and config.get(key) != value:
            raise RuntimeError("incorrect effective preset")
    return module, config


def run(args: argparse.Namespace) -> dict:
    # -I excludes CWD/PYTHONPATH; only trusted project and pinned engine paths are added.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from karity_bot.limits import apply_limits
    try:
        apply_limits(args.memory_mb, args.timeout, args.workspace_bytes)
    except Exception:
        return {"error": "limits_unavailable"}
    lock = json.loads(Path(__file__).with_name("engine.lock.json").read_text(encoding="utf-8"))
    try:
        module, config = resolve_engine(Path(args.engine), lock)
        from obfuscator.toolchain import LuaToolchain
        toolchain = LuaToolchain.from_config(config)
        for executable in (toolchain.lua(), toolchain.luac()):
            result = subprocess.run([executable, "-v"], capture_output=True, timeout=10, check=True)
            if b"Lua 5.3" not in result.stdout + result.stderr:
                raise RuntimeError("Lua 5.3 required")
    except MemoryError:
        return {"error": "memory_limit"}
    except Exception:
        return {"error": "engine_unavailable"}
    effective = {"profile": config["_profile"], "backend": config["vm_options"]["backend"],
                 "lua_version": config["target"]["lua_version"], "version": lock["version"],
                 "passes": config["passes"], "vm_output_passes": config["vm_output_passes"]}
    if args.check:
        return {"effective": effective}
    try:
        from obfuscator.selection import SelectionPlan
        source = Path("input.lua").read_text(encoding="utf-8")
        # Source annotations can override backend/options or skip VM protection.
        # Use the engine parser to distinguish real annotations from string contents.
        if SelectionPlan(source).active:
            return {"error": "custom_settings"}
        started = time.perf_counter()
        pipeline = module.build_pipeline(config)
        output = pipeline.run(source, verbose=0).encode("utf-8")
        duration = time.perf_counter() - started
        if not output or len(output) > args.output_bytes:
            return {"error": "output_too_large"}
        Path("output.lua").write_bytes(output)
        return {"effective": effective, "duration": duration, "output_bytes": len(output)}
    except MemoryError:
        return {"error": "memory_limit"}
    except Exception:
        # Engine diagnostics can contain source excerpts or local paths. Discard them.
        return {"error": "build_failed"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True)
    parser.add_argument("--memory-mb", type=int, required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--workspace-bytes", type=int, required=True)
    parser.add_argument("--output-bytes", type=int, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        report = run(args)
    except MemoryError:
        report = {"error": "memory_limit"}
    except Exception:
        report = {"error": "internal"}
    Path("report.json").write_text(json.dumps(report), encoding="utf-8")


if __name__ == "__main__":
    main()
