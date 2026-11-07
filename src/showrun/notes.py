"""Presenter notes: the player publishes its position to a small JSON file and
`showrun notes` renders it live in a second terminal (or on a second screen)."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from .model import Demo


def default_notes_path(demo_path: str) -> str:
    stem = Path(demo_path).resolve().as_posix().replace("/", "_").strip("_")
    return os.path.join(tempfile.gettempdir(), f"showrun-notes-{stem}.json")


class NotesPublisher:
    def __init__(self, path: Optional[str], demo: Demo):
        self.path = path
        self.demo = demo
        self.started = time.time()

    def publish(self, index: int, state: str = "ready") -> None:
        if not self.path:
            return
        steps = self.demo.steps

        def info(i: int) -> Optional[dict]:
            if 0 <= i < len(steps):
                s = steps[i]
                return {"n": i + 1, "label": s.label(), "run": s.run, "say": s.say,
                        "notes": s.notes, "hidden": s.hidden}
            return None

        nxt = next((j for j in range(index + 1, len(steps)) if not steps[j].hidden), -1)
        payload = {"title": self.demo.title, "total": len(steps), "state": state,
                   "started": self.started, "current": info(index), "next": info(nxt)}
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, self.path)

    def finish(self) -> None:
        self.publish(len(self.demo.steps), state="finished")


def _render(data: dict) -> Panel:
    elapsed = int(time.time() - data.get("started", time.time()))
    cur = data.get("current")
    parts = []
    header = Text()
    header.append(data.get("title") or "showrun", style="bold")
    header.append(f"   ⏱ {elapsed // 60:02d}:{elapsed % 60:02d}", style="cyan")
    if data.get("state") == "finished":
        header.append("   ✓ finished", style="bold green")
    parts.append(header)
    if cur:
        parts.append(Text(f"\nNOW  step {cur['n']}/{data['total']}: {cur['label']}", style="bold yellow"))
        if cur.get("run"):
            parts.append(Syntax(cur["run"], "bash", theme="monokai", background_color="default"))
        if cur.get("say"):
            parts.append(Text("Say: " + cur["say"], style="italic"))
        if cur.get("notes"):
            parts.append(Panel(cur["notes"], title="notes", border_style="magenta"))
    nxt = data.get("next")
    if nxt:
        parts.append(Text(f"\nNEXT step {nxt['n']}: {nxt['label']}", style="dim"))
        if nxt.get("notes"):
            parts.append(Text("  " + nxt["notes"].splitlines()[0], style="dim magenta"))
    return Panel(Group(*parts), title="presenter notes", border_style="blue")


def watch(path: str, console: Optional[Console] = None) -> None:
    console = console or Console()
    console.print(f"[dim]watching {path} — start `showrun play` in another terminal. Ctrl-C to quit.[/]")
    last = None
    with Live(Panel("waiting for the demo to start…"), console=console, refresh_per_second=4) as live:
        while True:
            try:
                data = json.loads(Path(path).read_text())
                last = data
            except (FileNotFoundError, json.JSONDecodeError):
                data = last
            if data:
                live.update(_render(data))
            time.sleep(0.25)
