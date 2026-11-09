"""Read-only access to the LMU ``LMU_Data`` shared-memory mapping.

Safety guarantees
-----------------
* Windows: ``OpenFileMappingW(FILE_MAP_READ)`` + ``MapViewOfFile(FILE_MAP_READ)``. It never creates
  a mapping (unlike ``mmap.mmap(-1, size, tagname)`` which silently creates an empty one when the
  game is not running) and cannot write. No process handle is opened, nothing is injected.
* Linux/Wine bridge and tests: ``/dev/shm/<name>`` (or any file) opened ``O_RDONLY`` + ``ACCESS_READ``.
* Nothing here touches the game's files, memory or anti-cheat.

The Windows backend could not be executed in the development environment (Linux): it is
implemented but UNVERIFIED until run on a Windows machine with LMU open.
"""
from __future__ import annotations

import ctypes
import mmap
import os
import sys
from dataclasses import dataclass
from typing import Protocol

from . import layout as L


class MappingNotFound(Exception):
    """The mapping does not exist (game not running, plugins disabled, or wrong name)."""


class Backend(Protocol):
    size: int
    description: str

    def read(self, offset: int, length: int) -> bytes: ...
    def close(self) -> None: ...


class BytesBackend:
    """Backend over an in-memory buffer (used by the synthetic game and tests)."""

    def __init__(self, buf: bytearray | memoryview, description: str = "memory buffer"):
        self._buf = buf
        self.size = len(buf)
        self.description = description

    def read(self, offset: int, length: int) -> bytes:
        return bytes(self._buf[offset:offset + length])

    def close(self) -> None:
        pass


class FileBackend:
    """Read-only mmap of a file (``/dev/shm/LMU_Data`` on Linux/Wine bridges)."""

    def __init__(self, path: str):
        try:
            fd = os.open(path, os.O_RDONLY)
        except FileNotFoundError as e:
            raise MappingNotFound(path) from e
        try:
            self.size = os.fstat(fd).st_size
            if self.size == 0:
                raise MappingNotFound(f"{path} is empty")
            self._mm = mmap.mmap(fd, self.size, access=mmap.ACCESS_READ)
        finally:
            os.close(fd)
        self.description = f"file mapping {path}"

    def read(self, offset: int, length: int) -> bytes:
        return self._mm[offset:offset + length]

    def close(self) -> None:
        self._mm.close()


class WindowsBackend:  # pragma: no cover - requires Windows
    FILE_MAP_READ = 0x0004
    MEM_COMMIT = 0x1000

    def __init__(self, name: str = L.LMU_SHARED_MEMORY_NAME):
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        k32.OpenFileMappingW.restype = ctypes.c_void_p
        k32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
        k32.MapViewOfFile.restype = ctypes.c_void_p
        k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
        k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._k32 = k32
        h = k32.OpenFileMappingW(self.FILE_MAP_READ, False, name)
        if not h:
            raise MappingNotFound(f"OpenFileMappingW({name!r}) failed, winerror={ctypes.get_last_error() or ctypes.GetLastError()}")
        self._h = h
        self._ptr = k32.MapViewOfFile(h, self.FILE_MAP_READ, 0, 0, 0)
        if not self._ptr:
            k32.CloseHandle(h)
            raise MappingNotFound("MapViewOfFile failed")

        class MBI(ctypes.Structure):
            _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                        ("AllocationProtect", ctypes.c_uint32), ("PartitionId", ctypes.c_uint16),
                        ("RegionSize", ctypes.c_size_t), ("State", ctypes.c_uint32),
                        ("Protect", ctypes.c_uint32), ("Type", ctypes.c_uint32)]
        mbi = MBI()
        k32.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
        k32.VirtualQuery(self._ptr, ctypes.byref(mbi), ctypes.sizeof(mbi))
        self.size = int(mbi.RegionSize)  # page-rounded size of the real mapping
        self.description = f"Windows named mapping {name}"

    def read(self, offset: int, length: int) -> bytes:
        if offset + length > self.size:
            raise ValueError("read beyond mapping")
        return ctypes.string_at(self._ptr + offset, length)

    def close(self) -> None:
        if self._ptr:
            self._k32.UnmapViewOfFile(self._ptr)
            self._k32.CloseHandle(self._h)
            self._ptr = None


def open_backend(name: str = L.LMU_SHARED_MEMORY_NAME, path_override: str | None = None) -> Backend:
    if path_override:
        return FileBackend(path_override)
    if sys.platform == "win32":
        return WindowsBackend(name)  # pragma: no cover
    return FileBackend(f"/dev/shm/{name}")


@dataclass(slots=True)
class Snapshot:
    generic: L.Generic
    info: L.ScoringInfo
    veh: L.VehicleScoring | None
    telem: L.VehicleTelemetry | None
    player_has_vehicle: bool
    active_vehicles: int
    player_idx: int


class SharedMemoryReader:
    """Reads consistent snapshots of the player's data only (copy of ~3 KB, not of the 325 KB map)."""

    def __init__(self, backend: Backend):
        self.backend = backend

    @property
    def size_ok(self) -> bool:
        return self.backend.size >= L.MAPPING_SIZE

    def close(self) -> None:
        self.backend.close()

    def _struct(self, cls, offset):
        return cls.from_buffer_copy(self.backend.read(offset, ctypes.sizeof(cls)))

    def read_generic(self) -> L.Generic:
        return self._struct(L.Generic, L.OFF_GENERIC)

    def read_snapshot(self, retries: int = 3) -> Snapshot:
        """Return a snapshot; retries when the player telemetry slot changes mid-read (torn read)."""
        generic = self.read_generic()
        info = self._struct(L.ScoringInfo, L.OFF_SCORING_INFO)
        hdr = self.backend.read(L.OFF_TELEMETRY, 3)
        active, idx, has = hdr[0], hdr[1], bool(hdr[2])
        veh = None
        n = max(0, min(int(info.mNumVehicles), L.MAX_MAPPED_VEHICLES))
        for i in range(n):
            cand = self._struct(L.VehicleScoring, L.OFF_VEH_SCORING + i * L.SIZE_VEH_SCORING)
            if cand.mIsPlayer:
                veh = cand
                break
        telem = None
        if has and idx < L.MAX_MAPPED_VEHICLES:
            off = L.OFF_TELEM_INFO + idx * L.SIZE_TELEM
            for _ in range(retries):
                a = self._struct(L.VehicleTelemetry, off)
                b = self.backend.read(off + L.VehicleTelemetry.mElapsedTime.offset, 8)
                if ctypes.c_double.from_buffer_copy(b).value == a.mElapsedTime:
                    telem = a
                    break
            else:
                telem = a  # best effort after retries
        return Snapshot(generic, info, veh, telem, has, active, idx)
