#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hooklib — la parte comune dei due hook. Python, non shell, perche' deve girare
uguale su Windows e su macOS: una sola implementazione, nessuna copia da tenere
allineata.

=============================================================================
Costanti del progetto. Su un repo nuovo le scrive `agent_context_init.py`
rilevandole da `git ls-files`: vanno guardate, e corrette solo se ha sbagliato.
=============================================================================
"""

# ==== TARATURA DEL PROGETTO (inizio) ====
# Tutto cio' che sta fra questi due marcatori e' specifico di QUESTO repository.
# `agent_context_init.py --pack` lo sostituisce con valori neutri, e
# l'inizializzatore lo riempie rilevandolo dal repo di destinazione.

# Le directory il cui cambiamento richiede che lo stato del lavoro venga aggiornato.
CODE_PATHS = ["src", "drivers"]

# Il documento che tiene lo stato corrente del lavoro.
STATUS_FILE = "docs/context/status.md"

# La directory dei documenti di contesto, per il cruscotto dei livelli di evidenza.
CONTEXT_DIR = "docs/context"

# I livelli di evidenza, nella forma esatta in cui compaiono nei documenti.
EVIDENCE_LEVELS = ["verificato", "dedotto", "assunto"]
# ==== TARATURA DEL PROGETTO (fine) ====

# =============================================================================
# Da qui in giu' non c'e' niente di specifico del progetto.
# =============================================================================

import io
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

MARKER_RE = re.compile(r"<!--\s*context-verified-at:\s*([0-9a-f]{7,40})\s*-->")
# I marcatori devono stare DA SOLI sulla loro riga: senza le ancore di riga, la
# regex cattura anche il paragrafo che spiega i marcatori citandoli in linea.
BLOCK_RE = re.compile(
    r"^[ \t]*<!--\s*session-start:\s*begin\s*-->[ \t]*$"
    r"(.*?)"
    r"^[ \t]*<!--\s*session-start:\s*end\s*-->[ \t]*$",
    re.S | re.M)


def setup_stdout() -> None:
    """La console di Windows non e' UTF-8: senza questo, una freccia uccide l'hook."""
    try:
        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                          errors="replace")
    except Exception:
        pass


def run_git(root, *args) -> str:
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=str(root))
        return r.stdout if r.returncode == 0 else ""
    except OSError:
        return ""


def repo_root():
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
    except OSError:
        pass
    return None


def git_dir(root):
    out = run_git(root, "rev-parse", "--git-dir").strip()
    if not out:
        return None
    p = Path(out)
    return p if p.is_absolute() else (root / p)


def log(event: str, outcome: str) -> None:
    """
    Traccia su file. E' l'UNICO modo in cui l'utente puo' vedere che l'hook e'
    partito: lo stdout di SessionStart va nel contesto dell'agente, non a schermo, e
    gli hook sono fail-open, quindi senza questa riga un hook rotto e un hook assente
    sono indistinguibili. Si scrivono anche gli esiti silenziosi, per lo stesso motivo.
    """
    try:
        root = repo_root()
        if root is None:
            return
        g = git_dir(root)
        if g is None:
            return
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {event:<13} {outcome}\n"
        with open(g / "claude-hooks.log", "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass


def read_marker(status_text: str):
    m = MARKER_RE.search(status_text)
    return m.group(1) if m else None


def extract_marked(status_text: str):
    """
    Le sezioni da iniettare le dichiara il documento, con
    <!-- session-start: begin --> ... <!-- session-start: end -->.
    Cosi' l'hook non sa niente della numerazione delle sezioni, che cambia da progetto
    a progetto e drifta dentro lo stesso progetto.
    """
    return [m.group(1).strip() for m in BLOCK_RE.finditer(status_text) if m.group(1).strip()]


def count_levels(root) -> dict:
    counts = {lvl: 0 for lvl in EVIDENCE_LEVELS}
    ctx = root / CONTEXT_DIR
    if not ctx.is_dir():
        return counts
    for p in sorted(ctx.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lvl in EVIDENCE_LEVELS:
            counts[lvl] += len(re.findall(r"\*\*" + re.escape(lvl) + r"\*\*", text))
    return counts


def dirty(root, paths) -> str:
    """Modifiche non committate sotto i percorsi dati (stringa vuota = pulito)."""
    return run_git(root, "status", "--porcelain", "--", *paths).strip()
