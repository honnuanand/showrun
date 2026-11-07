# showrun

Scripted, keypress-driven terminal demos. You write (or **record**) the demo once, then
present it by just hitting **Enter**: commands are typed out like a human would, run in a
real shell, and stream live output. Hidden setup, canned output, presenter notes, rehearsal,
offline playback and recordings are built in.

```bash
pip install showrun-cli     # the command is `showrun`
showrun init demo.yaml      # starter demo that shows off every feature
showrun check demo.yaml     # rehearse unattended
showrun play demo.yaml      # present it
```

## Commands

| Command | What it does |
|---|---|
| `showrun play demo.yaml` | Present. `--offline` replays recorded output, `--fallback` runs live but swaps in the recording if a step fails, `--auto 3` advances by itself, `--start 7`, `--speed 2`, `--cast talk.cast`, `-v port=9000` |
| `showrun record demo.yaml` | Do the demo once in a shell; every command and its output becomes a step |
| `showrun check demo.yaml` | Rehearsal: runs every step, checks exit codes and expected output, flags slow steps. Exit code 1 on failure, so it works in CI |
| `showrun notes demo.yaml` | Presenter view for a second terminal: current step, talking points, what's next, timer |
| `showrun replay talk.cast` | Play back a recording (`--speed 2 --max-idle 1`). Casts also work with asciinema / asciinema-player |
| `showrun export demo.yaml -f md` | Markdown runbook (`-f sh` for a plain bash script) |
| `showrun validate demo.yaml` | Parse and list steps |

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

## Development

```bash
pip install -e '.[dev]' && pytest
```
