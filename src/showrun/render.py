"""Render a demo to an asciinema .cast file without a terminal (for docs, CI and agents)."""

from __future__ import annotations

import io
import random
from dataclasses import dataclass, field
from typing import List

from rich.console import Console

from .cast import CastTee
from .keys import AutoKeys
from .model import Demo
from .player import Player


class _Sink(io.StringIO):
    """A stream that keeps nothing: the cast file is the only output."""

    def write(self, data: str) -> int:
        return len(data)

    def isatty(self) -> bool:
        return False


@dataclass
class RenderResult:
    path: str
    steps: int
    failures: int
    warnings: List[str] = field(default_factory=list)


def render_cast(demo: Demo, path: str, *, offline: bool = False, delay: float = 1.0,
                width: int = 100, height: int = 30, seed: int = 7) -> RenderResult:
    """Play *demo* unattended, pressing Enter after *delay* seconds, and record it to *path*.

    Typing, typos and output timing are real, so the cast looks like a live presentation.
    """
    tee = CastTee(_Sink(), path, demo.title, size=(width, height), crlf=True)
    console = Console(file=tee, force_terminal=True, color_system="truecolor", highlight=False,
                      width=width, height=height)
    player = Player(demo, console=console, keys=AutoKeys(delay), offline=offline,
                    rng=random.Random(seed), on_step=lambda i, st: tee.marker(st.label()))
    try:
        failures = player.play()
    finally:
        tee.close()
    return RenderResult(path, len(demo.steps), failures, list(player.warnings))
