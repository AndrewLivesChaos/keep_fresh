#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handoff — il filo di una sessione, per riprenderlo in una sessione nuova.

    <python> .keep-fresh/scripts/handoff.py new --title "<una riga>"   crea il file e ne stampa il percorso
    <python> .keep-fresh/scripts/handoff.py list [--all]               gli handoff aperti; --all anche gli altri
    <python> .keep-fresh/scripts/handoff.py resume [n|parola] [--comunque]
                                                                       lo stampa e lo segna ripreso; --comunque
                                                                       anche se branch o HEAD non coincidono
    <python> .keep-fresh/scripts/handoff.py discard [n|parola]         lo segna scartato
    <python> .keep-fresh/scripts/handoff.py prune                      cancella i chiusi o scaduti da tempo

Un handoff e' un file in .git/keep-fresh-handoff/ (un fatto della macchina, non del
repository, come context-cost.json). La meccanica sta qui; il CONTENUTO lo scrive l'agente,
perche' decisioni, vicoli ciechi e prossimo passo li conosce solo lui.

Lo importano anche gli hook (agent_hooks.py): l'indice all'avvio e le soglie stanno qui, in
un punto solo, cosi' `list` e l'indice dicono sempre la stessa cosa e con la stessa
numerazione.

Nessuna dipendenza fuori dalla libreria standard. Un file illeggibile nella cartella si
segnala e si ignora: non deve mai far fallire un comando ne' un hook.
"""

import argparse
import io
import re
import sys
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import context_core as core  # noqa: E402

# Dentro .git/: non finisce mai in un commit.
HANDOFF_DIR = "keep-fresh-handoff"

DEFAULT_WARN_TOKENS = 150_000
DEFAULT_HOURS = 48
DEFAULT_PRUNE_DAYS = 30
# Quante righe porta l'indice all'avvio: ognuna costa token in ogni sessione che parte.
MAX_LISTED = 5

STATES = ("aperto", "ripreso", "scartato")

# Il file nasce con questa riga: se l'agente lancia `new` e si dimentica di scrivere il
# corpo, lo si vede ovunque l'handoff compare, invece di scoprirlo alla ripresa.
EMPTY_MARKER = "<!-- handoff-vuoto: cancella questa riga quando hai scritto il corpo -->"

BODY_TEMPLATE = f"""{EMPTY_MARKER}

## Obiettivo
(cosa stavi cercando di ottenere, e per chi)

## Fatto
(cio' che e' finito e verificato; cio' che e' finito ma non verificato, a parte)

## Decisioni
(cosa hai scelto, perche', e le alternative scartate)

## Non ha funzionato
(i vicoli ciechi: chi riprende non deve ripercorrerli)

## Ancora da fare
(l'elenco COMPLETO di cio' che resta, voce per voce, preso da status.md, piani e TODO del
progetto e non dalla memoria: ogni voce aperta compare qui, anche se non e' per ora)

## Prossimo passo
(la prima cosa da fare, concreta)

## File e stato git
(file toccati, modifiche non committate, branch)
"""

META_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def setup_stdout() -> None:
    """La console di Windows non e' UTF-8: senza questo, un accento uccide il comando."""
    try:
        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                          errors="replace")
    except Exception:
        pass


# ----------------------------------------------------------------------- configurazione

def settings(cfg):
    """
    (soglia di token dell'avviso, ore di vita nell'indice, giorni prima della pulizia) da
    [context]. La soglia 0 spegne l'avviso; per le altre due un valore non positivo o di
    tipo sbagliato vale come mancante.
    """
    t = core.config_table(cfg, "context")

    def num(key, default, zero_ok=False):
        v = t.get(key)
        ok = isinstance(v, int) and not isinstance(v, bool) and (v > 0 or (zero_ok and v == 0))
        return v if ok else default
    return (num("handoff_warn_tokens", DEFAULT_WARN_TOKENS, zero_ok=True),
            num("handoff_ore", DEFAULT_HOURS),
            num("handoff_prune_giorni", DEFAULT_PRUNE_DAYS))


# ------------------------------------------------------------------------------ archivio

def store(root):
    g = core.git_dir(root)
    return g / HANDOFF_DIR if g else None


def read_text(path):
    """
    Il testo del file, con qualunque codifica l'abbia lasciato chi l'ha ritoccato dalla shell
    di Windows: UTF-8 con o senza BOM (Set-Content -Encoding utf8), UTF-16 con BOM
    (Out-File di PowerShell 5.1). Un handoff che l'agente ha riscritto cosi' non deve
    sparire dall'indice: nessuno se ne accorgerebbe.
    """
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16").replace("\r\n", "\n")
    return raw.decode("utf-8-sig").replace("\r\n", "\n")


def parse(path):
    """
    Un handoff: un dict con percorso, nome ed `errore`; se il file e' valido anche titolo,
    creato (con fuso), branch, head, stato e corpo. Un file rotto non solleva: torna con
    `errore` valorizzato.
    """
    e = {"path": path, "name": path.name, "errore": None}
    try:
        text = read_text(path)
    except (OSError, UnicodeError) as exc:
        e["errore"] = f"non leggibile ({type(exc).__name__})"
        return e
    m = META_RE.match(text)
    if not m:
        e["errore"] = "intestazione --- mancante"
        return e
    meta = {}
    for ln in m.group(1).splitlines():
        k, sep, v = ln.partition(":")
        if sep:
            meta[k.strip()] = v.strip()
    try:
        creato = datetime.fromisoformat(meta["creato"])
        e.update(titolo=meta["titolo"], branch=meta["branch"], head=meta["head"],
                 stato=meta["stato"], creato=creato if creato.tzinfo else creato.astimezone())
    except (KeyError, ValueError):
        e["errore"] = "metadati incompleti o illeggibili"
        return e
    if e["stato"] not in STATES:
        e["errore"] = f"stato sconosciuto: {e['stato']}"
        return e
    e["corpo"] = text[m.end():]
    return e


def entries(root):
    d = store(root)
    if d is None or not d.is_dir():
        return []
    return [parse(p) for p in sorted(d.glob("*.md"))]


def expired(e, now, hours):
    return now - e["creato"] > timedelta(hours=hours)


def current_branch(root):
    ok, out = core.run_git(root, "symbolic-ref", "--short", "-q", "HEAD")
    return out.strip() if ok and out.strip() else "(HEAD staccato)"


def mismatch(root, e):
    """
    Perche' questo handoff potrebbe non essere sulla base di adesso: etichette, vuota se
    coincide. Un handoff scritto in un repository senza commit (head "-") non ha un HEAD
    da confrontare.
    """
    out = []
    if e["branch"] != current_branch(root):
        out.append("altro branch")
    head = core.head_sha(root)
    if head and e["head"] not in ("-", head):
        ok, _ = core.run_git(root, "merge-base", "--is-ancestor", e["head"], "HEAD")
        if not ok:
            out.append("HEAD non nel tuo storico")
    return out


def line(n, e, root):
    when = e["creato"].astimezone().strftime("%d/%m %H:%M")
    tags = mismatch(root, e)
    if EMPTY_MARKER in e["corpo"]:
        tags.append("vuoto")
    tail = f"  ({', '.join(tags)})" if tags else ""
    lead = f"{n:>2}. " if n else "    "
    return f"{lead}{when}  [{e['branch']}]  {e['titolo']}{tail}"


def open_list(root, now, cfg):
    """
    Gli handoff che l'indice mostra, nell'ordine in cui li numera: aperti, validi, non
    scaduti. Il branch corrente per primo, poi i piu' recenti.
    """
    _, hours, _ = settings(cfg)
    branch = current_branch(root)
    live = [e for e in entries(root) if not e["errore"] and e["stato"] == "aperto"
            and not expired(e, now, hours)]
    live.sort(key=lambda e: e["creato"], reverse=True)
    live.sort(key=lambda e: e["branch"] != branch)      # stabile: il resto resta per data
    return live


def index_text(root, now, cfg):
    """(testo dell'indice per l'avvio di una sessione, numero di handoff aperti)."""
    items = open_list(root, now, cfg)
    if not items:
        return "", 0
    rows = ["Handoff aperti (non agire, non leggere; riprendi solo su richiesta "
            "dell'utente, con /keep-fresh:resume):"]
    rows += [line(n, e, root) for n, e in enumerate(items[:MAX_LISTED], 1)]
    if len(items) > MAX_LISTED:
        rows.append(f"+{len(items) - MAX_LISTED} altri: /keep-fresh:handoff --elenco")
    return "\n".join(rows), len(items)


def slugify(title):
    s = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40].strip("-")
    return s or "handoff"


def new(root, title, now):
    """Crea il file con i metadati di adesso e il corpo da scrivere. Ritorna il percorso."""
    d = store(root)
    d.mkdir(exist_ok=True)
    title = " ".join(title.split())                     # una riga sola
    stem = f"{now:%Y%m%d-%H%M}-{slugify(title)}"
    path, n = d / f"{stem}.md", 1
    while path.exists():
        n += 1
        path = d / f"{stem}-{n}.md"
    meta = (f"---\ntitolo: {title}\ncreato: {now.isoformat(timespec='seconds')}\n"
            f"branch: {current_branch(root)}\nhead: {core.head_sha(root) or '-'}\n"
            f"stato: aperto\n---\n")
    path.write_text(meta + BODY_TEMPLATE, encoding="utf-8", newline="\n")
    return path


def listing(items, root):
    return "\n".join(line(n, e, root) for n, e in enumerate(items, 1))


def select(root, arg, now, cfg):
    """
    (handoff, errore). Senza argomento va bene solo se ce n'e' uno; un numero e' la
    posizione nell'elenco; una parola cerca nei titoli di tutti gli aperti, scaduti
    compresi: uno scaduto non compare piu' da solo, ma nominandolo si riprende.
    """
    items = open_list(root, now, cfg)
    if arg is None:
        if len(items) == 1:
            return items[0], None
        if not items:
            return None, "Nessun handoff aperto."
        return None, ("Piu' di un handoff aperto: dimmi quale (numero o parola del "
                      "titolo).\n" + listing(items, root))
    if arg.isdigit():
        n = int(arg)
        if 1 <= n <= len(items):
            return items[n - 1], None
        return None, f"Nessun handoff numero {n}.\n" + (listing(items, root) or
                                                        "Nessun handoff aperto.")
    live = [e for e in entries(root) if not e["errore"] and e["stato"] == "aperto"]
    # Il nome del file e' univoco anche quando il titolo non lo e' (due titoli uno dentro
    # l'altro, solo cifre, virgolette): e' quello che resume suggerisce per --comunque.
    by_name = [e for e in live if arg in (e["name"], e["path"].stem)]
    if len(by_name) == 1:
        return by_name[0], None
    found = [e for e in live if arg.lower() in e["titolo"].lower()]
    if len(found) == 1:
        return found[0], None
    if not found:
        return None, f"Nessun handoff aperto con «{arg}» nel titolo."
    return None, (f"«{arg}» sta nel titolo di piu' handoff: scegline uno.\n"
                  + "\n".join(line(None, e, root) for e in found))


def set_state(path, state):
    """
    Cambia lo stato nell'intestazione, e solo li': una riga `stato:` nel corpo non si tocca.
    Come `parse`, accetta chiavi rientrate e le ripetute (vale l'ultima: le cambia tutte).
    Riscrive in UTF-8 senza BOM. Ritorna False, senza scrivere, se non trova lo stato.
    """
    text = read_text(path)
    m = META_RE.match(text)
    if not m:
        return False
    head, n = re.subn(r"^([ \t]*)stato:.*$",
                      lambda k: f"{k.group(1)}stato: {state}", m.group(1), flags=re.M)
    if not n:
        return False
    path.write_text("---\n" + head + "\n---\n" + text[m.end():], encoding="utf-8",
                    newline="\n")
    return True


def prune(root, now, cfg):
    """
    Cancella i file chiusi (ripresi, scartati) o scaduti la cui ultima modifica e' piu'
    vecchia di handoff_prune_giorni. Un aperto non scaduto non si tocca mai, e un file
    illeggibile nemmeno: potrebbe essere stato scritto a mano. Ritorna i nomi cancellati.
    """
    _, hours, days = settings(cfg)
    gone = []
    for e in entries(root):
        if e["errore"] or (e["stato"] == "aperto" and not expired(e, now, hours)):
            continue
        try:
            modified = datetime.fromtimestamp(e["path"].stat().st_mtime).astimezone()
            if now - modified > timedelta(days=days):
                e["path"].unlink()
                gone.append(e["name"])
        except OSError:
            pass
    return gone


# -------------------------------------------------------------------------------- comandi

def cmd_list(root, a, now, cfg):
    items = open_list(root, now, cfg)
    shown = {e["name"] for e in items}
    every = entries(root)
    print(f"Handoff aperti: {len(items)}")
    for n, e in enumerate(items, 1):
        print(line(n, e, root))
    for e in every:
        if e["errore"]:
            print(f"  ! {e['name']}: {e['errore']} (ignorato)")
    if a.all:
        rest = [e for e in every if not e["errore"] and e["name"] not in shown]
        if rest:
            print("Chiusi o scaduti:")
        for e in rest:
            stato = "scaduto" if e["stato"] == "aperto" else e["stato"]
            print(f"  {stato:<9} {line(None, e, root)}")
    return 0


def cmd_resume(root, a, now, cfg):
    e, err = select(root, a.which, now, cfg)
    if err:
        print(err)
        return 1
    diverso = mismatch(root, e)
    if diverso and not a.comunque:
        print(f"ATTENZIONE: {' e '.join(diverso)} (scritto su [{e['branch']}] a "
              f"{e['head']}, adesso sei su [{current_branch(root)}] a "
              f"{core.head_sha(root) or '-'}). Non l'ho letto ne' consumato.\n"
              f"Dillo all'utente. Per riprenderlo comunque: handoff.py resume "
              f"{e['path'].stem} --comunque")
        return 1
    if not set_state(e["path"], "ripreso"):
        print(f"Non riesco a segnare ripreso l'handoff {e['name']}: l'intestazione non "
              f"ha una riga di stato leggibile. Non l'ho letto.")
        return 1
    if EMPTY_MARKER in e["corpo"]:
        print("ATTENZIONE: il corpo non e' stato scritto: c'e' ancora la riga di handoff "
              "vuoto. Chi l'ha creato non ha finito.\n")
    when = e["creato"].astimezone().strftime("%d/%m/%Y %H:%M")
    print(f"# Handoff: {e['titolo']}\nscritto il {when} su [{e['branch']}] a {e['head']}\n")
    print(e["corpo"].strip("\n"))
    return 0


def cmd_discard(root, a, now, cfg):
    e, err = select(root, a.which, now, cfg)
    if err:
        print(err)
        return 1
    if not set_state(e["path"], "scartato"):
        print(f"Non riesco a segnare scartato l'handoff {e['name']}: l'intestazione non "
              f"ha una riga di stato leggibile.")
        return 1
    print(f"Scartato: {e['titolo']}")
    return 0


def cmd_prune(root, a, now, cfg):
    gone = prune(root, now, cfg)
    for name in gone:
        print(f"cancellato {name}")
    print(f"Pulizia: {len(gone)} file cancellati")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Gli handoff fra sessioni.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new", help="crea un handoff da compilare")
    p.add_argument("--title", required=True, help="una riga: il lavoro e a che punto sei")
    p = sub.add_parser("list", help="gli handoff aperti")
    p.add_argument("--all", action="store_true", help="anche chiusi e scaduti")
    p = sub.add_parser("resume", help="stampa un handoff e lo segna ripreso")
    p.add_argument("which", nargs="?", help="numero dell'elenco o parola del titolo")
    p.add_argument("--comunque", action="store_true",
                   help="anche se branch o HEAD non coincidono")
    p = sub.add_parser("discard", help="segna un handoff scartato")
    p.add_argument("which", nargs="?", help="numero dell'elenco o parola del titolo")
    sub.add_parser("prune", help="cancella i chiusi e gli scaduti da tempo")
    a = ap.parse_args(argv)

    root = core.repo_root()
    if root is None:
        print("Non sei dentro un repository git.", file=sys.stderr)
        return 1
    cfg, _ = core.load_config(root)
    now = datetime.now().astimezone()
    if a.cmd == "new":
        if not " ".join(a.title.split()):
            print("Il titolo e' vuoto: dimmi in una riga il lavoro e a che punto sei.",
                  file=sys.stderr)
            return 1
        print(new(root, a.title, now))
        return 0
    return {"list": cmd_list, "resume": cmd_resume, "discard": cmd_discard,
            "prune": cmd_prune}[a.cmd](root, a, now, cfg)


if __name__ == "__main__":
    setup_stdout()
    sys.exit(main())
