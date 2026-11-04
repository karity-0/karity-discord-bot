"""Limits are installed inside the worker, before importing the engine."""
from __future__ import annotations

import math
import os

_job_handle = None


def apply_limits(memory_mb: int, timeout: float, workspace_bytes: int) -> None:
    if os.name == "nt":
        _windows_job(memory_mb * 1024 * 1024)
    elif os.name == "posix":
        import resource
        memory = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (math.ceil(timeout) + 1, math.ceil(timeout) + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (workspace_bytes, workspace_bytes))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    else:
        raise RuntimeError("unsupported worker platform")


def _windows_job(memory_bytes: int) -> None:
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
            ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t),
            ("max_ws", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
            ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", BasicLimits), ("io", IoCounters),
            ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    info = ExtendedLimits()
    # Aggregate committed memory + kill descendants when the worker's handle closes.
    info.basic.flags = 0x00000200 | 0x00002000
    info.job_memory = memory_bytes
    if (not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info))
            or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess())):
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    # Keep this non-inheritable handle alive until process exit. Closing it here
    # would also terminate the current worker before it writes its report.
    global _job_handle
    _job_handle = handle
