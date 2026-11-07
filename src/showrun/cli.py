"""Command line interface."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .model import DemoError, load_demo

app = typer.Typer(add_completion=False, no_args_is_help=True, rich_markup_mode="rich",
                  help="Scripted, keypress-driven terminal demos.")
err = Console(stderr=True)


def _vars(pairs: Optional[List[str]]) -> Dict[str, str]:
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise typer.BadParameter(f"expected KEY=VALUE, got {p!r}")
        k, v = p.split("=", 1)
        out[k.strip()] = v
    return out


def _load(path: Path, var: Optional[List[str]]):
    try:
        return load_demo(path, _vars(var))
    except DemoError as e:
        err.print(f"[red]{e}[/]")
        raise typer.Exit(2)


VarOpt = typer.Option(None, "--var", "-v", help="Override a variable: KEY=VALUE (repeatable).")


@app.command()
def play(
    demo_file: Path = typer.Argument(..., help="Demo YAML file."),
    var: Optional[List[str]] = VarOpt,
    offline: bool = typer.Option(False, "--offline", help="Replay recorded output instead of running commands."),
    fallback: bool = typer.Option(False, "--fallback", help="Run live, but if a step fails show its recorded output."),
    auto: Optional[float] = typer.Option(None, "--auto", help="Advance by itself every N seconds."),
    start: int = typer.Option(1, "--start", "-s", help="Start at step N (hidden steps before it are skipped)."),
    cast: Optional[Path] = typer.Option(None, "--cast", help="Also record the session to an asciinema .cast file."),
    speed: float = typer.Option(1.0, "--speed", help="Typing speed multiplier (2 = twice as fast)."),
    notes: bool = typer.Option(True, "--notes/--no-notes", help="Publish position for `showrun notes`."),
):
    """Present a demo. Enter advances; press ? during the demo for all keys."""
    from .cast import CastTee
    from .keys import AutoKeys, TerminalKeys
    from .notes import default_notes_path
    from .player import Player

    demo = _load(demo_file, var)
    if speed > 0:
        demo.settings.typing_speed /= speed
    if not sys.stdin.isatty():
        err.print("[red]play needs an interactive terminal (try `showrun check` for unattended runs)[/]")
        raise typer.Exit(2)

    tee = CastTee(sys.stdout, str(cast), demo.title) if cast else None
    console = Console(file=tee, highlight=False, force_terminal=True) if tee else Console(highlight=False)
    keys = TerminalKeys()
    if auto is not None:
        keys = AutoKeys(auto, inner=keys)
    on_step = (lambda i, st: tee.marker(st.label())) if tee else None
    player = Player(demo, console=console, keys=keys, offline=offline, fallback=fallback, start_at=start,
                    notes_path=default_notes_path(str(demo_file)) if notes else None, on_step=on_step)
    try:
        failures = player.play()
    finally:
        if tee:
            tee.close()
            err.print(f"[dim]recorded {cast} — play it back with: showrun replay {cast}[/]")
    raise typer.Exit(1 if failures else 0)


@app.command()
def check(
    demo_file: Path = typer.Argument(..., help="Demo YAML file."),
    var: Optional[List[str]] = VarOpt,
    fail_fast: bool = typer.Option(False, "--fail-fast", "-x", help="Stop at the first failing step."),
):
    """Rehearse: run every step unattended and report failures (great in CI)."""
    from .check import rehearse, report

    demo = _load(demo_file, var)
    ok = report(rehearse(demo, stop_on_fail=fail_fast), Console())
    raise typer.Exit(0 if ok else 1)


@app.command()
def record(
    demo_file: Path = typer.Argument(..., help="YAML file to write."),
    title: Optional[str] = typer.Option(None, "--title", "-t"),
    shell: str = typer.Option("bash", "--shell"),
    append: bool = typer.Option(False, "--append", "-a", help="Add steps to an existing file."),
):
    """Do the demo once in a shell; every command (and its output) becomes a step."""
    from .record import Recorder

    if demo_file.exists() and not append:
        if not typer.confirm(f"{demo_file} exists. Overwrite?"):
            raise typer.Exit(1)
    Recorder(str(demo_file), title=title, shell=shell, append=append).run()


@app.command()
def replay(
    cast_file: Path = typer.Argument(..., help="asciinema v2 .cast file."),
    speed: float = typer.Option(1.0, "--speed", help="Playback speed multiplier."),
    max_idle: float = typer.Option(1.0, "--max-idle", help="Cap pauses at this many seconds (0 = no cap)."),
):
    """Play back a recorded .cast session in the terminal."""
    from .cast import replay as do_replay

    try:
        do_replay(str(cast_file), speed=speed, max_idle=max_idle or None)
    except (ValueError, FileNotFoundError) as e:
        err.print(f"[red]{e}[/]")
        raise typer.Exit(2)
    except KeyboardInterrupt:
        pass
    sys.stdout.write("\x1b[0m\n")


@app.command()
def notes(demo_file: Path = typer.Argument(..., help="The demo being presented.")):
    """Presenter view: run in a second terminal to see the current step, notes and what's next."""
    from .notes import default_notes_path, watch

    try:
        watch(default_notes_path(str(demo_file)))
    except KeyboardInterrupt:
        pass


@app.command()
def export(
    demo_file: Path = typer.Argument(...),
    var: Optional[List[str]] = VarOpt,
    fmt: str = typer.Option("md", "--format", "-f", help="md (runbook) or sh (plain script)."),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
    include_hidden: bool = typer.Option(False, "--include-hidden"),
):
    """Export as a Markdown runbook or a plain shell script."""
    from .export import to_markdown, to_script

    demo = _load(demo_file, var)
    if fmt == "md":
        text = to_markdown(demo, include_hidden=include_hidden)
    elif fmt == "sh":
        text = to_script(demo)
    else:
        raise typer.BadParameter("format must be md or sh")
    if output:
        output.write_text(text)
        err.print(f"[green]wrote {output}[/]")
    else:
        sys.stdout.write(text)


@app.command()
def validate(demo_file: Path = typer.Argument(...), var: Optional[List[str]] = VarOpt):
    """Check the file parses and list its steps."""
    demo = _load(demo_file, var)
    t = Table(title=demo.title or str(demo_file), header_style="bold")
    for col in ("#", "kind", "step"):
        t.add_column(col)
    for n, st in enumerate(demo.steps, 1):
        kind = ("hidden" if st.hidden else "bg" if st.background else "canned" if not st.execute
                else "run" if st.run else "wait" if st.wait_for else "say" if st.say else "pause")
        t.add_row(str(n), kind, st.label())
    Console().print(t)
    Console().print(f"[green]ok[/] — {len(demo.steps)} steps, {len(demo.setup)} setup, {len(demo.cleanup)} cleanup")


@app.command()
def init(path: Path = typer.Argument(Path("demo.yaml"))):
    """Write a starter demo file that shows off the features."""
    from importlib.resources import files

    if path.exists():
        err.print(f"[red]{path} already exists[/]")
        raise typer.Exit(1)
    path.write_text(files("showrun").joinpath("starter.yaml").read_text())
    err.print(f"[green]wrote {path}[/] — try: showrun check {path} && showrun play {path}")


@app.command()
def version():
    """Print the version."""
    print(__version__)


if __name__ == "__main__":  # pragma: no cover
    app()
