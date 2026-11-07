"""Demo script format: YAML -> validated pydantic models."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

VAR_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class DemoError(Exception):
    """Raised for invalid demo files."""


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = "[bold green]demo[/] [bold blue]{cwd}[/] [bold]$[/] "
    typing_speed: float = Field(0.04, ge=0, description="Seconds per character.")
    jitter: float = Field(0.5, ge=0, le=1, description="Random +/- fraction of typing_speed.")
    wait_before_typing: bool = False
    shell: str = "bash"
    cwd: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict)
    syntax_highlight: bool = True
    theme: str = "monokai"
    typo_rate: float = Field(0.0, ge=0, le=0.3, description="Chance per letter of a fake typo.")
    timeout: Optional[float] = Field(None, gt=0, description="Default per-step timeout (s).")
    highlight_style: str = "bold black on yellow"


class Step(BaseModel):
    """One demo step.

    Kinds of step:
      - run a command shown to the audience (default)
      - run a command silently (hidden: true)
      - show a command and canned output without running it (execute: false + output)
      - narration only (say without run)
      - pause until a keypress (pause: true)
    """

    model_config = ConfigDict(extra="forbid")

    run: Optional[str] = None
    say: Optional[str] = None
    hidden: bool = False
    type: bool = True
    wait: bool = True
    execute: bool = True
    output: Optional[str] = None
    expect_exit: Union[int, str] = 0  # int, or "any"
    timeout: Optional[float] = Field(None, gt=0)
    speed: Optional[float] = Field(None, ge=0)
    clear: bool = False
    pause: bool = False
    title: Optional[str] = None
    notes: Optional[str] = None            # presenter-only notes
    typos: Optional[bool] = None           # override settings.typo_rate on/off
    highlight: List[str] = Field(default_factory=list)  # regexes to highlight in output
    expect_output: Optional[str] = None    # regex checked in rehearsal (and flagged live)
    background: bool = False               # start command in background (servers etc.)
    wait_for: Optional[str] = None         # poll until this command exits 0
    wait_timeout: float = Field(30, gt=0)
    recorded_output: Optional[str] = None  # captured by `showrun record`; used by --offline

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("highlight"), str):
            data = dict(data)
            data["highlight"] = [data["highlight"]]
        return data

    @model_validator(mode="after")
    def _check(self) -> "Step":
        if not (self.run or self.say or self.pause or self.clear or self.title or self.wait_for):
            raise ValueError("step needs at least one of: run, say, pause, clear, title, wait_for")
        if self.background and not self.run:
            raise ValueError("background steps need a 'run' command")
        if self.background and self.output is not None:
            raise ValueError("background steps can't have canned output")
        for pat in self.highlight + ([self.expect_output] if self.expect_output else []):
            try:
                re.compile(pat)
            except re.error as e:
                raise ValueError(f"bad regex {pat!r}: {e}")
        if isinstance(self.expect_exit, str) and self.expect_exit != "any":
            raise ValueError("expect_exit must be an integer or 'any'")
        if self.output is not None and self.execute:
            raise ValueError("'output' (canned output) requires execute: false")
        if self.hidden and not self.run:
            raise ValueError("hidden steps need a 'run' command")
        return self

    @property
    def visible(self) -> bool:
        return not self.hidden

    def exit_ok(self, code: int) -> bool:
        return self.expect_exit == "any" or code == self.expect_exit

    def label(self) -> str:
        if self.title:
            return self.title
        if self.run:
            first = self.run.strip().splitlines()[0]
            return first if len(first) <= 60 else first[:57] + "..."
        if self.say:
            return "say: " + self.say.strip().splitlines()[0][:50]
        return "pause"


class Demo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None
    settings: Settings = Field(default_factory=Settings)
    vars: Dict[str, Any] = Field(default_factory=dict)
    setup: List[str] = Field(default_factory=list)
    cleanup: List[str] = Field(default_factory=list)
    steps: List[Step]

    @model_validator(mode="before")
    @classmethod
    def _normalise_steps(cls, data: Any) -> Any:
        # Allow plain strings as shorthand for {run: "..."}.
        if isinstance(data, dict) and isinstance(data.get("steps"), list):
            data = dict(data)
            data["steps"] = [{"run": s} if isinstance(s, str) else s for s in data["steps"]]
        return data


def substitute(text: str, variables: Dict[str, Any]) -> str:
    def repl(m: re.Match) -> str:
        name = m.group(1)
        # Unknown names are left alone so Go/Jinja templates in commands
        # (e.g. docker --format '{{ json . }}') pass through untouched.
        return str(variables[name]) if name in variables else m.group(0)

    return VAR_PATTERN.sub(repl, text)


def _sub_all(obj: Any, variables: Dict[str, Any]) -> Any:
    if isinstance(obj, str):
        return substitute(obj, variables)
    if isinstance(obj, list):
        return [_sub_all(x, variables) for x in obj]
    if isinstance(obj, dict):
        return {k: _sub_all(v, variables) for k, v in obj.items()}
    return obj


def parse_demo(text: str, overrides: Optional[Dict[str, str]] = None, base_dir: Optional[Path] = None) -> Demo:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise DemoError(f"YAML error: {e}") from e
    if not isinstance(raw, dict):
        raise DemoError("demo file must be a mapping with a 'steps' list")

    # Resolve variables: file defaults < SHOWRUN_VAR_<NAME> env < CLI overrides.
    variables: Dict[str, Any] = dict(raw.get("vars") or {})
    for key in list(variables):
        env_val = os.environ.get(f"SHOWRUN_VAR_{key.upper()}")
        if env_val is not None:
            variables[key] = env_val
    variables.update(overrides or {})
    raw["vars"] = variables

    for section in ("steps", "setup", "cleanup", "settings", "title"):
        if section in raw:
            raw[section] = _sub_all(raw[section], variables)

    try:
        demo = Demo.model_validate(raw)
    except ValidationError as e:
        raise DemoError(_format_validation(e)) from e

    if base_dir is not None:
        cwd = demo.settings.cwd
        demo.settings.cwd = str((base_dir / os.path.expanduser(cwd)).resolve()) if cwd else str(base_dir.resolve())
    return demo


def load_demo(path: Union[str, Path], overrides: Optional[Dict[str, str]] = None) -> Demo:
    p = Path(path)
    if not p.exists():
        raise DemoError(f"file not found: {p}")
    return parse_demo(p.read_text(), overrides, base_dir=p.parent)


def _format_validation(e: ValidationError) -> str:
    lines = ["invalid demo file:"]
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"])
        lines.append(f"  {loc or '<root>'}: {err['msg']}")
    return "\n".join(lines)
