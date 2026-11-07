"""Keypress sources: the real terminal, a scripted list (tests), or auto-advance."""

from __future__ import annotations

import os
import select
import sys
import time
from typing import Iterable, Optional

ENTER = "enter"
ESC = "esc"
BACKSPACE = "backspace"


def _normalise(ch: str) -> str:
    if ch in ("\r", "\n"):
        return ENTER
    if ch == "\x1b":
        return ESC
    if ch in ("\x7f", "\x08"):
        return BACKSPACE
    if ch == "\x03":
        raise KeyboardInterrupt
    return ch


class KeySource:
    def read(self, timeout: Optional[float] = None) -> Optional[str]:  # pragma: no cover
        raise NotImplementedError

    def poll(self) -> Optional[str]:
        return self.read(timeout=0)

    def suspend(self):  # context used while handing the tty to a child
        return _Null()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


class _Null:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


class TerminalKeys(KeySource):
    """Reads single keys from the controlling terminal in cbreak mode."""

    def __init__(self, stream=None):
        self.stream = stream or sys.stdin
        self.fd = self.stream.fileno()
        self._saved = None

    def __enter__(self):
        import termios
        import tty

        if os.isatty(self.fd):
            self._saved = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        return self

    def __exit__(self, *exc):
        import termios

        if self._saved is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)
            self._saved = None

    def suspend(self):
        outer = self

        class _Suspend:
            def __enter__(self_inner):
                outer.__exit__()

            def __exit__(self_inner, *exc):
                outer.__enter__()

        return _Suspend()

    def read(self, timeout: Optional[float] = None) -> Optional[str]:
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return None
        ch = os.read(self.fd, 1).decode(errors="ignore")
        if ch == "\x1b":
            # Swallow the rest of an escape sequence (arrow keys etc.).
            seq = ""
            while select.select([self.fd], [], [], 0.01)[0]:
                seq += os.read(self.fd, 1).decode(errors="ignore")
            return {"[C": "right", "[D": "left", "[A": "up", "[B": "down"}.get(seq, ESC)
        return _normalise(ch)


class ScriptedKeys(KeySource):
    """Feeds a fixed sequence of keys; returns ENTER forever (or 'q') when exhausted."""

    def __init__(self, keys: Iterable[str], then: str = ENTER):
        self.keys = list(keys)
        self.then = then

    def read(self, timeout: Optional[float] = None) -> Optional[str]:
        if self.keys:
            return self.keys.pop(0)
        return self.then

    def poll(self) -> Optional[str]:
        return None  # never interrupts typing


class AutoKeys(KeySource):
    """Presses Enter by itself after *delay* seconds, but real keys still work."""

    def __init__(self, delay: float, inner: Optional[KeySource] = None):
        self.delay = delay
        self.inner = inner

    def __enter__(self):
        if self.inner:
            self.inner.__enter__()
        return self

    def __exit__(self, *exc):
        if self.inner:
            self.inner.__exit__(*exc)

    def suspend(self):
        return self.inner.suspend() if self.inner else _Null()

    def read(self, timeout: Optional[float] = None) -> Optional[str]:
        if timeout == 0:
            return self.inner.read(0) if self.inner else None
        end = time.monotonic() + self.delay
        while time.monotonic() < end:
            if self.inner:
                k = self.inner.read(timeout=min(0.05, max(0, end - time.monotonic())))
                if k:
                    return k
            else:
                time.sleep(min(0.05, end - time.monotonic()))
        return ENTER
