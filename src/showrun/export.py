"""Export a demo as a Markdown runbook or a plain shell script."""

from __future__ import annotations

from typing import List

from .model import Demo
from .player import _strip_ansi


def to_markdown(demo: Demo, include_hidden: bool = False, include_output: bool = True) -> str:
    out: List[str] = [f"# {demo.title or 'Demo'}", ""]
    if demo.setup and include_hidden:
        out += ["## Setup", "", "```bash", *demo.setup, "```", ""]
    for step in demo.steps:
        if step.hidden and not include_hidden:
            continue
        if step.title:
            out += [f"## {step.title}", ""]
        if step.say:
            out += [step.say.strip(), ""]
        if step.run:
            label = " (hidden)" if step.hidden else (" (background)" if step.background else "")
            if label:
                out.append(f"*{label.strip(' ()')}:*")
            out += ["```bash", step.run.rstrip(), "```", ""]
            sample = step.output if not step.execute else step.recorded_output
            if include_output and sample:
                out += ["```text", _strip_ansi(sample).rstrip(), "```", ""]
        if step.wait_for:
            out += [f"_Wait until `{step.wait_for}` succeeds._", ""]
    if demo.cleanup and include_hidden:
        out += ["## Cleanup", "", "```bash", *demo.cleanup, "```", ""]
    return "\n".join(out).rstrip() + "\n"


def to_script(demo: Demo) -> str:
    out = ["#!/usr/bin/env bash", f"# {demo.title or 'demo'} — exported by showrun", "set -e", ""]
    for cmd in demo.setup:
        out.append(cmd)
    for step in demo.steps:
        if step.say:
            out += ["", "# " + step.say.strip().replace("\n", "\n# ")]
        if step.run and step.execute:
            out.append(step.run.rstrip() + (" &" if step.background else ""))
        if step.wait_for:
            out.append(f"until {step.wait_for} >/dev/null 2>&1; do sleep 0.5; done")
    if demo.cleanup:
        out += ["", "# cleanup", *demo.cleanup]
    return "\n".join(out) + "\n"
