# keep-fresh

*[Italiano](README.md)* — the guide, the skills and the scripts' messages are in Italian.

A plugin for coding agents (Claude Code and Codex) that sets up a git repository so agents
work in it with context that does not rot: context documents, a lint that checks they still
tell the truth, and hooks that put the state of the work in front of the agent and stop it
from ending a turn when the code changed and the state did not.

The plugin only does the mechanics. The agent writes the context, following the plugin's
guide. The code lives **only in the plugin**: a released fix reaches every project with a
plugin update, without touching them.

> **What has been tested.** On **Windows 11** with **Python 3.14**: the plugin self-test on
> throwaway repositories; the plugin installed from the marketplace in **Claude Code
> 2.1.308** and **Codex 0.154.0**, with the hooks running in real sessions (`claude -p`,
> `codex exec` after approval with `/hooks`). Not tested: macOS and Linux.

## Requirements

- git;
- Python **3.14** or later, reachable as `python` on Windows and `python3` on macOS/Linux
  (the technical minimum is 3.11, for `tomllib`);
- Claude Code or Codex.

## Install

The repository `AndrewLivesChaos/keep_fresh` is the marketplace. Users install from `master`.

**Claude Code**, once per configuration:

```powershell
claude plugin marketplace add AndrewLivesChaos/keep_fresh
claude plugin install keep-fresh@keep-fresh
```

Claude Code clones the marketplace with git and tries SSH first. On a machine without an SSH
key for GitHub set `CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1`, or updates from the `/plugin` panel
may fail. If you use several Claude Code configurations (`CLAUDE_CONFIG_DIR`), repeat the two
commands with that variable set: each configuration has its own copy.

**Codex:**

```powershell
codex plugin marketplace add AndrewLivesChaos/keep_fresh
codex plugin add keep-fresh@keep-fresh
```

Then, inside Codex, run `/hooks` and approve the three keep-fresh hooks. **Without approval
Codex skips them silently.** Approval is per plugin, not per project; according to the Codex
documentation it has to be repeated only when a release changes the plugin's hook file.

## Commands

| Command | What it does |
|---|---|
| `/keep-fresh:init` | prepares the current repository: dry run, confirmation, then writes the two seeds |
| `/keep-fresh:status` | read-only status: plugin, hooks, handoffs, lint, what to fix |
| `/keep-fresh:handoff` | the agent writes where you got to, to pick up in a new session (`--elenco`, `--scarta n`) |
| `/keep-fresh:resume` | picks up a handoff (`n`, a word of the title, `--comunque`) |
| `/keep-fresh:lint` | the documents lint; the agent also runs it on its own |
| `/keep-fresh:cost` | how much the context weighs (`misura`, `--giorni N`) |
| `/keep-fresh:migrate` | only for users of versions before 1.0.0, see below |

In Codex the skills are invoked as `$keep-fresh:<name>`.

## What it writes in the project

Only two **seeds**, written when missing and never overwritten:

| Path | What it is |
|---|---|
| `.keep-fresh/config.toml` | hand-made tuning |
| `docs/keep-fresh/context/status.md` | the skeleton of the work state |

The rest of the context (`AGENTS.md`, `CLAUDE.md`, the other files in
`docs/keep-fresh/context/`) is written by the agent following the guide. Hooks are not wired
into the project: the plugin brings them, and where `.keep-fresh/config.toml` is missing they
do nothing. Outside the tracked tree, in `.git/`, the hooks keep their trace
(`agent-hooks.log`) and the handoffs (`keep-fresh-handoff/`).

It also works in an empty folder just created with `git init`. Only the freshness marker of
`status.md` is missing, because there is no sha yet: after the first commit run
`/keep-fresh:init` again, and it adds it if the skeleton is untouched.

## Tuning: `.keep-fresh/config.toml`

The lint detects the code by itself and reports it in check 0. If it is wrong, fix it in
`[code]`: `include` for paths it must treat as code, `exclude` for paths it must not
(generated code, vendored libraries). The four `[lint.*]` tables start **empty on purpose**:
they are domain work, filled by looking at the false positives of the first lint run, with
the reason written next to each entry. `[context] max_injection_chars` caps what the start
hook injects in full from the `session-start` blocks of `status.md` (8000 by default); above
it, only an index is injected and the lint warns.

## Context cost: `/keep-fresh:cost`

The report reads Claude Code transcripts and Codex `token_count` events for the sessions
opened in this repository: calls, context at start and peak, cache writes and reads, list
price. Every number is marked **[misurato]** (measured: recorded by the agent or by the exact
measurement) or **[stimato]** (estimated: computed). `misura` runs headless Claude Code in a
throwaway copy to measure exactly how many tokens the instructions and the injection weigh
(about $0.40).

## Switching sessions without losing the thread: handoff

When the context passes `handoff_warn_tokens` (150,000 by default), the prompt hook stops the
message **once per session** and suggests `/keep-fresh:handoff`. It never stops a `/` command
or messages the agent generates itself (the end notification of a sub-agent or of a
background command, `<task-notification>`). The agent writes a file in `.git/keep-fresh-handoff/`
with goal, done, decisions, dead ends and next step; in the new session the start hook adds a
one-line index, and `/keep-fresh:resume` picks one up. Handoffs are **local** and never end up
in a commit.

## Hooks

The same for every agent (`plugins/keep-fresh/scripts/agent_hooks.py`): **at start** they inject
the work state from `status.md`; **at end of turn** they block once if the code changed and
`status.md` did not; **before your message** they stop it once after a pause longer than the
cache with a large context, or above `handoff_warn_tokens`. They are **fail-open**: an internal
error exits 0 without output, so the only way to know they run is the trace
`.git/agent-hooks.log`, summarised by `/keep-fresh:status`.

## Update

```powershell
claude plugin update keep-fresh@keep-fresh     # in every configuration
codex plugin marketplace upgrade               # Codex
```

Or enable auto-update for the marketplace in Claude Code's `/plugin` panel. An update arrives
only when the plugin version changes. `config.toml` and `status.md` are never touched.

## From versions before 1.0.0

Before 1.0.0 keep-fresh copied its scripts into every project (`.keep-fresh/scripts/`) and wired
the hooks in `.claude/settings.local.json` and `.codex/hooks.json`. Install the plugin, then run
`/keep-fresh:migrate --root <folder>`: a dry run over every project under that folder, then,
with your confirmation, it removes the copies and the old hooks and rewrites the documents'
commands. It skips projects with uncommitted changes in the files it would touch, and never
commits. Until a project is migrated, the plugin hooks step aside for its old copy.

## Developing keep-fresh

- Work happens on `develop`; `master` is what users install.
- To try a change without touching your projects: `claude --plugin-dir ./plugins/keep-fresh`
  from the repository root.
- `python plugins/keep-fresh/tests/selftest.py` must print `self-test: OK`.
- **Release**: bump the version in **both** `plugin.json` files (the self-test checks they
  match), merge into `master`, push.

## License

[MIT](LICENSE).
