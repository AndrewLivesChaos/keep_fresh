#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selftest — prova il plugin keep-fresh su repository finti, dall'inizio.

    python plugins/keep-fresh/tests/selftest.py

Esce 0 e stampa "self-test: OK (N passi)" solo se nessun passo fallisce; altrimenti
elenca i passi falliti ed esce 1. Non tocca niente fuori dalle cartelle temporanee che
crea. Gli script si eseguono da plugins/keep-fresh/scripts/, come li esegue un agente
che ha il plugin installato.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

PLUGIN = Path(__file__).resolve().parents[1]
REPO = PLUGIN.parents[1]
SCRIPTS = PLUGIN / "scripts"
HOOKS_SCRIPT = SCRIPTS / "agent_hooks.py"

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
           GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.autocrlf",
           GIT_CONFIG_VALUE_0="false", CLAUDE_PLUGIN_ROOT=str(PLUGIN),
           PYTHONDONTWRITEBYTECODE="1")

failures = []
passed = 0
_tmpdirs = []


def step(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
    else:
        failures.append(f"{name}" + (f"\n      {detail}" if detail else ""))


def run(*args, cwd, stdin=None, env=None):
    return subprocess.run([str(a) for a in args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          env=env or ENV, input=stdin)


def tmpdir(prefix="kf-selftest-") -> Path:
    p = Path(tempfile.mkdtemp(prefix=prefix))
    _tmpdirs.append(p)
    return p


def git_repo(with_config=True) -> Path:
    """Un repository git vuoto; con with_config ha .keep-fresh/config.toml dal modello."""
    root = tmpdir()
    run("git", "init", "-q", ".", cwd=root)
    if with_config:
        (root / ".keep-fresh").mkdir()
        shutil.copyfile(PLUGIN / "templates" / "config.toml",
                        root / ".keep-fresh" / "config.toml")
    return root


def hook_log(root: Path) -> str:
    p = root / ".git" / "agent-hooks.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ----------------------------------------------------------------------------- manifesti

def test_manifests():
    claude = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    codex = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text("utf-8"))
    step("manifesti: la versione e' la stessa per Claude Code e Codex",
         claude.get("version") == codex.get("version") == "1.0.0",
         f"claude={claude.get('version')!r} codex={codex.get('version')!r}")

    entries = []
    for rel in (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"):
        entries += json.loads((REPO / rel).read_text("utf-8")).get("plugins", [])
    step("manifesti: nessuna version nelle voci dei marketplace",
         entries and all("version" not in e for e in entries), str(entries))

    if shutil.which("claude") is None:
        print("  (saltato: claude plugin validate, claude non e' sul PATH)")
        return
    for target in (REPO, PLUGIN):
        r = run("claude", "plugin", "validate", target, cwd=REPO)
        step(f"claude plugin validate passa su {target.name}", r.returncode == 0,
             (r.stdout + r.stderr)[-600:])


def test_launcher():
    root = git_repo()
    sub = root / "a" / "b"
    sub.mkdir(parents=True)
    bash = shutil.which("bash")
    if bash is None:
        print("  (saltato: run-hook.cmd, bash non e' sul PATH)")
        return
    r = run(bash, PLUGIN / "hooks" / "run-hook.cmd", "session-start", "--agent", "prova",
            cwd=sub, stdin="{}")
    step("run-hook.cmd lancia agent_hooks da una sottocartella",
         r.returncode == 0 and "prova" in hook_log(root),
         f"exit={r.returncode} log={hook_log(root)!r} err={r.stderr[-300:]}")


# --------------------------------------------------------------------------------- main

TESTS = [test_manifests, test_launcher]


def main() -> int:
    try:
        for t in TESTS:
            try:
                t()
            except Exception as exc:
                step(f"{t.__name__}: nessuna eccezione", False,
                     f"{type(exc).__name__}: {exc}")
    finally:
        for p in _tmpdirs:
            shutil.rmtree(p, ignore_errors=True)
    if failures:
        print(f"self-test: {len(failures)} passi falliti, {passed} passati")
        for f in failures:
            print(f"  FALLITO: {f}")
        return 1
    print(f"self-test: OK ({passed} passi)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
