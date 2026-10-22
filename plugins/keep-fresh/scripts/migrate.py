#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate — porta sul plugin, in un colpo, i progetti inizializzati con il vecchio impianto.

    <python> <plugin>/scripts/migrate.py [--root DIR]            prova a vuoto: non scrive
    <python> <plugin>/scripts/migrate.py [--root DIR] --apply    scrive

Il vecchio impianto copiava gli script in ogni progetto (.keep-fresh/scripts/) e li
agganciava nei file locali degli agenti. Con il plugin il codice sta in un posto solo.
Per ogni progetto trovato sotto la radice:

  - toglie .keep-fresh/scripts/, .keep-fresh/guide.md, .keep-fresh/version.json;
  - dai file di aggancio (.claude/settings.local.json, .codex/hooks.json) toglie SOLO gli
    hook di keep-fresh; il resto resta com'era, e un file rimasto vuoto si toglie;
  - da .gitignore toglie la riga di un file di aggancio solo se toglie quel file;
  - nei documenti .md tracciati sostituisce i comandi degli script con i comandi della
    skill (/keep-fresh:lint, /keep-fresh:handoff...) e i percorsi con keep-fresh:scripts/.

Non tocca .git/ (gli handoff restano), config.toml, il resto del testo, e non committa.
Salta, dicendolo, un progetto con modifiche non committate nei file da toccare o con un
file di aggancio che non e' JSON valido. Su un progetto gia' migrato non fa niente.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import kf_init  # noqa: E402

REMOVE = (".keep-fresh/scripts", ".keep-fresh/guide.md", ".keep-fresh/version.json")
HOOK_FILES = (".claude/settings.local.json", ".codex/hooks.json")
OUR_HOOK = ".keep-fresh/scripts/agent_hooks.py"
SKIP_DIRS = {"node_modules", "__pycache__"}

INTERP = r"(?:<python>|python3?|py(?:\s+-3)?)\s+(?:\./)?"
SCRIPTS = r"\.keep-fresh/scripts/"
# Le regole, nell'ordine in cui si applicano: prima i comandi interi, poi i percorsi nudi.
REWRITES = [
    (re.compile(INTERP + SCRIPTS + r"docs_lint\.py(?:\s+--quiet)?"), "/keep-fresh:lint"),
    (re.compile(INTERP + SCRIPTS + r"context_cost\.py"), "/keep-fresh:cost"),
    (re.compile(INTERP + SCRIPTS + r'handoff\.py\s+new\b(?:\s+--title\s+"[^"]*")?'),
     "/keep-fresh:handoff"),
    (re.compile(INTERP + SCRIPTS + r"handoff\.py\s+list\b"), "/keep-fresh:handoff --elenco"),
    (re.compile(INTERP + SCRIPTS + r"handoff\.py\s+discard\b"), "/keep-fresh:handoff --scarta"),
    (re.compile(INTERP + SCRIPTS + r"handoff\.py\s+resume\b"), "/keep-fresh:resume"),
    (re.compile(INTERP + SCRIPTS + r"handoff\.py\b"), "/keep-fresh:handoff"),
    (re.compile(r"/keep-fresh handoff\b"), "/keep-fresh:handoff"),
    (re.compile(r"/keep-fresh resume\b"), "/keep-fresh:resume"),
    (re.compile(r"/keep-fresh status\b"), "/keep-fresh:status"),
    # Il comando nudo, non un pezzo di percorso (docs/keep-fresh/, skills/keep-fresh).
    (re.compile(r"(?<![\w./~-])/keep-fresh(?![:\w/.-])"), "/keep-fresh:init"),
    (re.compile(SCRIPTS + r"(\w+\.py)(?::\d+(?:-\d+)?)?"), r"keep-fresh:scripts/\1"),
    (re.compile(r"\.keep-fresh/scripts/?"), "keep-fresh:scripts/"),
    (re.compile(r"\.keep-fresh/guide\.md"), "keep-fresh:guide.md"),
]


def rewrite_text(text: str) -> tuple:
    """(testo riscritto, [(vecchia riga, nuova riga)] per ogni riga cambiata)."""
    out, changes = [], []
    for line in text.splitlines(keepends=True):
        new = line
        for rx, repl in REWRITES:
            new = rx.sub(repl, new)
        if new != line:
            changes.append((line.rstrip("\r\n"), new.rstrip("\r\n")))
        out.append(new)
    return "".join(out), changes


@dataclass
class HookEdit:
    file: str
    removed: int
    delete_file: bool


@dataclass
class Rewrite:
    file: str
    line: int
    old: str
    new: str


@dataclass
class ProjectPlan:
    removals: list = field(default_factory=list)
    hook_edits: list = field(default_factory=list)
    gitignore_lines: list = field(default_factory=list)
    rewrites: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    skip_reason: str | None = None
    # Il contenuto nuovo dei file da riscrivere: percorso relativo -> testo, o None per
    # un file di aggancio da togliere.
    contents: dict = field(default_factory=dict)

    @property
    def already_migrated(self) -> bool:
        return not (self.removals or self.hook_edits or self.gitignore_lines or self.rewrites)


def git(root: Path, *args) -> str:
    # Senza GIT_OPTIONAL_LOCKS=0, git status riscrive .git/index: la prova a vuoto non
    # sarebbe piu' di sola lettura.
    r = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    return r.stdout if r.returncode == 0 else ""


def is_keep_fresh_repo(p: Path) -> bool:
    return (p / "plugins" / "keep-fresh" / ".claude-plugin" / "plugin.json").is_file()


def is_project(p: Path) -> bool:
    return (p / ".keep-fresh" / "config.toml").is_file() or (p / ".keep-fresh" / "scripts").is_dir()


def find_projects(root: Path, max_depth: int = 4) -> list:
    """I progetti con keep-fresh sotto `root`, senza scendere dentro un progetto trovato."""
    found = []

    def walk(d: Path, depth: int):
        if is_keep_fresh_repo(d):
            return
        if is_project(d):
            found.append(d)
            return
        if depth >= max_depth:
            return
        try:
            children = sorted(c for c in d.iterdir() if c.is_dir())
        except OSError:
            return
        for c in children:
            if c.name.startswith(".") or c.name in SKIP_DIRS:
                continue
            walk(c, depth + 1)

    walk(Path(root), 0)
    return found


def _strip_hooks(cfg: dict) -> tuple:
    """(configurazione senza i nostri hook, quanti tolti). Non modifica `cfg`."""
    cfg = json.loads(json.dumps(cfg))
    hooks = cfg.get("hooks")
    removed = 0
    if isinstance(hooks, dict):
        for ev in list(hooks):
            entries = hooks[ev] if isinstance(hooks[ev], list) else []
            kept_entries = []
            for e in entries:
                hs = e.get("hooks") if isinstance(e, dict) else None
                if not isinstance(hs, list):
                    kept_entries.append(e)
                    continue
                kept = [h for h in hs
                        if not (isinstance(h, dict) and OUR_HOOK in str(h.get("command", "")))]
                removed += len(hs) - len(kept)
                if kept:
                    kept_entries.append(dict(e, hooks=kept))
            if kept_entries:
                hooks[ev] = kept_entries
            else:
                del hooks[ev]
        if not hooks:
            del cfg["hooks"]
    return cfg, removed


def plan_project(project: Path) -> ProjectPlan:
    plan = ProjectPlan()
    tracked = set(git(project, "ls-files").splitlines())

    for rel in REMOVE:
        if (project / rel).exists():
            plan.removals.append(rel)

    for rel in HOOK_FILES:
        p = project / rel
        if not p.is_file():
            continue
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            plan.skip_reason = f"{rel} non e' JSON valido: sistemalo a mano e rilancia"
            return plan
        if not isinstance(cfg, dict):
            continue
        new, removed = _strip_hooks(cfg)
        if removed:
            plan.hook_edits.append(HookEdit(rel, removed, delete_file=not new))
            plan.contents[rel] = None if not new else json.dumps(new, indent=2,
                                                                  ensure_ascii=False) + "\n"

    gone = {h.file for h in plan.hook_edits if h.delete_file}
    gi = project / ".gitignore"
    if gone and gi.is_file():
        lines = gi.read_text(encoding="utf-8").splitlines(keepends=True)
        drop = [l for l in lines if l.strip() in gone]
        if drop:
            plan.gitignore_lines = [l.strip() for l in drop]
            plan.contents[".gitignore"] = "".join(l for l in lines if l not in drop)

    for rel in sorted(t for t in tracked if t.endswith(".md") and not t.startswith(".keep-fresh/")):
        p = project / rel
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new, _ = rewrite_text(text)
        if new == text:
            if ".keep-fresh/version.json" in text:
                plan.warnings.append(f"{rel} cita .keep-fresh/version.json, che non esiste piu'")
            continue
        for n, (old_l, new_l) in enumerate(zip(text.splitlines(), new.splitlines()), 1):
            if old_l != new_l:
                plan.rewrites.append(Rewrite(rel, n, old_l, new_l))
        plan.contents[rel] = new

    for rel in sorted(t for t in tracked if t.endswith("agent_context_init.py")):
        plan.warnings.append(f"{rel} e' una copia del vecchio inizializzatore: non la tocco")

    touched = [r for r in plan.contents if r in tracked]
    touched += [t for t in tracked if any(t == r or t.startswith(r + "/") for r in plan.removals)]
    if touched:
        dirty = sorted({l[3:].strip().strip('"') for l in
                        git(project, "status", "--porcelain", "--", *touched).splitlines()
                        if l.strip()})
        if dirty:
            plan.skip_reason = f"modifiche non committate in {', '.join(dirty)}"
    return plan


def apply_plan(project: Path, plan: ProjectPlan) -> list:
    done = []
    for rel in plan.removals:
        p = project / rel
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        done.append(f"tolto {rel}")
    for rel, content in plan.contents.items():
        p = project / rel
        if content is None:
            p.unlink()
            done.append(f"tolto {rel}")
        else:
            p.write_text(content, encoding="utf-8", newline="\n")
            done.append(f"riscritto {rel}")
    return done


def describe(plan: ProjectPlan) -> list:
    out = [f"- togli {rel}" for rel in plan.removals]
    for h in plan.hook_edits:
        out.append(f"- {h.file}: tolti {h.removed} hook di keep-fresh"
                   + (", il file resta vuoto: lo tolgo" if h.delete_file else ""))
    out += [f"- .gitignore: tolgo {l}" for l in plan.gitignore_lines]
    out += [f"- {r.file}:{r.line}: {r.old.strip()} -> {r.new.strip()}" for r in plan.rewrites]
    out += [f"! {w}" for w in plan.warnings]
    return out


def default_root() -> Path:
    if sys.platform == "win32" and Path("C:/projects").is_dir():
        return Path("C:/projects")
    return Path.home() / "projects"


def main() -> int:
    ap = argparse.ArgumentParser(description="Porta sul plugin i progetti col vecchio impianto.")
    ap.add_argument("--root", type=Path, default=None,
                    help="dove cercare i progetti (default: C:\\projects su Windows, "
                         "altrimenti ~/projects)")
    ap.add_argument("--apply", action="store_true", help="scrive; senza, e' la prova a vuoto")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = (args.root or default_root()).resolve()

    print(f"keep-fresh migrate: progetti sotto {root}")
    print("PROVA A VUOTO: non scrive niente. Con --apply scrive." if not args.apply
          else "SCRIVE: nessun commit, li fai tu.")
    print("\nPlugin su questa macchina:")
    installs = kf_init.plugin_installs()
    for i in installs:
        flag, text = kf_init.describe_install(i)
        print(f"  [{flag}]  {text}")
        if not i.installed or i.enabled is False:
            print(f"  ! keep-fresh non installato in {i.config_dir}: li' i progetti migrati "
                  f"resterebbero senza hook")
    if not installs:
        print("  ! nessuna configurazione di Claude Code o di Codex trovata")

    projects = find_projects(root)
    todo = done_already = skipped = 0
    for project in projects:
        print(f"\n== {project}")
        plan = plan_project(project)
        if plan.skip_reason:
            skipped += 1
            print(f"saltato: {plan.skip_reason}")
            continue
        if plan.already_migrated:
            done_already += 1
            print("gia' migrato, niente da fare")
            for w in plan.warnings:
                print(f"! {w}")
            continue
        todo += 1
        for line in describe(plan):
            print(line)
        if args.apply:
            apply_plan(project, plan)
            print("fatto. git status:")
            for l in git(project, "status", "--short").splitlines():
                print(f"    {l}")

    verb = "migrati" if args.apply else "da migrare"
    print(f"\n{todo} {verb}, {done_already} gia' migrati, {skipped} saltati")
    return 0


if __name__ == "__main__":
    sys.exit(main())
