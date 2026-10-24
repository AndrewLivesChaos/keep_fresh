# keep-fresh

*[Italiano](README.md)* — the agent guide, the skills and the scripts' messages are in Italian.

**Project context for coding agents that stays true over time.**
A plugin for **Claude Code** and **Codex**: it organises the documentation agents read,
checks it against the code and keeps it up to date on every turn, with measured,
controlled token usage.

## The problem

A coding agent starts from scratch in every session. To work well it needs written context:
what the project is, the rules it must not break, where the work stands. That context
**goes stale silently**: the code changes, the documents do not, and the agent confidently
follows instructions that are no longer true. On top of that, context that grows unchecked
is paid for in tokens at every start.

## What keep-fresh does

- **Structures the context.** A single entry point (`AGENTS.md`) with routing tables to small,
  topical documents (`docs/keep-fresh/context/`): the agent loads only what the task needs,
  not everything. One context for every agent: Claude Code reads it through `CLAUDE.md`,
  which imports `AGENTS.md`.
- **Checks it against the code.** A documents lint verifies that the identifiers they cite
  still exist, that links resolve, that whatever is stated as verified carries the date of
  the check, and that the work state has not fallen behind the code.
- **Keeps it up to date by itself.** Three hooks: at start they put the work state in front
  of the agent; at end of turn they stop it, once, if it changed the code without updating
  the state; before a message they warn when resuming a session would be expensive.
- **Carries work across sessions.** With `/keep-fresh:handoff` the agent writes where it got
  to, its decisions and dead ends; a fresh, lighter session picks it up with
  `/keep-fresh:resume`.
- **Makes cost measurable.** `/keep-fresh:cost` reports what the context really weighs,
  session by session, telling measured numbers apart from estimates.
- **Leaves the project clean.** It writes only two starter files in the repository; the code
  lives in the plugin. A plugin update reaches every project without touching it.

## Performance and usage

| Item | Value | How it was obtained |
|---|---|---|
| Model calls made by the plugin | **none** (except `/keep-fresh:cost misura`, on request, about $0.40) | by design: hooks and lint are local Python scripts |
| Hook duration | **0.2–0.3 s** (start ~0.27 s, end of turn ~0.20 s) | measured, small repository, Windows 11, Python 3.14; grows with repository size |
| Lint duration | **~0.25 s** | measured, same conditions |
| Context injected at start | **at most 8,000 characters** (about 2,000–2,500 tokens) | configurable cap; above it, only an index of the blocks, and the lint flags it |
| Dependencies | **none** beyond Python and git | Python standard library |

Where it saves:

- **The injection cap.** In a real project, before the cap, the blocks loaded at every start
  had grown to about 134,000 characters, in the order of 60,000 tokens paid for in every
  session. With the cap a few thousand tokens remain, and the lint points at what to shorten.
- **Resuming after a pause.** Once the prompt cache has expired, the first message writes the
  whole context to the cache again instead of reading it: on Anthropic's price list a cache
  write costs 12.5 to 20 times a cache read. With a large context the hook stops the message
  once and says what it will cost; the stopped message never reaches the model and costs
  nothing. Sent again, it goes through.
- **Handoff.** Above a threshold (150,000 tokens by default) the hook suggests moving the work
  to a new session: every later call re-reads a smaller context.
- **Targeted loading.** Routing tables make the agent read only the documents of the task at
  hand.

Session costs computed by `/keep-fresh:cost` were compared with the cost Claude Code computes
itself and matched to the seventh decimal place for Opus 5.5, Opus 5, Sonnet 5 and Haiku 4.5.
For Codex the report gives tokens, not costs.

## Requirements

- git;
- Python **3.14** or later, reachable as `python` on Windows and `python3` on macOS/Linux
  (the technical minimum is 3.11);
- Claude Code or Codex.

## Install

The repository is the plugin's marketplace; install from the `master` branch.

**Claude Code**, once per configuration:

```bash
claude plugin marketplace add AndrewLivesChaos/keep_fresh
claude plugin install keep-fresh@keep-fresh
```

Claude Code tries to clone over SSH first. On a machine without an SSH key for GitHub set
`CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1`, or updates from the `/plugin` panel may fail. With several
configurations (`CLAUDE_CONFIG_DIR`) repeat the two commands for each.

**Codex:**

```bash
codex plugin marketplace add AndrewLivesChaos/keep_fresh
codex plugin add keep-fresh@keep-fresh
```

Then, inside Codex, open `/hooks` and approve the three keep-fresh hooks. **Without approval
Codex skips them silently.** Approval is per plugin, not per project.

## Getting started

1. Open the agent at the root of your git repository and run `/keep-fresh:init`
   (`$keep-fresh:init` in Codex). It does a dry run, asks for confirmation and writes the two
   starter files.
2. Init prints a prompt to paste: with it the agent reads the plugin guide, asks you what it
   cannot infer from the code and writes the context (`AGENTS.md`, `CLAUDE.md`,
   `docs/keep-fresh/context/`).
3. The agent runs the lint until it is clean. Many findings on the first run are normal: fix
   the tuning in `.keep-fresh/config.toml` first, then the documents.
4. Review and commit the context and the tuning. From then on the hooks work by themselves.
5. `/keep-fresh:status` tells you at any time whether plugin, hooks and lint are in order.

It also works in a folder just created with `git init`: in a repository with no commits init
makes an empty `Initial commit`, with no files, to have a reference point.

## Commands

| Command | What it does |
|---|---|
| `/keep-fresh:init` | prepares the current repository: dry run, confirmation, then writes the two starter files |
| `/keep-fresh:status` | read-only status: plugin, hooks, handoffs, lint, what to fix |
| `/keep-fresh:lint` | the documents lint; the agent also runs it on its own |
| `/keep-fresh:handoff` | the agent writes where you got to, to pick up in a new session (`--elenco`, `--scarta n`) |
| `/keep-fresh:resume` | picks up a handoff (`n`, a word of the title, `--comunque`) |
| `/keep-fresh:cost` | how much the context weighs (`misura`, `--giorni N`) |

In Codex the skills are invoked as `$keep-fresh:<name>`.

## How it works

### What it writes in the project

Only two files, written when missing and never overwritten:

| Path | What it is |
|---|---|
| `.keep-fresh/config.toml` | the lint tuning, edited by hand |
| `docs/keep-fresh/context/status.md` | the skeleton of the work state |

The rest of the context is written by the agent. Hooks are not wired into the project: the
plugin brings them, and where `.keep-fresh/config.toml` is missing they do nothing. In `.git/`,
so outside any commit, the plugin keeps the hooks' trace (`agent-hooks.log`) and the handoffs
(`keep-fresh-handoff/`).

### The lint

| Check | What it verifies |
|---|---|
| 0. Configuration | what counts as code |
| 1. Banned features | symbols that must not come back into the code |
| 2. Identifiers | what the documents cite still exists |
| 3. Evidence | every "verified" carries the date of the check, and conversational labels (`[Certo]`, `[Probabile]`, `[Ipotesi]`) stay out of the documents |
| 4. Links and anchors | references resolve |
| 5. Freshness | `status.md` has not fallen behind the code |
| 6. Weight | how much enters the context at every start |

### The hooks

The same for Claude Code and Codex:

- **at start** (`SessionStart`) they inject the work state from `status.md`, within the cap;
- **at end of turn** (`Stop`) they block once if the code changed and `status.md` did not;
- **before your message** (`UserPromptSubmit`) they warn, once, if resuming after a pause
  would be expensive or if the context passed the handoff threshold. They never stop a `/`
  command.

They are **fail-open**: an internal error never blocks your work. To know whether they run
there is the trace `.git/agent-hooks.log`, summarised by `/keep-fresh:status`.

### Tuning: `.keep-fresh/config.toml`

- `[code]`: `include` and `exclude` correct the automatic code detection (generated code,
  vendored libraries, folders starting with a dot).
- `[lint.*]`: the lint's exceptions. They start **empty on purpose** and are filled by looking
  at the false positives of the first run, with the reason written next to each entry.
- `[context]`: `max_injection_chars` (8000), `handoff_warn_tokens` (150,000), `handoff_ore`
  (48) and `handoff_prune_giorni` (30). If the injection cap is not enough, the fix is to
  shorten the blocks in `status.md`, not to raise it.

### Context cost: `/keep-fresh:cost`

```
/keep-fresh:cost                 report, calls no model
/keep-fresh:cost --giorni 30     recent sessions only
/keep-fresh:cost misura          exact measurement of the fixed tokens (about $0.40)
```

The report reads Claude Code transcripts and Codex token counts for the sessions opened in the
repository: calls, context at start and peak, cache writes and reads, list price. Every number
is marked **[misurato]** (measured) or **[stimato]** (estimated). `misura` runs headless Claude
Code in a throwaway copy and compares totals with and without the context; every measurement
is taken twice and must match, or it is not saved.

### Handoff

1. Above `handoff_warn_tokens` the hook stops the message once and suggests a handoff.
2. `/keep-fresh:handoff`: the agent writes goal, work done, decisions, dead ends and next step.
   Then `/clear` or a new session.
3. At start the hook shows an index of open handoffs (at most five), without loading their
   content.
4. `/keep-fresh:resume` picks up the chosen one. If it was written on another branch it says so
   and does not consume it; `--comunque` picks it up anyway.

Handoffs stay **local**, in `.git/`, and never end up in a commit.

## Update

```bash
claude plugin update keep-fresh@keep-fresh     # in every Claude Code configuration
codex plugin marketplace upgrade               # Codex
```

Or, in Claude Code, `/plugin` → *Marketplaces* → keep-fresh → *Enable auto-update*. An update
arrives when the plugin version changes. `config.toml` and `status.md` are never touched.

## Troubleshooting

- **"Non sei dentro un repository git"** (not inside a git repository): run `git init` first.
- **`.git/agent-hooks.log` stays empty**: the plugin is not installed or is disabled in that
  configuration (`/keep-fresh:status` says so); with Codex, the hooks were not approved with
  `/hooks`.
- **Nothing shows at start**: that is normal. What the start hook produces goes into the
  agent's context, not to the screen.
- **The lint reports dozens of missing identifiers on the first run**: that is normal. Fix the
  tuning first, then the documents. A finding that describes a real defect is not silenced:
  it is recorded in `status.md` as open work.

## What has been tested

- **Windows 11, Python 3.14**: the plugin self-test; the plugin installed from the marketplace
  in Claude Code 2.1.308 and Codex 0.154.0, with the hooks verified in real sessions.
- **macOS**: installation from the marketplace succeeded; hook behaviour not yet verified.
- **Linux**: not tested.
- The exact measurement in `/keep-fresh:cost` uses Claude Code only.

## Developing keep-fresh

```
.claude-plugin/marketplace.json      marketplace for Claude Code
.agents/plugins/marketplace.json     marketplace for Codex
plugins/keep-fresh/                  the plugin
  .claude-plugin/plugin.json         Claude Code manifest (version)
  .codex-plugin/plugin.json          Codex manifest (version, hook file)
  hooks/hooks.json                   hooks for Claude Code, through hooks/run-hook.cmd
  hooks/codex-hooks.json             hooks for Codex
  scripts/                           lint, hooks, handoff, cost, init
  skills/<command>/SKILL.md          one skill per command
  guide.md                           the guide the agent follows
  templates/config.toml              the starter tuning file
  tests/selftest.py                  the self-test
```

- Work happens on `develop`; `master` is what users install.
- To try a change without touching your projects: `claude --plugin-dir ./plugins/keep-fresh`
  from the repository root.
- `python plugins/keep-fresh/tests/selftest.py` must print `self-test: OK`.
- **Release**: bump the version in **both** `plugin.json` files (the self-test checks they
  match), merge into `master`, push.

## License

[MIT](LICENSE).
