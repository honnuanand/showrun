"""`showrun record`: do the demo once in a shell, get a replayable script."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from rich.console import Console

from .player import _strip_ansi
from .shell import Shell

RECORD_HELP = """\
[bold]Recording.[/] Type commands as normal; each one becomes a step.
  [cyan]#say[/] text      narration shown before the next command
  [cyan]#title[/] text    section heading before the next command
  [cyan]#note[/] text     presenter-only note for the next command
  [cyan]#hide[/] cmd      run cmd now, saved as a hidden step
  [cyan]#bg[/] cmd        start cmd in the background (servers)
  [cyan]#wait[/] cmd      add a wait_for check (e.g. curl -sf localhost:8000)
  [cyan]#fake[/]          last step: show its recorded output instead of running it
  [cyan]#pause[/]         add a pause step          [cyan]#undo[/]  drop the last step
  [cyan]#list[/]          show steps so far         [cyan]#done[/]  save and exit (or Ctrl-D)
[dim]Full-screen apps (vim, top) and commands that read from stdin aren't recordable.[/]"""


class _LiteralDumper(yaml.SafeDumper):
    pass


def _str_rep(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_LiteralDumper.add_representer(str, _str_rep)


def dump_yaml(doc: Dict[str, Any]) -> str:
    return yaml.dump(doc, Dumper=_LiteralDumper, sort_keys=False, allow_unicode=True, width=1000)


class Recorder:
    def __init__(self, path: str, title: Optional[str] = None, shell: str = "bash",
                 console: Optional[Console] = None, append: bool = False):
        self.path = Path(path)
        self.console = console or Console(highlight=False)
        self.doc: Dict[str, Any] = {"title": title or self.path.stem.replace("-", " ").replace("_", " ").title(),
                                    "settings": {"typing_speed": 0.04}, "steps": []}
        if append and self.path.exists():
            self.doc = yaml.safe_load(self.path.read_text()) or self.doc
            self.doc.setdefault("steps", [])
        self.shell_name = shell
        self.pending: Dict[str, Any] = {}

    @property
    def steps(self) -> List[Dict[str, Any]]:
        return self.doc["steps"]

    def save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(dump_yaml(self.doc))
        os.replace(tmp, self.path)

    def _add(self, step: Dict[str, Any]) -> None:
        step = {**self.pending, **step}
        self.pending = {}
        self.steps.append(step)
        self.save()

    # One line of input -> action. Returns False when recording should stop.
    def handle(self, line: str, sh: Shell, echo=None) -> bool:
        echo = echo or (lambda s: (self.console.file.write(s), self.console.file.flush()))
        stripped = line.strip()
        if not stripped:
            return True
        if stripped.startswith("#"):
            word, _, rest = stripped[1:].partition(" ")
            rest = rest.strip()
            if word in ("done", "quit", "exit"):
                return False
            if word in ("say", "title", "note") and rest:
                key = "notes" if word == "note" else word
                self.pending[key] = (self.pending.get(key, "") + "\n" + rest).strip()
            elif word == "hide" and rest:
                r = sh.run(rest)
                self._add({"run": rest, "hidden": True, **({"expect_exit": "any"} if r.exit_code else {})})
                self.console.print(f"[dim]hidden step saved (exit {r.exit_code})[/]")
            elif word == "bg" and rest:
                pid, log = sh.start_background(rest)
                self._add({"run": rest, "background": True})
                self.console.print(f"[dim]⟳ background pid {pid}, log {log}[/]")
            elif word == "wait" and rest:
                ok = sh.wait_for(rest, 30)
                self._add({"wait_for": rest, **({} if ok else {"wait_timeout": 60})})
                self.console.print("[dim]ready[/]" if ok else "[yellow]never succeeded; saved anyway[/]")
            elif word == "fake" and self.steps:
                last = self.steps[-1]
                if "recorded_output" in last:
                    last["execute"] = False
                    last["output"] = last.pop("recorded_output")
                    self.save()
                    self.console.print("[dim]last step will show its recorded output instead of running[/]")
            elif word == "pause":
                self._add({"pause": True})
            elif word == "undo" and self.steps:
                gone = self.steps.pop()
                self.save()
                self.console.print(f"[dim]removed: {gone.get('run') or gone}[/]")
            elif word == "list":
                for n, st in enumerate(self.steps, 1):
                    self.console.print(f"[dim]{n:>3}[/] {st.get('run') or st.get('say') or st}")
            else:
                self.console.print(RECORD_HELP)
            return True

        captured: List[str] = []

        def out(chunk: str) -> None:
            captured.append(chunk)
            echo(chunk)

        r = sh.run(line, on_output=out)
        text = "".join(captured)
        if text and not text.endswith("\n"):
            echo("\r\n")
        step: Dict[str, Any] = {"run": line.rstrip()}
        clean = _strip_ansi(text).strip("\n")
        if clean:
            step["recorded_output"] = clean + "\n"
        if r.exit_code != 0:
            step["expect_exit"] = r.exit_code
            self.console.print(f"[dim red]exit {r.exit_code} (saved as expected)[/]")
        self._add(step)
        return True

    def run(self) -> None:
        try:
            import readline  # noqa: F401  (line editing + history)
        except ImportError:
            pass
        self.console.print(RECORD_HELP)
        self.console.print(f"[dim]saving to {self.path}[/]\n")
        self.save()
        with Shell(self.shell_name) as sh:
            while True:
                cwd = sh.cwd()
                prompt = f"\001\x1b[1;31m\002● rec\001\x1b[0m\002 \001\x1b[1;34m\002{cwd}\001\x1b[0m\002 $ "
                try:
                    line = input(prompt)
                except EOFError:
                    print()
                    break
                except KeyboardInterrupt:
                    print()
                    continue
                if not self.handle(line, sh):
                    break
        self.save()
        self.console.print(f"[green]saved {len(self.steps)} steps to {self.path}[/]  "
                           f"[dim]next: showrun check {self.path}  ·  showrun play {self.path}[/]")
