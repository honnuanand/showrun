"""asciinema v2 .cast recording and playback, with no asciinema install required."""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Optional, TextIO


class CastTee:
    """File-like wrapper: writes to the real stream and records an asciinema v2 cast."""

    def __init__(self, stream: TextIO, path: str, title: Optional[str] = None):
        self.stream = stream
        cols, rows = shutil.get_terminal_size((100, 30))
        self.out = open(path, "w", encoding="utf-8")
        header = {"version": 2, "width": cols, "height": rows,
                  "timestamp": int(time.time()), "env": {"TERM": "xterm-256color"}}
        if title:
            header["title"] = title
        self.out.write(json.dumps(header) + "\n")
        self.start = time.monotonic()

    def write(self, data: str) -> int:
        if data:
            self.out.write(json.dumps([round(time.monotonic() - self.start, 6), "o", data]) + "\n")
        return self.stream.write(data)

    def marker(self, label: str) -> None:
        self.out.write(json.dumps([round(time.monotonic() - self.start, 6), "m", label]) + "\n")

    def flush(self) -> None:
        self.stream.flush()
        self.out.flush()

    def close(self) -> None:
        self.out.close()

    # Rich inspects these.
    def isatty(self) -> bool:
        return self.stream.isatty()

    def fileno(self) -> int:
        return self.stream.fileno()

    @property
    def encoding(self) -> str:
        return getattr(self.stream, "encoding", "utf-8")


def replay(path: str, speed: float = 1.0, max_idle: Optional[float] = 1.0,
           stream: TextIO = sys.stdout, sleep=time.sleep) -> float:
    """Play a .cast file to *stream*. Returns total (scaled) playback time."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError("empty cast file")
    header = json.loads(lines[0])
    if header.get("version") != 2:
        raise ValueError("only asciinema v2 casts are supported")
    last = 0.0
    total = 0.0
    for line in lines[1:]:
        if not line.strip():
            continue
        t, kind, data = json.loads(line)
        delay = t - last
        last = t
        if max_idle is not None:
            delay = min(delay, max_idle)
        delay /= speed
        if delay > 0:
            sleep(delay)
            total += delay
        if kind == "o":
            stream.write(data)
            stream.flush()
    return total
