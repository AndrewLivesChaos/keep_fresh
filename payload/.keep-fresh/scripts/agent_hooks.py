#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agent_hooks — il livello che esegue invece di chiedere, uguale per ogni agente.

    <python> .keep-fresh/scripts/agent_hooks.py session-start --agent <nome>
    <python> .keep-fresh/scripts/agent_hooks.py stop          --agent <nome>
    <python> .keep-fresh/scripts/agent_hooks.py prompt        --agent <nome>

Lo invoca l'agente stesso, attraverso il suo meccanismo di hook. L'aggancio e' l'unica
parte specifica dell'agente (e della macchina), e lo scrive agent_context_init.py nella
configurazione LOCALE di ciascun agente. Qui non c'e' niente di specifico di un agente:
il protocollo usato e' quello che gli agenti supportati hanno in comune.

  session-start  stampa su stdout le sezioni volatili di status.md, o solo il loro indice
                 se superano il tetto di config.toml (il testo lo costruisce
                 context_core.build_injection). Lo stdout di questo evento entra nel
                 contesto dell'agente, NON a schermo: l'utente non vede niente ed e'
                 normale. Accoda l'indice degli handoff aperti (handoff.py), tranne con
                 source resume o compact.
  stop           a fine turno, se il codice e' cambiato e status.md no, stampa su stdout
                 {"decision": "block", "reason": ...} ed esce 0: l'agente non chiude e
                 riceve il motivo. Blocca UNA SOLA VOLTA per sessione.
  prompt         prima che un messaggio dell'utente parta (UserPromptSubmit): se la
                 sessione riprende dopo una pausa piu' lunga della cache con un contesto
                 grande, lo ferma UNA volta e dice quanto costa riprendere. Lo ferma una
                 volta anche quando il contesto supera handoff_warn_tokens, e propone
                 l'handoff. Reinviato, passa. Soglie in [context] di config.toml.

Perche' JSON e non l'uscita 2: provato il 2026-09-17 su Windows, Codex 0.154.0 tratta
l'uscita 2 di Stop come un errore e chiude comunque; la decisione JSON con uscita 0
blocca sia su Codex 0.154.0 sia su Claude Code 2.1.274.

FAIL-OPEN: qualunque errore interno esce 0 senza stampare. Un hook rotto deve degradare
ad "assente", mai a "bloccante". Per questo esiste la traccia .git/agent-hooks.log: e'
l'unico modo di sapere se gli hook girano.
"""

import hashlib
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


def load_handoff():
    """Come load_core: un modulo che non si importa vale come assente, mai come errore."""
    try:
        import handoff
        return handoff
    except Exception:
        return None


handoff = load_handoff()


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
        log("SessionStart", ".keep-fresh/scripts/context_core.py non trovato: niente da iniettare")
        return 0
    root = core.repo_root()
    if root is None:
        return 0

    inj = core.build_injection(root)
    if inj is None:
        log("SessionStart", f"nessun {core.STATUS_FILE}: niente da iniettare")
    else:
        text = inj["text"]
        print(text)
        # Il formato di questa riga lo legge .keep-fresh/scripts/context_cost.py: "iniettati N caratteri".
        ridotto = (f", RIDOTTO a indice: blocchi={inj['blocks_chars']} > tetto={inj['budget']}"
                   if inj["reduced"] else "")
        log("SessionStart", f"iniettati {len(text)} caratteri "
                            f"(fonte={data.get('source', '?')}, "
                            f"assunto={inj['levels'].get('assunto', 0)}{ridotto})")
    handoff_index(root, data)
    return 0


def handoff_index(root, data: dict) -> None:
    """
    Accoda l'indice degli handoff aperti, e pulisce quelli chiusi da tempo. Non con
    `resume` e `compact`: il contesto c'e' gia'. Con una `source` assente o che non
    conosciamo si mostra: l'indice costa poche righe, il silenzio sarebbe il difetto
    peggiore. Fail-open anche qui: un errore degli handoff non tocca l'iniezione.
    """
    if handoff is None or data.get("source") in ("resume", "compact"):
        return
    try:
        cfg, _ = core.load_config(root)
        now = datetime.now().astimezone()
        handoff.prune(root, now, cfg)
        text, n = handoff.index_text(root, now, cfg)
    except Exception as exc:
        log("SessionStart", f"handoff: ERRORE {type(exc).__name__} (indice saltato)")
        return
    if text:
        print("\n" + text)
        log("SessionStart", f"handoff: indice di {n} " + ("voce" if n == 1 else "voci"))


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
        log("Stop", ".keep-fresh/scripts/context_core.py non trovato: nessun controllo")
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


# ------------------------------------------------------------------------------ prompt

HANDOFF_MESSAGE = """Il contesto di questa sessione e' di {ctx} token (soglia {warn}: [context] handoff_warn_tokens in .keep-fresh/config.toml).

- Per cambiare sessione senza perdere il filo: /keep-fresh handoff. L'agente scrive dove sei arrivato in un file locale; poi /clear o una sessione nuova. La nuova sessione vedra' l'handoff in elenco e lo riprendera' con /keep-fresh resume, se vorrai.
- Se ti serve tutto questo contesto: reinvia lo stesso messaggio, non ti fermo una seconda volta in questa sessione."""


def handoff_notice(call, cfg, g, sid):
    """(testo, marcatore) se il contesto supera la soglia e in questa sessione non l'ho detto."""
    if handoff is None or g is None:
        return None, None
    warn = handoff.settings(cfg)[0]
    if warn <= 0 or call["context"] < warn:
        return None, None
    flag = g / f"handoff-warn-{sid}.flag"
    if flag.exists():
        return None, None

    def fmt(n):
        return f"{n:,}".replace(",", ".")
    return HANDOFF_MESSAGE.format(ctx=fmt(call["context"]), warn=fmt(warn)), flag


def prompt(data: dict) -> int:
    """
    Prima che un messaggio dell'utente parta, due avvisi indipendenti, ciascuno UNA volta:

      - ripresa dopo una pausa piu' lunga della cache con un contesto grande: dice quanto
        costa riprendere;
      - contesto oltre handoff_warn_tokens: propone l'handoff e il cambio di sessione.

    Se scattano insieme, parte un solo messaggio che li dice entrambi. Il messaggio fermato
    non arriva al modello e non costa niente. Reinviato, passa. I comandi che iniziano con
    / passano sempre: fermare un /clear o un /keep-fresh handoff sarebbe fermare proprio il
    rimedio.

    Il formato che ferma e' {"decision": "block", "reason": ...}: provato il 2026-09-28
    su Claude Code 2.1.283 (zero chiamate al modello, il motivo e il messaggio originale
    mostrati all'utente); per Codex e' il formato della documentazione, non provato.
    """
    if core is None:
        return 0
    text = str(data.get("prompt") or data.get("prompt_text") or "")
    if text.lstrip().startswith("/"):
        log("Prompt", "ok (comando /)")
        return 0
    tp = data.get("transcript_path")
    if not tp or not Path(tp).is_file():
        log("Prompt", "ok (nessuna trascrizione)")
        return 0
    root = core.repo_root()
    g = core.git_dir(root) if root else None
    cfg, _ = core.load_config(root) if root else ({}, None)
    msg, call = core.resume_warning(tp, datetime.now().astimezone(), cfg)
    if call is None:
        log("Prompt", "ok (nessuna chiamata precedente)")
        return 0
    # Senza session_id i marcatori si legano alla trascrizione, che e' per sessione: con un
    # nome fisso il primo avviso varrebbe per tutte le sessioni future.
    sid = (re.sub(r"[^A-Za-z0-9_-]", "", str(data.get("session_id") or ""))
           or "t" + hashlib.sha1(str(tp).encode("utf-8")).hexdigest()[:12])
    parts, flags, kinds = [], [], []
    if msg is not None:
        # Un avviso per pausa: il marcatore e' legato all'ora dell'ultima chiamata, quindi
        # la prossima pausa della stessa sessione avvisa di nuovo.
        flag = (g / f"resume-warn-{sid}-{int(call['ts'].timestamp())}.flag") if g else None
        if flag is None or not flag.exists():
            parts.append(msg)
            flags.append(flag)
            kinds.append("ripresa dopo la pausa")
    note, hflag = handoff_notice(call, cfg, g, sid)
    if note:
        parts.append(note)
        flags.append(hflag)
        kinds.append("contesto oltre la soglia dell'handoff")
    if not parts:
        log("Prompt", f"ok (contesto {call['context']} token, nessun avviso da dare)")
        return 0
    for f in flags:
        if f is not None:
            f.write_text("", encoding="utf-8")
    log("Prompt", f"FERMATO: {' + '.join(kinds)}, contesto {call['context']} token")
    print(json.dumps({"decision": "block", "reason": "\n\n".join(parts)},
                     ensure_ascii=False))
    return 0


# -------------------------------------------------------------------------------- main

EVENTS = {"session-start": ("SessionStart", session_start), "stop": ("Stop", stop),
          "prompt": ("Prompt", prompt)}


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
