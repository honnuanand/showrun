"""MCP server: lets AI agents write, validate, rehearse, export and render showrun demos.

Run it with `showrun mcp` (stdio). Needs the `mcp` extra: pip install 'showrun-cli[mcp]'.
Note that check_demo and render_demo run the demo's shell commands on this machine, just as
`showrun check` does, so an MCP client should ask before calling them.
"""

from __future__ import annotations

import json
import os
import re
from importlib.resources import files
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from . import __version__
from .model import Demo, DemoError, load_demo, parse_demo

INSTRUCTIONS = """\
showrun turns a YAML file of shell steps into a keypress-driven terminal presentation.
Typical agent workflow:
  1. read the format with `demo_format` (or start from `starter_demo`),
  2. write the YAML with `write_demo` (it is validated before it is saved),
  3. rehearse it with `check_demo` (runs every command and reports failures),
  4. optionally `render_demo` to produce an asciinema .cast, and `read_cast` to see it as text.
The human then presents it with `showrun play <file>` (Enter advances).
Most tools accept either `path` (a YAML file) or `yaml_text` (inline YAML)."""

server = _Server("showrun", instructions=INSTRUCTIONS)

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\r")


def _demo(path: Optional[str], yaml_text: Optional[str], variables: Optional[Dict[str, str]]) -> Demo:
    if bool(path) == bool(yaml_text):
        raise ValueError("pass exactly one of `path` or `yaml_text`")
    if path:
        return load_demo(os.path.expanduser(path), variables)
    return parse_demo(yaml_text or "", variables, base_dir=Path.cwd())


def _kind(st) -> str:
    return ("hidden" if st.hidden else "background" if st.background else "canned" if not st.execute
            else "run" if st.run else "wait" if st.wait_for else "say" if st.say else "pause")


def _steps(demo: Demo) -> List[Dict[str, Any]]:
    return [{"n": n, "kind": _kind(st), "label": st.label()} for n, st in enumerate(demo.steps, 1)]


@server.tool()
def demo_format() -> str:
    """Reference for the demo YAML format: settings, vars, setup/cleanup and every step option."""
    from .model import Settings, Step

    def fields(model) -> Dict[str, str]:
        return {name: str(f.annotation).replace("typing.", "") + (f" — {f.description}" if f.description else "")
                for name, f in model.model_fields.items()}

    return json.dumps({
        "top_level": {"title": "str", "settings": "mapping (see settings)", "vars": "mapping; use as {{name}}",
                      "setup": "list of commands run silently before step 1",
                      "cleanup": "list of commands that always run at the end", "steps": "list of steps"},
        "settings": fields(Settings),
        "step": fields(Step),
        "notes": ["A step can be a plain string, which means `run: <string>`.",
                  "execute: false + output: shows canned output without running the command.",
                  "background: true + wait_for: <cmd> starts a service and waits until <cmd> exits 0.",
                  "expect_output is a regex checked by check_demo; expect_exit may be an int or 'any'."],
        "example": files("showrun").joinpath("starter.yaml").read_text(),
    }, indent=2)


@server.tool()
def starter_demo() -> str:
    """A complete starter demo (YAML) that uses most features; a good template to edit."""
    return files("showrun").joinpath("starter.yaml").read_text()


@server.tool()
def validate_demo(path: Optional[str] = None, yaml_text: Optional[str] = None,
                  variables: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Parse a demo (from `path` or `yaml_text`) and list its steps. Runs nothing."""
    try:
        d = _demo(path, yaml_text, variables)
    except DemoError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "title": d.title, "steps": _steps(d), "setup": len(d.setup), "cleanup": len(d.cleanup)}


@server.tool()
def write_demo(path: str, yaml_text: str, overwrite: bool = False) -> Dict[str, Any]:
    """Validate `yaml_text` and save it to `path`. Refuses to replace an existing file unless overwrite=true."""
    p = Path(os.path.expanduser(path))
    if p.exists() and not overwrite:
        return {"ok": False, "error": f"{p} exists; pass overwrite=true to replace it"}
    try:
        d = parse_demo(yaml_text, base_dir=p.parent)
    except DemoError as e:
        return {"ok": False, "error": str(e)}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml_text)
    return {"ok": True, "path": str(p.resolve()), "steps": _steps(d),
            "next": f"check it with check_demo, then present with: showrun play {p}"}


@server.tool()
def check_demo(path: Optional[str] = None, yaml_text: Optional[str] = None,
               variables: Optional[Dict[str, str]] = None, fail_fast: bool = False) -> Dict[str, Any]:
    """Rehearse a demo: RUNS every command in a real shell and reports failures, timeouts and
    missing expected output (same as `showrun check`). Canned steps are skipped."""
    from .check import rehearse

    try:
        d = _demo(path, yaml_text, variables)
    except DemoError as e:
        return {"ok": False, "error": str(e)}
    results = rehearse(d, stop_on_fail=fail_fast)
    rows = [{"n": r.n, "step": r.label, "status": r.status, "seconds": round(r.duration, 2),
             **({"detail": r.detail} if r.detail else {})} for r in results]
    fails = sum(r.status == "fail" for r in results)
    return {"ok": fails == 0, "failing": fails, "results": rows}


@server.tool()
def export_demo(path: Optional[str] = None, yaml_text: Optional[str] = None, format: str = "md",
                include_hidden: bool = False, variables: Optional[Dict[str, str]] = None) -> str:
    """Export a demo as a Markdown runbook (format='md') or a plain bash script (format='sh')."""
    from .export import to_markdown, to_script

    d = _demo(path, yaml_text, variables)
    if format == "md":
        return to_markdown(d, include_hidden=include_hidden)
    if format == "sh":
        return to_script(d)
    raise ValueError("format must be 'md' or 'sh'")


@server.tool()
def render_demo(output: str, path: Optional[str] = None, yaml_text: Optional[str] = None,
                offline: bool = False, delay: float = 1.0, width: int = 100, height: int = 30,
                variables: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Present the demo unattended and save it as an asciinema v2 .cast at `output`. RUNS the
    commands unless offline=true (then recorded/canned output is shown instead)."""
    from .render import render_cast

    d = _demo(path, yaml_text, variables)
    out = Path(os.path.expanduser(output))
    out.parent.mkdir(parents=True, exist_ok=True)
    r = render_cast(d, str(out), offline=offline, delay=delay, width=width, height=height)
    return {"ok": r.failures == 0, "path": str(out.resolve()), "steps": r.steps, "failures": r.failures,
            "warnings": r.warnings, "replay": f"showrun replay {out}"}


@server.tool()
def read_cast(path: str, max_chars: int = 20000) -> str:
    """Read a .cast recording as plain text, with a `── step: … ──` line at each step marker."""
    lines = Path(os.path.expanduser(path)).read_text(encoding="utf-8").splitlines()
    out: List[str] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        _, kind, data = json.loads(line)
        if kind == "m":
            out.append(f"\n── step: {data} ──\n")
        elif kind == "o":
            out.append(_ANSI.sub("", data))
    text = "".join(out)
    return text if len(text) <= max_chars else text[:max_chars] + f"\n… ({len(text) - max_chars} more chars)"


def guide_text() -> str:
    """The project README (shipped as the package's long description)."""
    from importlib.metadata import PackageNotFoundError, metadata

    try:
        return metadata("showrun-cli").get_payload() or metadata("showrun-cli")["Description"] or ""
    except PackageNotFoundError:
        return "showrun guide: https://github.com/honnuanand/showrun#readme"


@server.resource("showrun://guide", name="showrun guide", mime_type="text/markdown",
                 description="The one-page showrun guide: commands, keys, demo format, MCP tools.")
def guide() -> str:
    return guide_text()


@server.tool()
def showrun_version() -> str:
    """The installed showrun version."""
    return __version__


def main() -> None:
    server.run()


if __name__ == "__main__":  # pragma: no cover
    main()
