# showrun

[![CI](https://github.com/honnuanand/showrun/actions/workflows/ci.yml/badge.svg)](https://github.com/honnuanand/showrun/actions/workflows/ci.yml)
[![Publish](https://github.com/honnuanand/showrun/actions/workflows/publish.yml/badge.svg)](https://github.com/honnuanand/showrun/actions/workflows/publish.yml)
[![PyPI](https://img.shields.io/pypi/v/showrun-cli)](https://pypi.org/p/showrun-cli)
[![Python](https://img.shields.io/pypi/pyversions/showrun-cli)](https://pypi.org/p/showrun-cli)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/honnuanand/showrun/blob/main/LICENSE)

Scripted, keypress-driven terminal demos. You write (or **record**) the demo once, then
present it by just hitting **Enter**: commands are typed out like a human would, run in a
real shell, and stream live output. Hidden setup, canned output, presenter notes, rehearsal,
offline playback and recordings are built in.

It's made for anyone who shows a command line to other people: conference talks, team demos,
and especially **how-tos for CLI tools**. Write the steps once, rehearse them in CI, present
them live, and publish the same file as a replay and a Markdown runbook.

**Website and live replays: [showrun.clues.apps.clue2.app](https://showrun.clues.apps.clue2.app)**

![showrun presenting a short git how-to](https://raw.githubusercontent.com/honnuanand/showrun/main/docs/media/git-undo.gif)

```bash
pip install showrun-cli     # the command is `showrun`
showrun init demo.yaml      # starter demo that shows off every feature
showrun check demo.yaml     # rehearse unattended
showrun play demo.yaml      # present it
```

## Sample replays

Each of these is a YAML file in this repo, rendered with `showrun render`. The `.cast` files
play in [asciinema-player](https://github.com/asciinema/asciinema-player) or with
`showrun replay docs/casts/<name>.cast`.

| Demo | Replay |
|---|---|
| **How-to: undo your last git commit** ([`docs/demos/git-undo.yaml`](https://github.com/honnuanand/showrun/blob/main/docs/demos/git-undo.yaml)): narration, highlights, a real git repo set up silently | [GIF](https://raw.githubusercontent.com/honnuanand/showrun/main/docs/media/git-undo.gif) · [cast](https://github.com/honnuanand/showrun/blob/main/docs/casts/git-undo.cast) |
| **The feature tour** ([`examples/tour.yaml`](https://github.com/honnuanand/showrun/blob/main/examples/tour.yaml)): shared shell state, hidden steps, a background server with `wait_for`, canned output | ![tour](https://raw.githubusercontent.com/honnuanand/showrun/main/docs/media/tour.gif) |
| **showrun rehearsing itself** ([`docs/demos/showrun-cli.yaml`](https://github.com/honnuanand/showrun/blob/main/docs/demos/showrun-cli.yaml)): `validate`, `check` and `export` | ![showrun cli](https://raw.githubusercontent.com/honnuanand/showrun/main/docs/media/showrun-cli.gif) |
| **Offline playback** ([`examples/recorded.yaml`](https://github.com/honnuanand/showrun/blob/main/examples/recorded.yaml) with `--offline`): recorded output, nothing executed | ![offline](https://raw.githubusercontent.com/honnuanand/showrun/main/docs/media/offline.gif) |

The full guide, with every option and workflow, is in [docs/](https://github.com/honnuanand/showrun/blob/main/docs/README.md).

## Commands

| Command | What it does |
|---|---|
| `showrun play demo.yaml` | Present. `--offline` replays recorded output, `--fallback` runs live but swaps in the recording if a step fails, `--auto 3` advances by itself, `--start 7`, `--speed 2`, `--cast talk.cast`, `-v port=9000` |
| `showrun record demo.yaml` | Do the demo once in a shell; every command and its output becomes a step |
| `showrun check demo.yaml` | Rehearsal: runs every step, checks exit codes and expected output, flags slow steps. Exit code 1 on failure, so it works in CI |
| `showrun notes demo.yaml` | Presenter view for a second terminal: current step, talking points, what's next, timer |
| `showrun render demo.yaml -o demo.cast` | Present unattended and save an asciinema cast, no terminal needed (`--offline`, `--delay 1.5`, `--width`, `--height`). Good for docs and CI |
| `showrun replay talk.cast` | Play back a recording (`--speed 2 --max-idle 1`). Casts also work with asciinema / asciinema-player |
| `showrun export demo.yaml -f md` | Markdown runbook (`-f sh` for a plain bash script) |
| `showrun validate demo.yaml` | Parse and list steps |
| `showrun mcp` | MCP server for AI agents (see below) |

## Keys while presenting

| Key | Action |
|---|---|
| Enter / Space / → | run the typed command, or continue |
| any key while typing | finish typing instantly |
| `s` | skip this step |
| `b` / ← | back one step |
| `r` | retype the command |
| `g` + number + Enter | jump to step N |
| `l` | list all steps |
| `i` | live shell in the same session (Ctrl-] returns to the demo) |
| `?` | help |
| `q` / Ctrl-C | quit (cleanup still runs) |

## Recording

```
showrun record kafka-demo.yaml
● rec ~/work $ #title Producing events
● rec ~/work $ #say Let's start the broker first
● rec ~/work $ #bg docker compose up kafka
● rec ~/work $ #wait nc -z localhost 9092
● rec ~/work $ kcat -b localhost:9092 -L
● rec ~/work $ #note mention partitions here
● rec ~/work $ ./produce.sh 100
● rec ~/work $ #done
```

Directives: `#say`, `#title`, `#note` (attach to the next command), `#hide cmd`, `#bg cmd`,
`#wait cmd`, `#fake` (turn the last step into canned output), `#pause`, `#undo`, `#list`,
`#done`. The file is saved after every step, so nothing is lost if something crashes.

Each recorded step keeps its output in `recorded_output`, which gives you three ways to
present:

- `showrun play demo.yaml` runs everything live.
- `showrun play demo.yaml --offline` shows the recordings and runs nothing that has one
  (background services and `wait_for` are skipped). It's for bad wifi or no cluster.
- `showrun play demo.yaml --fallback` runs live, but if a step fails, times out or misses
  `expect_output`, it says so and shows the recorded run instead.

## Demo file reference

```yaml
title: My demo
settings:
  prompt: "[bold green]me@demo[/] [blue]{cwd}[/] $ "   # Rich markup; {cwd} is live
  typing_speed: 0.04      # s per char
  jitter: 0.5             # timing randomness
  typo_rate: 0.01         # occasional fake typo, corrected on screen
  wait_before_typing: false
  theme: monokai          # syntax highlighting theme
  timeout: 60             # default per-step timeout
  shell: bash             # or zsh
  cwd: ./project          # relative to the YAML file
  env: {KUBECONFIG: ./kc}
vars:                     # {{name}}; override with -v name=x or SHOWRUN_VAR_NAME
  ns: demo
setup:   [kubectl create ns {{ns}}]     # silent, before step 1
cleanup: [kubectl delete ns {{ns}}]     # always runs
steps:
  - kubectl get pods -n {{ns}}          # plain string = run it
  - run: export TOKEN=$(./get-token)
    hidden: true                        # runs silently
  - title: Deploying                    # section rule
    say: Now we roll out v2             # narration shown as a comment
    notes: Stress zero downtime         # presenter view only
    run: kubectl apply -f v2.yaml
    highlight: ["configured", "created"]  # regexes highlighted in output
    expect_output: configured           # checked by `check`, warned live
    expect_exit: 0                      # or "any"
    timeout: 30
  - run: ./server --port 8080
    background: true
    wait_for: curl -sf localhost:8080/health
    wait_timeout: 30
  - run: terraform apply                # too slow to run on stage?
    execute: false
    output: "Apply complete! Resources: 3 added"
  - run: cat big.json
    type: false                         # appears instantly
    speed: 0.01                         # per-step typing speed
    typos: false
    clear: true                         # clear screen first
  - pause: true                         # wait for Enter
```

## How it works

- **One persistent shell** (`pexpect` on a pty) runs every step, so `cd`, `export` and
  functions carry over. A unique marker after each command gives the exit code and tells
  showrun when the command has finished, without guessing at prompts.
- **Rich** draws the prompt, the syntax-highlighted typing, highlights and the notes view.
- **Recordings** are plain asciinema v2 files with a marker at each step, written by
  showrun itself, so asciinema doesn't need to be installed.
- **Background jobs** run inside the session, and their process trees are killed at the end.

## Limits

Full-screen apps (vim, top, k9s) don't stream well inside a step. Use `i` to drop into the
live shell for those. Commands that read from stdin need their input piped in.

## Use it from AI agents (MCP)

`showrun mcp` runs a [Model Context Protocol](https://modelcontextprotocol.io) server over
stdio, so an agent such as Claude Code, Claude Desktop or Cursor can write, rehearse and
render demos for you.

```bash
pip install 'showrun-cli[mcp]'                 # needs Python 3.10+
claude mcp add showrun -- showrun mcp          # Claude Code
```

There's also a hosted, read-only server at `https://showrun.clues.apps.clue2.app/mcp`. It can explain the format, validate
and export demos, and never runs commands. Use it when you don't want to install anything:

```bash
claude mcp add --transport http showrun https://showrun.clues.apps.clue2.app/mcp
```

For other clients, add the local server to the client's MCP config:

```json
{ "mcpServers": { "showrun": { "command": "showrun", "args": ["mcp"] } } }
```

| Tool | What it does |
|---|---|
| `demo_format`, `starter_demo` | The YAML format reference and a starter file to edit |
| `validate_demo` | Parse a demo (file or inline YAML) and list its steps |
| `write_demo` | Validate and save a demo; won't overwrite unless asked |
| `check_demo` | Rehearse: **runs** every command and reports failures |
| `export_demo` | Markdown runbook or bash script |
| `render_demo` | Present unattended into a `.cast` (**runs** commands unless `offline`) |
| `read_cast` | A `.cast` as plain text with step markers, so the agent can see the result |

The server also publishes the one-page guide as the resource `showrun://guide`. Ask your
agent something like *"write a showrun demo that shows how to use `jq` to filter JSON,
check it, and render it"*. `check_demo` and `render_demo` run shell commands on your
machine, so leave your client's tool approval on.

## Credits

showrun is inspired by [demo-magic](https://github.com/paxtonhare/demo-magic) by Paxton
Hare, the little bash script that types your commands for you while you talk. I've used
demo-magic for my own talks and demos for more than a decade, and showrun is my attempt at
the same idea with rehearsal, recording, offline playback and presenter notes built in.
Thank you, Paxton.

## Development

```bash
pip install -e '.[dev]' && pytest
```
