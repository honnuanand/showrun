import io
import json
import re

import pytest
from rich.console import Console

from showrun.cast import CastTee, replay
from showrun.check import rehearse
from showrun.export import to_markdown, to_script
from showrun.keys import ScriptedKeys
from showrun.model import DemoError, parse_demo
from showrun.player import Player
from showrun.record import Recorder
from showrun.shell import Shell

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\r")


def plain(s):
    return ANSI.sub("", s)


def demo(yaml_text, **vars):
    return parse_demo(yaml_text, vars)


def play(d, keys=(), **kw):
    buf = io.StringIO()
    console = Console(file=buf, width=100, force_terminal=True, color_system="truecolor")
    p = Player(d, console=console, keys=ScriptedKeys(list(keys)), sleep=lambda s: None, **kw)
    fails = p.play()
    return plain(buf.getvalue()), p, fails


# ---------------------------------------------------------------- model
def test_shorthand_vars_and_validation():
    d = demo("vars: {name: world}\nsteps:\n  - echo hello {{name}}\n  - run: echo '{{ json . }}'\n", name="there")
    assert d.steps[0].run == "echo hello there"
    assert d.steps[1].run == "echo '{{ json . }}'"  # unknown names pass through


@pytest.mark.parametrize("bad", [
    "steps: [{hidden: true}]",
    "steps: [{run: ls, output: x}]",           # canned output needs execute: false
    "steps: [{run: ls, expect_exit: maybe}]",
    "steps: [{run: ls, highlight: '('}]",
    "steps: [{run: ls, bogus: 1}]",
    "- not a mapping",
])
def test_invalid(bad):
    with pytest.raises(DemoError):
        parse_demo(bad)


# ---------------------------------------------------------------- shell
def test_shell_state_persists_and_exit_codes():
    with Shell() as sh:
        sh.run("cd /tmp && export FOO=bar")
        assert sh.capture("pwd") == "/tmp"
        assert sh.capture("echo $FOO") == "bar"
        assert sh.run("(exit 3)").exit_code == 3
        r = sh.run("for i in 1 2 3; do echo line$i; done")
        assert plain(r.output).split() == ["line1", "line2", "line3"]


def test_shell_timeout_and_background():
    with Shell() as sh:
        r = sh.run("sleep 5", timeout=0.5)
        assert r.timed_out
        pid, log = sh.start_background("echo started; sleep 30")
        assert sh.wait_for(f"grep -q started {log}", timeout=5)
        assert not sh.wait_for("false", timeout=0.3, interval=0.1)


# ---------------------------------------------------------------- player
def test_play_hidden_visible_canned():
    d = demo("""
steps:
  - run: export SECRET=xyz
    hidden: true
  - say: watch this
    wait: false
  - run: echo "value=$SECRET"
  - run: kubectl get pods
    execute: false
    output: "web-1  Running"
""")
    out, p, fails = play(d)
    assert "export SECRET" not in out
    assert "# watch this" in out
    assert "value=xyz" in out
    assert "web-1  Running" in out
    assert fails == 0


def test_skip_back_goto():
    d = demo("steps:\n  - echo one\n  - echo two\n  - echo three\n  - echo four\n")
    # run 1, skip 2, back at 3 -> run 2, at 3 jump to step 4, run 4
    out, p, _ = play(d, ["enter", "s", "b", "enter", "g", "4", "enter", "enter"])
    assert out.count("\none\n") == 1
    assert "⏭ skipped" in out and out.count("\ntwo\n") == 1
    assert "\nthree\n" not in out
    assert "\nfour\n" in out


def test_highlight_and_expectations():
    d = demo("""
steps:
  - run: printf 'ok\\nERROR boom\\n'
    highlight: ERROR
    expect_output: nothing-like-this
  - run: (exit 2)
""")
    out, p, fails = play(d)
    assert "▶ ERROR boom" in out
    assert fails == 1
    assert any("didn't match" in w for w in p.warnings)
    assert any("exited with 2" in w for w in p.warnings)


def test_offline_uses_recorded_output():
    d = demo("steps:\n  - run: definitely-not-a-command\n    recorded_output: from the recording\n")
    out, _, fails = play(d, offline=True)
    assert "from the recording" in out and fails == 0


def test_typos_still_type_correct_command():
    import random
    d = demo("settings: {typo_rate: 0.3}\nsteps:\n  - echo abcdefghij\n")
    out, _, _ = play(d, rng=random.Random(1))
    assert "abcdefghij\n" in out


def test_notes_file(tmp_path):
    path = tmp_path / "n.json"
    d = demo("steps:\n  - run: echo a\n    notes: say hi\n  - echo b\n")
    play(d, notes_path=str(path))
    data = json.loads(path.read_text())
    assert data["state"] == "finished"


# ------------------------------------------------------- check / export
def test_rehearse_reports_failures():
    d = demo("""
steps:
  - echo fine
  - run: echo hello
    expect_output: goodbye
  - run: slow
    execute: false
    output: x
""")
    res = rehearse(d)
    assert [r.status for r in res] == ["ok", "fail", "skip"]


def test_export():
    d = demo("title: T\nsteps:\n  - {title: Part, say: Intro, run: ls}\n  - {run: secret, hidden: true}\n")
    md = to_markdown(d)
    assert "## Part" in md and "```bash\nls\n```" in md and "secret" not in md
    assert "secret" in to_script(d)


# ---------------------------------------------------------- record/cast
def test_recorder(tmp_path):
    path = tmp_path / "rec.yaml"
    rec = Recorder(str(path), console=Console(file=io.StringIO()))
    with Shell() as sh:
        for line in ["#say first", "echo hi", "#hide echo hidden", "false", "echo drop", "#undo", "#fake"]:
            rec.handle(line, sh, echo=lambda s: None)
    d = parse_demo(path.read_text())
    assert d.steps[0].say == "first" and d.steps[0].recorded_output == "hi\n"
    assert d.steps[1].hidden
    assert d.steps[2].expect_exit == 1
    assert len(d.steps) == 3


def test_cast_roundtrip(tmp_path):
    path = tmp_path / "s.cast"
    tee = CastTee(io.StringIO(), str(path), "t")
    tee.write("hello ")
    tee.marker("step")
    tee.write("world")
    tee.close()
    out = io.StringIO()
    replay(str(path), speed=100, stream=out, sleep=lambda s: None)
    assert out.getvalue() == "hello world"


def test_fallback_to_recording():
    d = demo("steps:\n  - run: exit-with-error-xyz\n    recorded_output: recorded ok\n")
    out, p, fails = play(d, fallback=True)
    assert "recorded run" in out and "recorded ok" in out and fails == 0
