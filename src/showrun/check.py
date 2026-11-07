"""Rehearsal: run every step unattended and report what would break on stage."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from rich.console import Console
from rich.table import Table

from .model import Demo
from .player import _strip_ansi
from .shell import Shell


@dataclass
class CheckResult:
    n: int
    label: str
    status: str  # ok | fail | skip
    detail: str = ""
    duration: float = 0.0


def rehearse(demo: Demo, shell: Optional[Shell] = None, stop_on_fail: bool = False) -> List[CheckResult]:
    s = demo.settings
    sh = shell or Shell(s.shell, cwd=s.cwd, env=s.env)
    results: List[CheckResult] = []
    try:
        for cmd in demo.setup:
            r = sh.run(cmd, timeout=s.timeout)
            if r.exit_code != 0:
                results.append(CheckResult(0, f"setup: {cmd}", "fail", f"exit {r.exit_code}"))
        for n, step in enumerate(demo.steps, 1):
            label = step.label()
            if step.run and not step.execute:
                results.append(CheckResult(n, label, "skip", "canned output"))
                continue
            if not step.run and not step.wait_for:
                continue
            problems = []
            dur = 0.0
            if step.run and step.background:
                pid, log = sh.start_background(step.run)
            elif step.run:
                r = sh.run(step.run, timeout=step.timeout or s.timeout)
                dur = r.duration
                if r.timed_out:
                    problems.append(f"timed out after {step.timeout or s.timeout}s")
                elif not step.exit_ok(r.exit_code):
                    problems.append(f"exit {r.exit_code} (expected {step.expect_exit})")
                if step.expect_output and not re.search(step.expect_output, _strip_ansi(r.output), re.M):
                    problems.append(f"output missing /{step.expect_output}/")
                if problems:
                    tail = _strip_ansi(r.output).strip().splitlines()[-3:]
                    if tail:
                        problems.append("… " + " | ".join(tail))
            if step.wait_for and not sh.wait_for(step.wait_for, step.wait_timeout):
                problems.append(f"wait_for failed: {step.wait_for}")
            results.append(CheckResult(n, label, "fail" if problems else "ok", "; ".join(problems), dur))
            if problems and stop_on_fail:
                break
    finally:
        for cmd in demo.cleanup:
            try:
                sh.run(cmd, timeout=30)
            except Exception:
                pass
        if shell is None:
            sh.close()
    return results


def report(results: List[CheckResult], console: Console) -> bool:
    t = Table(title="rehearsal", header_style="bold")
    t.add_column("#", justify="right")
    t.add_column("step")
    t.add_column("result")
    t.add_column("time", justify="right")
    t.add_column("detail", overflow="fold")
    icons = {"ok": "[green]✓ ok[/]", "fail": "[red]✗ fail[/]", "skip": "[dim]– skip[/]"}
    for r in results:
        t.add_row(str(r.n or "-"), r.label, icons[r.status],
                  f"{r.duration:.1f}s" if r.duration else "", r.detail)
    console.print(t)
    fails = sum(r.status == "fail" for r in results)
    slow = sorted((r for r in results if r.duration > 5), key=lambda r: -r.duration)[:3]
    if slow:
        console.print("[yellow]slow steps (consider execute: false + output):[/] "
                      + ", ".join(f"#{r.n} {r.duration:.0f}s" for r in slow))
    total = sum(r.duration for r in results)
    console.print(("[bold green]all good[/]" if not fails else f"[bold red]{fails} failing step(s)[/]")
                  + f"  [dim](command time {total:.1f}s)[/]")
    return fails == 0
