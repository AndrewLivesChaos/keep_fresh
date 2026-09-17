#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SessionStart — inietta in contesto lo stato corrente del progetto.

Perche' esiste: il file di ingresso (AGENTS.md) e' caricato in automatico, ma i file
dei sottosistemi e status.md no — si aprono solo se l'agente decide di seguire il
rinvio. Questo hook toglie di mezzo quella discrezionalita' per il file piu' volatile.

Lo stdout di SessionStart entra nel contesto dell'agente, NON a schermo: l'utente non
vede niente ed e' normale. La prova che sia partito e' la riga in .git/claude-hooks.log.
Ogni riga stampata si paga in token a ogni avvio, /clear e compattazione compresi.

FAIL-OPEN: qualunque errore esce 0 e non stampa. Un hook rotto deve degradare ad
"assente", mai a "bloccante".
"""

import sys

# Importare hooklib non deve lasciare __pycache__ nel repository.
sys.dont_write_bytecode = True

from hooklib import core, log, setup_stdout

setup_stdout()


def main() -> int:
    if core is None:
        log("SessionStart", "scripts/context_core.py non trovato: niente da iniettare")
        return 0
    root = core.repo_root()
    if root is None:
        return 0

    STATUS_FILE = core.STATUS_FILE
    status_path = root / STATUS_FILE
    if not status_path.is_file():
        log("SessionStart", f"nessun {STATUS_FILE}: niente da iniettare")
        return 0

    status = status_path.read_text(encoding="utf-8", errors="replace")
    cfg, _ = core.load_config(root)
    specs, labels = core.code_scope(root, cfg)
    where = ", ".join(labels)

    out = [
        "=== Stato del progetto (iniettato da .claude/hooks/session_start.py) ===",
        f"Fonte: {STATUS_FILE}. Se agisci su qualcosa di qui sotto, rileggi il file intero.",
        "",
    ]

    # --- Le sezioni che il documento stesso dichiara volatili ---
    blocks = core.extract_marked(status)
    if blocks:
        out.append("\n\n".join(blocks))
        out.append("")
    else:
        out.append(f"({STATUS_FILE} non ha blocchi <!-- session-start: begin/end -->: "
                   f"nessuna sezione dichiarata volatile.)")
        out.append("")

    # --- Cruscotto dei livelli di evidenza ---
    levels = core.count_levels(root)
    out.append("Evidenza nei documenti di contesto: " +
               "  ".join(f"{k}={v}" for k, v in levels.items()))

    # --- Freschezza: il documento e' invecchiato rispetto al codice? ---
    sha = core.read_marker(status)
    if sha:
        ok, since = core.commits_since(root, sha, specs)
        if ok and since:
            out.append(f"ATTENZIONE: {len(since)} commit hanno toccato il codice ({where}) "
                       f"dopo {sha}, il punto a cui {STATUS_FILE} dichiara di essere "
                       f"riconciliato. Potrebbe dire cose non piu' vere.")
    elif core.head_sha(root) is not None:
        out.append(f"ATTENZIONE: {STATUS_FILE} non ha il marcatore context-verified-at: "
                   f"la sua freschezza non e' misurabile.")

    # --- Lavoro non registrato rimasto da una sessione precedente ---
    if core.dirty(root, specs) and not core.dirty(root, [STATUS_FILE]):
        out.append(f"ATTENZIONE: ci sono modifiche non committate al codice ({where}) e "
                   f"{STATUS_FILE} e' intatto. Probabile lavoro di una sessione "
                   f"precedente mai registrato: valuta se va annotato.")

    out += ["", "Verifica che i documenti dicano ancora il vero: "
                "python scripts/docs_lint.py",
            "=== fine stato del progetto ==="]

    text = "\n".join(out)
    print(text)
    log("SessionStart", f"iniettati {len(text)} caratteri "
                        f"(assunto={levels.get('assunto', 0)})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                      # fail-open, sempre
        try:
            log("SessionStart", f"ERRORE INTERNO {type(exc).__name__} "
                                f"(fail-open, nessun blocco)")
        except Exception:
            pass
        sys.exit(0)
