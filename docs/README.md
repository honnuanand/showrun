# showrun guide

showrun turns a YAML list of shell steps into a terminal presentation you drive with
**Enter**. This guide walks through the whole workflow: write, rehearse, present, publish.
The [project README](../README.md) has the quick reference.

![A git how-to presented with showrun](media/git-undo.gif)

- [1. Install](#1-install)
- [2. Write a demo](#2-write-a-demo)
- [3. Rehearse it](#3-rehearse-it)
- [4. Present it](#4-present-it)
- [5. Record instead of writing](#5-record-instead-of-writing)
- [6. Publish replays and runbooks](#6-publish-replays-and-runbooks)
- [7. Writing CLI how-tos](#7-writing-cli-how-tos)
- [8. Let an AI agent do it (MCP)](#8-let-an-ai-agent-do-it-mcp)
- [Samples in this repo](#samples-in-this-repo)
- [Credits](#credits)

## 1. Install

```bash
pip install showrun-cli          # Python 3.9+, macOS or Linux. The command is `showrun`.
pip install 'showrun-cli[mcp]'   # adds the MCP server for AI agents (Python 3.10+)
```

## 2. Write a demo

`showrun init demo.yaml` writes a starter file. A demo is a title, optional settings, and a
list of steps. A plain string is a command to run:

```yaml
title: Hello showrun
steps:
  - echo "hello"
  - title: A section heading
    say: Narration appears as a comment before the command.
    run: ls -la
    highlight: ["\\.yaml$"]
```

The kinds of step:

| You want to… | Write |
|---|---|
| run a command the audience sees | `- ls` or `run: ls` |
| run something silently (log in, cd, export) | `run: …` + `hidden: true` |
| show a command without running it | `run: …` + `execute: false` + `output: …` |
| start a server and wait until it's up | `run: …` + `background: true` + `wait_for: curl -sf …` |
| talk without a command | `say: …` |
| stop until you press Enter | `pause: true` |
| show a big heredoc instantly | `type: false` |

Every step runs in **one persistent shell**, so `cd`, `export` and shell functions carry over.
`setup:` runs silently before step 1, and `cleanup:` always runs at the end, even if you quit.
Variables (`vars:`) are written `{{name}}` and can be overridden with `-v name=value` or
`SHOWRUN_VAR_NAME`.

Pagers (`git log`, `man`) are turned off inside the demo shell so they can't swallow your
keypresses. Set `PAGER` in `settings.env` if you really want one.

## 3. Rehearse it

```bash
showrun validate demo.yaml   # parse and list steps; runs nothing
showrun check demo.yaml      # run every step unattended
```

`check` reports each step's exit code, `expect_output` regex, timeouts and slow steps, and
exits 1 on failure. Put it in CI so a demo never breaks the night before a talk:

```yaml
# .github/workflows/demo.yml
on: [push]
jobs:
  rehearse:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install showrun-cli && showrun check demo.yaml
```

![showrun validating and rehearsing a demo](media/showrun-cli.gif)

## 4. Present it

```bash
showrun play demo.yaml            # Enter to advance, ? for keys
showrun notes demo.yaml           # in a second terminal: current step, notes, what's next, timer
```

| Key | Action |
|---|---|
| Enter / Space / → | run the typed command, or continue |
| any key while typing | finish typing instantly |
| `s` / `b` / `r` | skip / back / retype |
| `g` N Enter | jump to step N |
| `l` | list steps |
| `i` | live shell in the same session (Ctrl-] returns) |
| `q` | quit (cleanup still runs) |

Safety nets for the day:

- `--offline` shows recorded output and runs nothing that has one. Use it on bad wifi.
- `--fallback` runs live but swaps in the recording if a step fails.
- `--cast talk.cast` records the live session as you present.

![offline playback](media/offline.gif)

## 5. Record instead of writing

```bash
showrun record demo.yaml
```

Do the demo once in a real shell. Every command and its output becomes a step, and the
output is kept as `recorded_output` for `--offline` and `--fallback`. Directives start with
`#`: `#say`, `#title`, `#note`, `#hide cmd`, `#bg cmd`, `#wait cmd`, `#fake`, `#pause`,
`#undo`, `#list`, `#done`.

## 6. Publish replays and runbooks

The same YAML file produces everything you need to publish a demo:

```bash
showrun render demo.yaml -o demo.cast --delay 1.5   # unattended, no terminal needed
showrun replay demo.cast                            # play it back in a terminal
showrun export demo.yaml -f md > HOWTO.md           # Markdown runbook with sample output
showrun export demo.yaml -f sh > demo.sh            # plain bash script
```

`.cast` files are standard asciinema v2, so they play in
[asciinema-player](https://github.com/asciinema/asciinema-player) on any web page:

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/asciinema-player@3.8.0/dist/bundle/asciinema-player.css">
<div id="demo"></div>
<script src="https://cdn.jsdelivr.net/npm/asciinema-player@3.8.0/dist/bundle/asciinema-player.min.js"></script>
<script>AsciinemaPlayer.create('demo.cast', document.getElementById('demo'), { idleTimeLimit: 1.5 });</script>
```

Each step leaves a marker in the cast, so the player can jump between steps. For a GIF
(for example in a README), play the cast with [vhs](https://github.com/charmbracelet/vhs) or
convert it with [agg](https://github.com/asciinema/agg).

## 7. Writing CLI how-tos

showrun works well for "how do I do X with tool Y" content. Some habits that help:

- **Hide the setup.** Create the sandbox (a temp git repo, a sample JSON file, a local
  server) in `setup:` so the audience only sees the commands that matter.
- **One idea per step.** Put the *why* in `say:` and the *what* in `run:`.
- **Point at the result** with `highlight:` instead of saying "see that line there".
- **Assert the outcome** with `expect_output:` so `showrun check` catches a tool upgrade
  that changes the behaviour.
- **Ship three formats from one file:** the live demo, a `.cast` replay for the docs site,
  and a Markdown runbook via `export -f md`.

See [`demos/git-undo.yaml`](demos/git-undo.yaml) for a complete example.

## 8. Let an AI agent do it (MCP)

`showrun mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server, so
an agent can write, rehearse and render demos for you.

```bash
claude mcp add showrun -- showrun mcp       # Claude Code
```

```json
{ "mcpServers": { "showrun": { "command": "showrun", "args": ["mcp"] } } }
```

Tools: `demo_format`, `starter_demo`, `validate_demo`, `write_demo`, `check_demo`,
`export_demo`, `render_demo`, `read_cast`, `showrun_version`. The guide is published as
the resource `showrun://guide`. `check_demo` and `render_demo` run shell commands, so keep
your client's approval prompt on for them.

Try a prompt like: *"Write a showrun demo that teaches `jq` basics on a sample JSON file,
check it until it passes, then render it to jq.cast."*

## Samples in this repo

| Demo | Replay |
|---|---|
| [`demos/git-undo.yaml`](demos/git-undo.yaml): a git how-to | [GIF](media/git-undo.gif) · [cast](casts/git-undo.cast) |
| [`../examples/tour.yaml`](../examples/tour.yaml): every feature | [GIF](media/tour.gif) · [cast](casts/tour.cast) |
| [`demos/showrun-cli.yaml`](demos/showrun-cli.yaml): validate, check, export | [GIF](media/showrun-cli.gif) · [cast](casts/showrun-cli.cast) |
| [`../examples/recorded.yaml`](../examples/recorded.yaml) with `--offline` | [GIF](media/offline.gif) · [cast](casts/offline.cast) |

To regenerate a cast: `showrun render docs/demos/git-undo.yaml -o docs/casts/git-undo.cast --delay 1.8 --width 92 --height 26`.

## Credits

showrun is inspired by [demo-magic](https://github.com/paxtonhare/demo-magic) by Paxton
Hare. I've used demo-magic for my own talks and demos for more than a decade, and showrun
is my take on the same idea with rehearsal, recording, offline playback and presenter
notes built in. Thank you, Paxton.
