#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deploy — copia la skill keep-fresh dal repository nelle cartelle skills di Claude Code.

La skill installata e' una COPIA dei tre file che servono a chi la usa. Questo script la
tiene allineata al repository: senza, una modifica fatta qui non arriva alle copie.

    python deploy.py               # copia dove c'e' differenza
    python deploy.py --dry-run     # dice cosa farebbe, non scrive niente
    python deploy.py --check       # confronta soltanto; esce con 1 se una copia e' indietro
    python deploy.py --target DIR  # usa questa cartella skills al posto di quelle di default
                                   # (ripetibile)

Regole:
- una cartella skills che non esiste su questa macchina viene saltata, non creata;
- se la destinazione e' un collegamento (link o giunzione) si ferma: scriverci
  modificherebbe il repository stesso;
- non cancella niente: i file in piu' nella destinazione vengono solo segnalati.
"""

import argparse
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_NAME = "keep-fresh"
# Solo cio' che serve a chi usa la skill. Il payload sta gia' dentro lo script.
FILES = ("SKILL.md", "agent_context_init.py", "README.md")
# Le cartelle skills delle configurazioni di Claude Code presenti su questa macchina.
DEFAULT_SKILLS_DIRS = ("~/.claude/skills", "~/.claude-lavoro/skills")

SRC = Path(__file__).resolve().parent


def is_link(p: Path) -> bool:
    return p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())


def git_version() -> str:
    """Il commit da cui si copia, e se i file della skill hanno modifiche non committate."""
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=SRC,
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", *FILES], cwd=SRC,
                               capture_output=True, text=True, check=True).stdout.strip()
        return f"{sha}" + (" (file della skill con modifiche non committate)" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "sconosciuta (git non disponibile)"


def state(src: Path, dst: Path) -> str:
    if not dst.exists():
        return "mancante"
    return "uguale" if filecmp.cmp(src, dst, shallow=False) else "diverso"


def main() -> int:
    ap = argparse.ArgumentParser(description="Copia la skill keep-fresh nelle cartelle skills.")
    ap.add_argument("--dry-run", action="store_true", help="dice cosa farebbe")
    ap.add_argument("--check", action="store_true",
                    help="confronta soltanto; esce con 1 se una copia non e' allineata")
    ap.add_argument("--target", action="append", metavar="DIR",
                    help="cartella skills di destinazione (ripetibile)")
    args = ap.parse_args()

    missing_src = [f for f in FILES if not (SRC / f).is_file()]
    if missing_src:
        print(f"ERRORE: nel repository mancano: {', '.join(missing_src)}")
        return 1

    skills_dirs = [Path(t).expanduser() for t in (args.target or DEFAULT_SKILLS_DIRS)]
    print(f"Sorgente : {SRC}")
    print(f"Versione : {git_version()}")

    errors = 0
    behind = 0
    for skills_dir in skills_dirs:
        dest = skills_dir / SKILL_NAME
        print(f"\n{dest}")
        if not skills_dir.is_dir():
            print(f"  salto: {skills_dir} non esiste su questa macchina")
            continue
        if is_link(dest):
            print("  ERRORE: e' un collegamento. Scriverci modificherebbe il repository: "
                  "toglilo a mano (senza cancellare il contenuto) e rilancia.")
            errors += 1
            continue

        todo = []
        for f in FILES:
            st = state(SRC / f, dest / f)
            print(f"  {f:<24} {st}")
            if st != "uguale":
                todo.append(f)
        extra = sorted(p.name for p in dest.iterdir() if p.name not in FILES) if dest.is_dir() else []
        if extra:
            print(f"  file in piu' (non toccati): {', '.join(extra)}")

        if not todo:
            continue
        behind += 1
        if args.check or args.dry_run:
            continue
        dest.mkdir(exist_ok=True)
        for f in todo:
            shutil.copy2(SRC / f, dest / f)
            if state(SRC / f, dest / f) != "uguale":
                print(f"  ERRORE: {f} copiato ma diverso dalla sorgente")
                errors += 1
        print(f"  copiati: {', '.join(todo)}")

    print()
    if errors:
        print(f"Finito con {errors} errore/i.")
        return 1
    if behind and (args.check or args.dry_run):
        print(f"{behind} copia/e da allineare" + ("" if args.dry_run else ": lancia deploy.py"))
        return 1 if args.check else 0
    print("Copie allineate al repository." if not behind else "Copie aggiornate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
