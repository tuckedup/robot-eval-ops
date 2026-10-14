r"""Physical-device identity for the persisted device lease.

A lease is keyed by the PHYSICAL serial port, not by a config alias: two configs (or a CLI command and a
`session run`) naming the same port must collide. Keys are canonicalised so `COM3`, `com3`, `\\.\COM3` and (on
POSIX) a symlink to `/dev/ttyUSB0` all map to one key.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable

_WIN_NS_PREFIX = re.compile(r"^\\\\[.?]\\")
_COM_PORT = re.compile(r"(?i)(\\\\\.\\)?com\d+")


def canonical_port(port: str) -> str:
    p = port.strip()
    if sys.platform == "win32" or _COM_PORT.fullmatch(p):
        return "port:" + _WIN_NS_PREFIX.sub("", p).upper()
    return "port:" + os.path.realpath(p)


def hardware_lock_keys(ports: Iterable[str], label: str | None = None) -> list[str]:
    """Sorted, de-duplicated lease keys: one per physical port plus the (optional) human device label."""
    keys = {canonical_port(p) for p in ports if p and p.strip()}
    if label and label.strip():
        keys.add("label:" + label.strip())
    return sorted(keys)
