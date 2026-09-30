"""Fail the build if anything bundled needs a newer system than Nova supports.

    python check_min_os.py <folder> <oldest macOS, e.g. 11.0> <oldest glibc, e.g. 2.28>

A single library built for a newer macOS (or Linux) stops Nova from starting
on an older computer, and nothing else would notice: the build machine runs
the newest system. This reads the minimum OS written into every compiled file
(Mach-O on macOS, ELF on Linux) and lists any that are too new.
"""
from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

LC_VERSION_MIN_MACOSX = 0x24
LC_BUILD_VERSION = 0x32
PLATFORM_MACOS = 1


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in text.split("."))


def _macho_min(data: bytes, offset: int = 0) -> tuple[int, int] | None:
    """Minimum macOS of one Mach-O image (thin or inside a fat file)."""
    magic = data[offset:offset + 4]
    if magic == b"\xcf\xfa\xed\xfe":
        header, endian = 32, "<"
    elif magic == b"\xce\xfa\xed\xfe":
        header, endian = 28, "<"
    else:
        return None
    ncmds = struct.unpack_from(endian + "I", data, offset + 16)[0]
    pos, found = offset + header, None
    for _ in range(ncmds):
        if pos + 8 > len(data):
            break
        cmd, size = struct.unpack_from(endian + "II", data, pos)
        if cmd == LC_BUILD_VERSION:
            plat, minos = struct.unpack_from(endian + "II", data, pos + 8)
            if plat == PLATFORM_MACOS:
                found = (minos >> 16, (minos >> 8) & 0xFF)
        elif cmd == LC_VERSION_MIN_MACOSX:
            v = struct.unpack_from(endian + "I", data, pos + 8)[0]
            found = (v >> 16, (v >> 8) & 0xFF)
        if size < 8:
            break
        pos += size
    return found


def macos_min(path: Path) -> tuple[int, int] | None:
    data = path.read_bytes()
    if data[:4] in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
        wide = data[:4] == b"\xca\xfe\xba\xbf"
        count = struct.unpack_from(">I", data, 4)[0]
        if count > 16:  # a Java class file shares the magic number
            return None
        mins = []
        for i in range(count):
            entry = 8 + i * (32 if wide else 20)
            off = struct.unpack_from(">Q" if wide else ">I", data, entry + (8 if wide else 8))[0]
            m = _macho_min(data, off)
            if m:
                mins.append(m)
        return max(mins) if mins else None
    return _macho_min(data)


_GLIBC = re.compile(rb"GLIBC_(2\.\d+)")


def glibc_min(path: Path) -> tuple[int, ...] | None:
    data = path.read_bytes()
    if data[:4] != b"\x7fELF":
        return None
    found = [_version(m.decode()) for m in set(_GLIBC.findall(data))]
    return max(found) if found else None


def main() -> int:
    folder, mac_floor, glibc_floor = Path(sys.argv[1]), _version(sys.argv[2]), _version(sys.argv[3])
    too_new, checked = [], 0
    for path in folder.rglob("*"):
        if not path.is_file() or path.is_symlink() or path.stat().st_size < 64:
            continue
        if path.suffix not in ("", ".so", ".dylib") and ".so." not in path.name:
            continue
        try:
            if sys.platform == "darwin":
                need, floor = macos_min(path), mac_floor[:2]
            elif sys.platform.startswith("linux"):
                need, floor = glibc_min(path), glibc_floor
            else:
                return 0
        except (OSError, struct.error):
            continue
        if need is None:
            continue
        checked += 1
        if tuple(need) > tuple(floor):
            too_new.append((".".join(map(str, need)), str(path.relative_to(folder))))
    system = "macOS" if sys.platform == "darwin" else "glibc"
    floor_text = sys.argv[2] if sys.platform == "darwin" else sys.argv[3]
    print(f"Checked {checked} compiled files against {system} {floor_text}.")
    if too_new:
        for need, name in sorted(too_new, reverse=True)[:40]:
            print(f"  needs {system} {need}: {name}")
        print(f"{len(too_new)} files need a newer system than Nova supports.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
