#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agent_hooks — il livello che esegue invece di chiedere, uguale per ogni agente.

    python scripts/agent_hooks.py session-start --agent <nome>
    python scripts/agent_hooks.py stop          --agent <nome>

Lo invoca l'agente stesso, attraverso il suo meccanismo di hook. L'aggancio e' l'unica
parte specifica dell'agente (e della macchina), e lo scrive agent_context_init.py nella
configurazione LOCALE di ciascun agente. Qui non c'e' niente di specifico di un agente:
il protocollo usato e' quello che gli agenti supportati hanno in comune.

  session-start  stampa su stdout le sezioni volatili di status.md. Lo stdout di questo
                 evento entra nel contesto dell'agente, NON a schermo: l'utente non vede
                 niente ed e' normale.
  stop           a fine turno, se il codice e' cambiato e status.md no, stampa su stdout
                 {"decision": "block", "reason": ...} ed esce 0: l'agente non chiude e
                 riceve il motivo. Blocca UNA SOLA VOLTA per sessione.

Perche' JSON e non l'uscita 2: provato il 2026-09-17 su Windows, Codex 0.154.0 tratta
l'uscita 2 di Stop come un errore e chiude comunque; la decisione JSON con uscita 0
blocca sia su Codex 0.154.0 sia su Claude Code 2.1.274.

FAIL-OPEN: qualunque errore interno esce 0 senza stampare. Un hook rotto deve degradare
ad "assente", mai a "bloccante". Per questo esiste la traccia .git/agent-hooks.log: e'
l'unico modo di sapere se gli hook girano.
"""

import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Importare context_core non deve lasciare __pycache__ nel repository.
sys.dont_write_bytecode = True

AGENT = "?"


def setup_stdout() -> None:
    """La console di Windows non e' UTF-8: senza questo, una freccia uccide l'hook."""
    try:
        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                          errors="replace")
    except Exception:
        pass


def load_core():
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import context_core
        return context_core
    except Exception:
        return None


core = load_core()


def log(event: str, outcome: str) -> None:
    """
    Una riga per esecuzione, anche per gli esiti silenziosi: un hook fail-open rotto e
    un hook assente sono altrimenti indistinguibili.
    """
    try:
        if core is None:
            return
        root = core.repo_root()
        g = core.git_dir(root) if root else None
        if g is None:
            return
        line = (f"{datetime.now():%Y-%m-%d %H:%M:%S}  {AGENT:<7} {event:<13} "
                f"{outcome}\n")
        with open(g / "agent-hooks.log", "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass


def read_input() -> dict:
    """Il JSON che l'agente passa su stdin. Malformato o assente vale come vuoto."""
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ------------------------------------------------------------------------ session-start

def session_start(data: dict) -> int:
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
        "=== Stato del progetto (iniettato da scripts/agent_hooks.py) ===",
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
                        f"(fonte={data.get('source', '?')}, "
                        f"assunto={levels.get('assunto', 0)})")
    return 0


# -------------------------------------------------------------------------------- stop

MESSAGE = """Il codice e' cambiato e {status} e' intatto.

  - {reasons}

Prima di chiudere: aggiorna {status} (difetto notato, verifica saltata, decisione
rimandata, stato del lavoro), oppure dichiara esplicitamente all'utente perche' non
serve. Se hai riconciliato il documento con il codice, riporta anche il marcatore
context-verified-at a HEAD.

Questo controllo blocca una volta sola per sessione: non ripartira'."""


def stop(data: dict) -> int:
    if core is None:
        log("Stop", "scripts/context_core.py non trovato: nessun controllo")
        return 0
    # L'agente ha gia' continuato una volta per un hook di fine turno: non si insiste.
    if data.get("stop_hook_active") is True:
        log("Stop", "ok (turno gia' prolungato da un hook)")
        return 0
    root = core.repo_root()
    if root is None:
        return 0
    g = core.git_dir(root)
    if g is None:
        return 0

    STATUS_FILE = core.STATUS_FILE
    sid = str(data.get("session_id") or "ignota")
    safe = re.sub(r"[^A-Za-z0-9_-]", "", sid) or "ignota"
    flag = g / f"docs-status-nag-{safe}.flag"
    if flag.exists():
        log("Stop", "ok (gia' segnalato in questa sessione)")
        return 0

    if core.dirty(root, [STATUS_FILE]):
        log("Stop", f"ok ({STATUS_FILE} gia' toccato)")
        return 0

    cfg, _ = core.load_config(root)
    specs, labels = core.code_scope(root, cfg)
    if not specs:
        log("Stop", "ok (nessun codice nel repository, per ora)")
        return 0
    where = ", ".join(labels)

    reasons = []
    changed = core.dirty(root, specs)
    if changed:
        files = ", ".join(re.sub(r"^\s*\S+\s+", "", l) for l in changed.splitlines())
        reasons.append(f"modifiche non committate: {files}")

    status_path = root / STATUS_FILE
    if status_path.is_file():
        sha = core.read_marker(status_path.read_text(encoding="utf-8", errors="replace"))
        if sha:
            ok, since = core.commits_since(root, sha, specs)
            if ok and since:
                reasons.append(f"{len(since)} commit sul codice ({where}) dopo {sha}, "
                               f"il punto a cui {STATUS_FILE} dichiara di essere "
                               f"riconciliato")

    if not reasons:
        log("Stop", "ok (codice invariato dal marcatore)")
        return 0

    flag.write_text("", encoding="utf-8")
    log("Stop", "BLOCCATO: " + "; ".join(reasons))
    print(json.dumps({"decision": "block",
                      "reason": MESSAGE.format(status=STATUS_FILE,
                                               reasons="\n  - ".join(reasons))},
                     ensure_ascii=False))
    return 0


# -------------------------------------------------------------------------------- main

EVENTS = {"session-start": ("SessionStart", session_start), "stop": ("Stop", stop)}


def main(argv) -> int:
    global AGENT
    args = list(argv)
    if "--agent" in args:
        i = args.index("--agent")
        AGENT = args[i + 1] if i + 1 < len(args) else "?"
        del args[i:i + 2]
    if not args or args[0] not in EVENTS:
        log("?", f"evento sconosciuto: {args[:1]}")
        return 0
    name, fn = EVENTS[args[0]]
    try:
        return fn(read_input())
    except Exception as exc:                      # fail-open, sempre
        log(name, f"ERRORE INTERNO {type(exc).__name__} (fail-open, nessun blocco)")
        return 0


if __name__ == "__main__":
    setup_stdout()
    try:
        code = main(sys.argv[1:])
    except Exception:
        code = 0
    sys.exit(0 if code is None else code)
