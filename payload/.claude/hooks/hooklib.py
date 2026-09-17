#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hooklib — la parte comune agli hook di Claude Code. Python, non shell, perche' deve
girare uguale su ogni sistema operativo.

Qui non c'e' niente di specifico del progetto. Dove sta il codice lo rileva
scripts/context_core.py a ogni esecuzione, lo stesso modulo che usa il lint: hook e
lint rispondono sempre allo stesso modo alla domanda "e' cambiato il codice?".

Se context_core non si trova, `core` resta None e gli hook tacciono: sono fail-open.
"""

import io
import sys
from datetime import datetime
from pathlib import Path
import subprocess


def setup_stdout() -> None:
    """La console di Windows non e' UTF-8: senza questo, una freccia uccide l'hook."""
    try:
        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                          errors="replace")
    except Exception:
        pass


def _root_via_git():
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
    except OSError:
        pass
    return None


def _load_core():
    root = _root_via_git()
    if root is None:
        return None
    # Importare context_core non deve lasciare __pycache__ nel repository.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root / "scripts"))
    try:
        import context_core
        return context_core
    except Exception:
        return None


core = _load_core()


def log(event: str, outcome: str) -> None:
    """
    Traccia su file. E' l'UNICO modo in cui l'utente puo' vedere che l'hook e'
    partito: lo stdout di SessionStart va nel contesto dell'agente, non a schermo, e
    gli hook sono fail-open, quindi senza questa riga un hook rotto e un hook assente
    sono indistinguibili. Si scrivono anche gli esiti silenziosi, per lo stesso motivo.
    """
    try:
        root = _root_via_git()
        if root is None:
            return
        g = core.git_dir(root) if core else root / ".git"
        if g is None or not g.is_dir():
            return
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {event:<13} {outcome}\n"
        with open(g / "claude-hooks.log", "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass
