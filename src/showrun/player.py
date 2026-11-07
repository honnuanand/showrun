"""The interactive presenter: types commands, waits for keys, runs steps."""

from __future__ import annotations

import random
import re
import time
from typing import Callable, List, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from . import keys as K
from .model import Demo, Step
from .notes import NotesPublisher
from .shell import Result, Shell

HELP = """\
[bold]Enter[/]  run / continue     [bold]s[/]  skip step       [bold]b[/]  back one step
[bold]r[/]      retype command     [bold]g[/]  go to step N    [bold]l[/]  list steps
[bold]i[/]      live shell (Ctrl-] returns)                     [bold]q[/]  quit
[dim]While typing, any key finishes the command instantly.[/]"""

# Neighbouring keys used for believable typos.
_NEIGHBOURS = {
    "a": "sq", "b": "vn", "c": "xv", "d": "sf", "e": "wr", "f": "dg", "g": "fh", "h": "gj",
    "i": "uo", "j": "hk", "k": "jl", "l": "k;", "m": "n,", "n": "bm", "o": "ip", "p": "o[",
    "q": "wa", "r": "et", "s": "ad", "t": "ry", "u": "yi", "v": "cb", "w": "qe", "x": "zc",
    "y": "tu", "z": "xa",
}


class Quit(Exception):
    pass


class Player:
    def __init__(
        self,
        demo: Demo,
        console: Optional[Console] = None,
        keys: Optional[K.KeySource] = None,
        shell_factory: Optional[Callable[[], Shell]] = None,
        offline: bool = False,
        fallback: bool = False,
        start_at: int = 1,
        notes_path: Optional[str] = None,
        rng: Optional[random.Random] = None,
        sleep: Callable[[float], None] = time.sleep,
        on_step: Optional[Callable[[int, Step], None]] = None,
    ):
        self.demo = demo
        self.s = demo.settings
        self.console = console or Console(highlight=False)
        self.keys = keys or K.TerminalKeys()
        self.shell_factory = shell_factory or (
            lambda: Shell(self.s.shell, cwd=self.s.cwd, env=self.s.env)
        )
        self.offline = offline
        self.fallback = fallback  # live first; on failure show the recorded output
        self.index = max(0, start_at - 1)
        self.notes = NotesPublisher(notes_path, demo)
        self.rng = rng or random.Random()
        self.sleep = sleep
        self.on_step = on_step
        self.shell: Optional[Shell] = None
        self.results: List[Optional[Result]] = [None] * len(demo.steps)
        self.warnings: List[str] = []

    # ------------------------------------------------------------------ io
    @property
    def out(self):
        return self.console.file

    def write(self, text: str) -> None:
        self.out.write(text)
        self.out.flush()

    # ----------------------------------------------------------- lifecycle
    def play(self) -> int:
        """Run the whole demo. Returns the number of steps that failed."""
        failures = 0
        with self.keys:
            self.shell = self.shell_factory()
            try:
                self.shell.resize(self.console.width, self.console.height)
            except Exception:
                pass
            try:
                for cmd in self.demo.setup:
                    r = self.shell.run(cmd)
                    if r.exit_code != 0:
                        self._warn(f"setup command failed (exit {r.exit_code}): {cmd}")
                failures = self._loop()
            except (Quit, KeyboardInterrupt):
                self.console.print("\n[dim]demo stopped.[/]")
            finally:
                try:
                    for cmd in self.demo.cleanup:
                        self.shell.run(cmd, timeout=30)
                finally:
                    self.shell.close()
                    self.notes.finish()
        return failures

    def _loop(self) -> int:
        steps = self.demo.steps
        while self.index < len(steps):
            i = self.index
            step = steps[i]
            self.notes.publish(i)
            if self.on_step:
                self.on_step(i, step)
            outcome = self._step(step)
            if outcome == "back":
                self.index = self._prev_visible(i)
            elif isinstance(outcome, int):
                self.index = outcome
            else:
                self.index = i + 1
        return sum(1 for i, r in enumerate(self.results)
                   if r is not None and not steps[i].exit_ok(r.exit_code))

    def _prev_visible(self, i: int) -> int:
        j = i - 1
        while j > 0 and self.demo.steps[j].hidden:
            j -= 1
        return max(j, 0)

    # --------------------------------------------------------------- steps
    def _step(self, step: Step):
        i = self.index
        if step.hidden:
            if step.run:
                self._execute(step, i, silent=True)
            if step.wait_for:
                self._wait_for(step, silent=True)
            return "next"

        if step.clear:
            self.console.clear()
        if step.title:
            self.console.rule(f"[bold]{step.title}")
        if step.say:
            self.console.print(Text("# " + step.say.strip().replace("\n", "\n# "), style="italic cyan"))

        if not step.run:
            if step.wait_for:
                self._wait_for(step)
            if step.pause or (step.say and step.wait):
                return self._wait_controls(step, on_enter="next")
            return "next"

        if self.s.wait_before_typing and step.wait:
            self._prompt()
            r = self._wait_controls(step, on_enter="type", show_prompt=False)
            if r != "type":
                self.write("\n")
                return r
            self._type(step)
        else:
            self._prompt()
            self._type(step)

        if step.wait:
            r = self._wait_controls(step, on_enter="run", show_prompt=False, typed=True)
            if r != "run":
                self.write("\n")
                return r
        self.write("\n")
        self._execute(step, i)
        if step.wait_for:
            self._wait_for(step)
        return "next"

    # ------------------------------------------------------------ controls
    def _wait_controls(self, step: Step, on_enter: str, show_prompt: bool = True, typed: bool = False):
        while True:
            key = self.keys.read()
            if key in (K.ENTER, "right", " ", "n"):
                return on_enter
            if key == "q":
                raise Quit()
            if key == "s":
                if typed:
                    self.write(self._dim("  ⏭ skipped"))
                return "next"
            if key in ("b", "left"):
                return "back"
            if key == "r" and step.run and typed:
                self.write("\r\x1b[2K")
                self._clear_typed(step)
                self._prompt()
                self._type(step)
                continue
            if key == "g":
                target = self._read_number()
                if target is not None:
                    return target
                self._redraw(step, typed)
                continue
            if key == "l":
                self.write("\n")
                self._list_steps()
                self._redraw(step, typed)
                continue
            if key == "i":
                self.write("\n")
                self._live_shell()
                self._redraw(step, typed)
                continue
            if key in ("?", "h"):
                self.write("\n")
                self.console.print(Panel(HELP, title="controls", border_style="blue"))
                self._redraw(step, typed)
                continue

    def _redraw(self, step: Step, typed: bool) -> None:
        if typed and step.run:
            self._prompt()
            self._type(step, instant=True)
        elif step.run and self.s.wait_before_typing:
            self._prompt()

    def _clear_typed(self, step: Step) -> None:
        # Multi-line commands occupy several rows; move up and clear them.
        extra = step.run.rstrip("\n").count("\n")
        for _ in range(extra):
            self.write("\x1b[1A\x1b[2K")
        self.write("\r")

    def _read_number(self) -> Optional[int]:
        self.write("\n" + self._dim("go to step #: "))
        digits = ""
        while True:
            k = self.keys.read()
            if k == K.ENTER:
                break
            if k == K.ESC:
                digits = ""
                break
            if k == K.BACKSPACE and digits:
                digits = digits[:-1]
                self.write("\b \b")
            elif k and k.isdigit():
                digits += k
                self.write(k)
        self.write("\n")
        if digits and 1 <= int(digits) <= len(self.demo.steps):
            return int(digits) - 1
        return None

    def _list_steps(self) -> None:
        t = Table(box=None, show_header=False, padding=(0, 1))
        for n, st in enumerate(self.demo.steps, 1):
            mark = "▶" if n - 1 == self.index else " "
            style = "dim" if st.hidden else ("bold" if n - 1 == self.index else "")
            tag = " [dim](hidden)[/]" if st.hidden else ""
            t.add_row(mark, str(n), Text(st.label(), style=style), tag)
        self.console.print(t)

    def _live_shell(self) -> None:
        self.console.print(self._dim_markup("live shell — press Ctrl-] to return to the demo"))
        with self.keys.suspend():
            self.shell.interact()
        self.write("\r\n")
        self.console.print(self._dim_markup("back to the demo"))

    # -------------------------------------------------------------- typing
    def _prompt(self) -> None:
        cwd = self.shell.cwd() if "{cwd}" in self.s.prompt else ""
        markup = self.s.prompt.replace("{cwd}", cwd.replace("[", r"\["))
        self.console.print(markup, end="")

    def _styled(self, command: str) -> Text:
        if not self.s.syntax_highlight:
            return Text(command)
        syn = Syntax(command, "bash", theme=self.s.theme, background_color="default")
        text = syn.highlight(command)
        text.rstrip()
        return text

    def _type(self, step: Step, instant: bool = False) -> None:
        text = self._styled(step.run.rstrip("\n"))
        speed = self.s.typing_speed if step.speed is None else step.speed
        typo_rate = self.s.typo_rate if step.typos is None else (step.typos and max(self.s.typo_rate, 0.03))
        if not step.type or speed == 0:
            instant = True
        plain = text.plain
        n = 0
        while n < len(plain):
            if not instant and self.keys.poll() is not None:
                instant = True  # any key = fast-forward
            if instant:
                self._print_text(text[n:])
                break
            ch = plain[n]
            if ch == "\n":
                self.write("\n")
                self.console.print("[dim]>[/] ", end="")
                n += 1
                continue
            if typo_rate and ch.isalpha() and self.rng.random() < typo_rate:
                wrong = self.rng.choice(_NEIGHBOURS.get(ch.lower(), "x"))
                self.write(wrong)
                self.sleep(speed * 4)
                self.write("\b \b")
                self.sleep(speed * 2)
            self._print_text(text[n:n + 1])
            jitter = speed * self.s.jitter
            self.sleep(max(0.0, speed + self.rng.uniform(-jitter, jitter)) * (3 if ch == " " else 1))
            n += 1

    def _print_text(self, text: Text) -> None:
        # Render continuation lines with a "> " marker.
        lines = text.split("\n", allow_blank=True)
        for k, line in enumerate(lines):
            if k:
                self.write("\n")
                self.console.print("[dim]>[/] ", end="")
            self.console.print(line, end="", soft_wrap=True, highlight=False)

    # ----------------------------------------------------------- execution
    def _canned(self, step: Step) -> Optional[str]:
        if not step.execute:
            return step.output or ""
        if self.offline and step.recorded_output is not None:
            return step.recorded_output
        return None

    def _execute(self, step: Step, i: int, silent: bool = False) -> None:
        canned = self._canned(step)
        if canned is not None:
            if not silent and canned:
                self._emit_output(step, canned.replace("\r\n", "\n").replace("\n", "\r\n"))
                if not canned.endswith("\n"):
                    self.write("\r\n")
            self.results[i] = Result(0, canned, 0.0)
            return

        if step.background and self.offline:
            self.results[i] = Result(0, "", 0.0)
            if not silent:
                self.console.print(self._dim_markup("⟳ running in background (offline: not started)"))
            return

        if step.background:
            pid, log = self.shell.start_background(step.run)
            self.results[i] = Result(0, "", 0.0)
            if not silent:
                self.console.print(self._dim_markup(f"⟳ running in background (pid {pid}, log {log})"))
            return

        timeout = step.timeout or self.s.timeout
        state = {"tail": "", "any": False}
        highlighter = _LineHighlighter(step.highlight, self.s.highlight_style, self.console) if step.highlight else None

        def on_output(chunk: str) -> None:
            if silent:
                return
            state["any"] = True
            state["tail"] = (state["tail"] + chunk)[-2:]
            if highlighter:
                highlighter.feed(chunk)
            else:
                self.write(chunk)

        res = self.shell.run(step.run, on_output=on_output, timeout=timeout)
        if highlighter:
            highlighter.flush()
        if not silent and state["any"] and not state["tail"].endswith("\n"):
            self.write("\r\n")
        self.results[i] = res

        failed = res.timed_out or not step.exit_ok(res.exit_code) or (
            step.expect_output and not re.search(step.expect_output, _strip_ansi(res.output), re.M))
        if failed and self.fallback and step.recorded_output is not None:
            if not silent:
                self.console.print(self._dim_markup("↺ live run didn't go to plan, here's the recorded run:"))
                self._emit_output(step, step.recorded_output.replace("\n", "\r\n"))
            self.warnings.append(f"step {i + 1} fell back to recorded output")
            self.results[i] = Result(0, step.recorded_output, res.duration)
            return

        if res.timed_out:
            self._warn(f"step {i + 1} timed out after {timeout}s", silent)
        elif not step.exit_ok(res.exit_code):
            self._warn(f"step {i + 1} exited with {res.exit_code}", silent)
        if step.expect_output and not re.search(step.expect_output, _strip_ansi(res.output), re.M):
            self._warn(f"step {i + 1} output didn't match /{step.expect_output}/", silent)

    def _emit_output(self, step: Step, text: str) -> None:
        if step.highlight:
            h = _LineHighlighter(step.highlight, self.s.highlight_style, self.console)
            h.feed(text)
            h.flush()
        else:
            self.write(text)

    def _wait_for(self, step: Step, silent: bool = False) -> None:
        if self.offline:
            return
        if silent:
            ok = self.shell.wait_for(step.wait_for, step.wait_timeout)
        else:
            with self.console.status(f"[dim]waiting for: {step.wait_for}[/]", spinner="dots"):
                ok = self.shell.wait_for(step.wait_for, step.wait_timeout)
        if not ok:
            self._warn(f"gave up waiting for `{step.wait_for}` after {step.wait_timeout}s", silent)

    # ------------------------------------------------------------- helpers
    def _warn(self, msg: str, silent: bool = False) -> None:
        self.warnings.append(msg)
        if not silent:
            self.console.print(f"[red dim]✗ {msg}[/]")

    @staticmethod
    def _dim(text: str) -> str:
        return f"\x1b[2m{text}\x1b[0m"

    @staticmethod
    def _dim_markup(text: str) -> str:
        return f"[dim]{text.replace('[', chr(92) + '[')}[/]"


_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\r")


def _strip_ansi(s: str) -> str:
    return _ANSI.sub("", s)


class _LineHighlighter:
    """Buffers output by line and highlights regex matches (keeps original ANSI colours)."""

    def __init__(self, patterns: List[str], style: str, console: Console):
        self.patterns = [re.compile(p) for p in patterns]
        self.style = style
        self.console = console
        self.buf = ""

    def feed(self, chunk: str) -> None:
        self.buf += chunk
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self._line(line.rstrip("\r"), newline=True)

    def flush(self) -> None:
        if self.buf:
            self._line(self.buf.rstrip("\r"), newline=False)
            self.buf = ""

    def _line(self, line: str, newline: bool) -> None:
        text = Text.from_ansi(line)
        hit = False
        for p in self.patterns:
            for m in p.finditer(text.plain):
                text.stylize(self.style, m.start(), m.end())
                hit = True
        if hit:
            marker = Text("▶ ", style="bold yellow")
            text = marker + text
        self.console.print(text, end="\r\n" if newline else "", soft_wrap=True, highlight=False)
