"""A persistent shell session driven through a pty.

All steps run in the same shell process, so `cd`, `export`, functions and
aliases carry over between steps.  Completion of each command is detected by
a random sentinel printed together with the command's exit status.
"""

from __future__ import annotations

import os
import re
import secrets
import shlex
import shutil
import tempfile
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

import pexpect


@dataclass
class Result:
    exit_code: int
    output: str
    duration: float
    timed_out: bool = False
    interrupted: bool = False


class ShellError(Exception):
    pass


def _kill_tree(pid: int) -> None:
    """Terminate *pid* and its descendants (background groups run in a subshell)."""
    import subprocess

    try:
        kids = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout.split()
    except FileNotFoundError:
        kids = []
    for kid in kids:
        _kill_tree(int(kid))
    try:
        os.kill(pid, 15)
    except (ProcessLookupError, PermissionError):
        pass


class Shell:
    def __init__(
        self,
        shell: str = "bash",
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        size: Optional[tuple] = None,
    ):
        self.token = secrets.token_hex(6)
        self._marker_prefix = "__SR_" + self.token
        full_env = dict(os.environ)
        full_env.update(env or {})
        full_env.setdefault("TERM", "xterm-256color")
        # A pager (git log, man, systemctl) would wait for keys the audience never sends.
        # The demo's own settings.env can still choose a pager.
        for var in ("PAGER", "GIT_PAGER", "SYSTEMD_PAGER"):
            if var not in (env or {}):
                full_env[var] = "cat"
        # Keep users' rc files out of the way; demos should be reproducible.
        full_env["PS1"] = ""
        full_env["PS2"] = ""
        full_env.pop("PROMPT_COMMAND", None)

        args = ["--norc", "--noprofile"] if os.path.basename(shell) == "bash" else []
        if os.path.basename(shell) == "zsh":
            args = ["-f"]
        cols, rows = size or shutil.get_terminal_size((100, 30))
        try:
            self.child = pexpect.spawn(
                shell, args, cwd=cwd, env=full_env, encoding="utf-8",
                codec_errors="replace", dimensions=(rows, cols), echo=False,
            )
        except pexpect.ExceptionPexpect as e:
            raise ShellError(f"could not start shell '{shell}': {e}") from e

        self._raw("stty -echo 2>/dev/null; PS1=''; PS2=''; unset PROMPT_COMMAND; set +m 2>/dev/null; bind 'set enable-bracketed-paste off' 2>/dev/null")
        self.run("true")  # sync: swallow any startup noise
        self.background: list = []  # (pid, logfile, command)

    # -- low level -----------------------------------------------------
    def _raw(self, line: str) -> None:
        self.child.sendline(line)

    def resize(self, cols: int, rows: int) -> None:
        self.child.setwinsize(rows, cols)

    @property
    def alive(self) -> bool:
        return self.child.isalive()

    # -- running -------------------------------------------------------
    def run(
        self,
        command: str,
        on_output: Optional[Callable[[str], None]] = None,
        timeout: Optional[float] = None,
    ) -> Result:
        """Run *command* to completion, streaming output to *on_output*."""
        if not self.alive:
            raise ShellError("shell has exited")
        # The status line is sent on its own line so multi-line commands work.
        # Each run gets its own marker id, so a stale marker can never end a later run.
        self._seq = getattr(self, "_seq", 0) + 1
        seq = self._seq
        marker_re = re.compile(r"\r?\n?__SR_" + self.token + "_" + str(seq) + r"_(\d+)__\r?\n")
        marker_cmd = f"printf '\\n__SR_{self.token}_{seq}_%d__\\n' \"$?\"\n"
        self.child.send(command.rstrip("\n") + "\n")
        self.child.send(marker_cmd)

        def interrupt() -> None:
            # Ctrl-C makes the tty discard typed-ahead input, including our
            # marker line, so send it again afterwards.
            self.child.sendintr()
            time.sleep(0.1)
            self.child.send(marker_cmd)

        start = time.monotonic()
        buf = ""
        emitted = []
        hold = len(self._marker_prefix) + 16  # >= full marker length
        timed_out = interrupted = False

        def emit(text: str) -> None:
            if text:
                emitted.append(text)
                if on_output:
                    on_output(text)

        while True:
            try:
                chunk = self.child.read_nonblocking(4096, timeout=0.05)
                buf += chunk
            except pexpect.TIMEOUT:
                pass
            except pexpect.EOF:
                emit(buf)
                raise ShellError("shell exited while running a command (did the step run `exit`?)")
            except KeyboardInterrupt:
                interrupt()
                interrupted = True
                continue

            m = marker_re.search(buf)
            if m:
                emit(buf[: m.start()])
                rest = buf[m.end():]
                if rest.strip():
                    emit(rest)
                code = int(m.group(1))
                break
            # Emit everything except a tail that might hold a partial marker.
            safe = len(buf) - hold
            if safe > 0:
                emit(buf[:safe])
                buf = buf[safe:]

            if timeout and not timed_out and time.monotonic() - start > timeout:
                timed_out = True
                interrupt()

        return Result(code, "".join(emitted), time.monotonic() - start, timed_out, interrupted)

    def start_background(self, command: str) -> tuple:
        """Start *command* in the background inside the session; returns (pid, logfile)."""
        log = os.path.join(tempfile.gettempdir(), f"showrun-{self.token}-bg{len(self.background)}.log")
        # A subshell keeps bash from printing job-control noise like "[1] 1234".
        out = self.capture(f"( {{ {command.rstrip().rstrip(';')}\n}} > {shlex.quote(log)} 2>&1 & echo $! )")
        try:
            pid = int(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise ShellError(f"could not start background command: {out}")
        self.background.append((pid, log, command))
        return pid, log

    def stop_background(self) -> None:
        for pid, _, _ in self.background:
            _kill_tree(pid)
        self.background.clear()

    def wait_for(self, command: str, timeout: float = 30, interval: float = 0.5) -> bool:
        """Poll *command* (silently) until it exits 0, or give up after *timeout* seconds."""
        deadline = time.monotonic() + timeout
        while True:
            if self.run(f"{{ {command}\n}} >/dev/null 2>&1", timeout=max(1.0, min(10, timeout))).exit_code == 0:
                return True
            if time.monotonic() > deadline:
                return False
            time.sleep(interval)

    def capture(self, command: str, timeout: float = 10) -> str:
        out = self.run(command, timeout=timeout).output
        return re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\r", "", out).strip()

    def cwd(self) -> str:
        path = self.capture("pwd")
        home = os.path.expanduser("~")
        if home != "/" and (path == home or path.startswith(home + "/")):
            path = "~" + path[len(home):]
        return path

    # -- live interaction -----------------------------------------------
    def interact(self, prompt: str = "(live) \\w $ ", escape: str = "\x1d") -> None:
        """Hand the session to the user until they press the escape key (Ctrl-])."""
        self.run(f"stty echo 2>/dev/null; PS1='{prompt}'")
        try:
            self.child.interact(escape_character=escape)
        finally:
            self.child.sendcontrol("c")  # discard any half-typed line
            time.sleep(0.05)
            self._raw("stty -echo 2>/dev/null; PS1=''")
            self.run("true")

    def close(self) -> None:
        self.stop_background()
        if self.alive:
            try:
                self._raw("exit")
                self.child.expect(pexpect.EOF, timeout=2)
            except Exception:
                pass
            self.child.close(force=True)

    def __enter__(self) -> "Shell":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
