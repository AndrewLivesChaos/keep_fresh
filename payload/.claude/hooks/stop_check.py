#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stop — impedisce di chiudere il turno se il codice e' cambiato e lo stato del lavoro no.

Stop scatta alla fine di OGNI risposta, non a fine sessione. E' esattamente il motivo
per cui funziona: non esiste un "momento finale" da intercettare, e chiudere il
terminale non salta nessun controllo, perche' il controllo e' gia' avvenuto a ogni
turno precedente.

Exit 2 = "prevents Claude from stopping, continues conversation", con il messaggio
preso da stderr. Blocca UNA SOLA VOLTA per sessione: poi lascia un marcatore in .git/
e tace, altrimenti diventa martellante.

FAIL-OPEN: qualunque errore esce 0. Un hook rotto non deve mai bloccare il lavoro.
"""

import json
import re
import sys

from hooklib import (
    CODE_PATHS, STATUS_FILE, dirty, git_dir, log, read_marker, repo_root,
    run_git, setup_stdout,
)

setup_stdout()

MESSAGE = """Il codice e' cambiato e {status} e' intatto.

  - {reasons}

Prima di chiudere: aggiorna {status} (difetto notato, verifica saltata, decisione
rimandata, stato del lavoro), oppure dichiara esplicitamente all'utente perche' non
serve. Se hai riconciliato il documento con il codice, riporta anche il marcatore
context-verified-at a HEAD.

Questo controllo blocca una volta sola per sessione: non ripartira'."""


def session_id() -> str:
    try:
        raw = sys.stdin.read()
    except Exception:
        return "ignota"
    if not raw:
        return "ignota"
    try:
        sid = json.loads(raw).get("session_id")
        return str(sid) if sid else "ignota"
    except Exception:
        return "ignota"


def main() -> int:
    sid = session_id()
    root = repo_root()
    if root is None:
        return 0
    g = git_dir(root)
    if g is None:
        return 0

    safe = re.sub(r"[^A-Za-z0-9_-]", "", sid) or "ignota"
    flag = g / f"docs-status-nag-{safe}.flag"
    if flag.exists():
        log("Stop", "ok (gia' segnalato in questa sessione)")
        return 0

    if dirty(root, [STATUS_FILE]):
        log("Stop", f"ok ({STATUS_FILE} gia' toccato)")
        return 0

    reasons = []

    changed = dirty(root, CODE_PATHS)
    if changed:
        files = ", ".join(re.sub(r"^\s*\S+\s+", "", l) for l in changed.splitlines())
        reasons.append(f"modifiche non committate: {files}")

    status_path = root / STATUS_FILE
    if status_path.is_file():
        sha = read_marker(status_path.read_text(encoding="utf-8", errors="replace"))
        if sha:
            since = run_git(root, "log", "--oneline", f"{sha}..HEAD", "--", *CODE_PATHS)
            if since.strip():
                n = len(since.strip().splitlines())
                reasons.append(f"{n} commit su {'/, '.join(CODE_PATHS)}/ dopo {sha}, "
                               f"il punto a cui {STATUS_FILE} dichiara di essere "
                               f"riconciliato")

    if not reasons:
        log("Stop", "ok (codice invariato dal marcatore)")
        return 0

    flag.write_text("", encoding="utf-8")
    log("Stop", "BLOCCATO: " + "; ".join(reasons))
    sys.stderr.write(MESSAGE.format(status=STATUS_FILE,
                                    reasons="\n  - ".join(reasons)) + "\n")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                      # fail-open, sempre
        try:
            log("Stop", f"ERRORE INTERNO {type(exc).__name__} (fail-open, nessun blocco)")
        except Exception:
            pass
        sys.exit(0)
