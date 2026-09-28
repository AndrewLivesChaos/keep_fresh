#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
context_core — la parte comune al lint dei documenti e agli hook degli agenti.

Risponde a tre domande, sempre nello stesso modo per chiunque le faccia:

  - dove sta il codice di questo repository;
  - cosa dice la configurazione scritta a mano (docs/context/config.toml);
  - a che commit status.md dichiara di essere riconciliato, e cosa e' cambiato da allora.

Dove sta il codice NON e' scritto da nessuna parte: si rileva a ogni esecuzione dai file
che git conosce, tracciati e nuovi non ignorati. Una costante scritta una volta sola
diventa falsa appena il progetto cresce o si riorganizza, e nessuno se ne accorge: un
repository nato vuoto restava sorvegliato su una cartella `src` che non esisteva.

Nessuna dipendenza fuori dalla libreria standard. Non stampa niente e non esce: decide
chi lo importa cosa fare degli errori.
"""

import re
import subprocess
import tomllib
from pathlib import Path

CONTEXT_DIR = "docs/context"
STATUS_FILE = "docs/context/status.md"
CONFIG_FILE = "docs/context/config.toml"

# I livelli di evidenza, nella forma esatta in cui compaiono nei documenti.
EVIDENCE_LEVELS = ("verificato", "dedotto", "assunto")

# I file che questo impianto installa. Stanno nell'albero ma non sono codice del
# progetto: modificarli non rende vecchio lo stato del lavoro, e contengono di proposito
# i nomi che il lint cerca.
MANAGED_FILES = {"scripts/docs_lint.py", "scripts/context_core.py", "scripts/agent_hooks.py",
                 "scripts/context_cost.py", "scripts/agent_context_version.json"}
# L'inizializzatore si copia dove capita, quindi si riconosce per nome.
MANAGED_NAMES = {"agent_context_init.py"}

# Estensioni che non sono codice: documenti, media, archivi, binari, dati.
NON_SOURCE_SUFFIXES = {
    ".md", ".rst", ".adoc", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".webp", ".bmp", ".tiff", ".mp3", ".mp4", ".wav", ".zip", ".gz", ".tar", ".7z",
    ".bin", ".hex", ".elf", ".exe", ".dll", ".so", ".dylib", ".lock", ".log", ".csv",
    ".pem", ".der", ".crt", ".key",
    ".ttf", ".otf", ".woff", ".woff2", ".eot", ".wasm", ".jar", ".class",
    ".o", ".a", ".obj", ".lib", ".pyc", ".pyo", ".db", ".sqlite", ".sqlite3",
    # Testo libero: note, versioni, output salvati. I .txt che sono codice si
    # riconoscono per nome, qui sotto.
    ".txt",
}

# File che sono codice pur senza un'estensione riconoscibile come tale.
SOURCE_NAMES = {
    "CMakeLists.txt", "Makefile", "makefile", "GNUmakefile", "Dockerfile",
    "Containerfile", "Kconfig", "Jenkinsfile", "Rakefile", "Gemfile", "Vagrantfile",
    "Procfile", "requirements.txt", "constraints.txt",
}

# Directory che non contengono codice del progetto, per quanto piene di file.
NON_SOURCE_DIRS = {
    "docs", "doc", "build", "dist", "out", "target", "node_modules", "vendor",
    "third_party", "external", "__pycache__", "venv", "site-packages",
}

MARKER_RE = re.compile(r"<!--\s*context-verified-at:\s*([0-9a-f]{7,40})\s*-->")
# I marcatori devono stare DA SOLI sulla loro riga: senza le ancore di riga, la regex
# cattura anche il paragrafo che spiega i marcatori citandoli in linea.
BLOCK_RE = re.compile(
    r"^[ \t]*<!--\s*session-start:\s*begin\s*-->[ \t]*$"
    r"(.*?)"
    r"^[ \t]*<!--\s*session-start:\s*end\s*-->[ \t]*$",
    re.S | re.M)


# ------------------------------------------------------------------------------ git

def run_git(root, *args):
    """(riuscito, stdout). Un git assente o rotto vale come comando fallito."""
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           cwd=str(root) if root else None)
        return r.returncode == 0, r.stdout
    except OSError:
        return False, ""


def repo_root(start=None):
    ok, out = run_git(start, "rev-parse", "--show-toplevel")
    return Path(out.strip()) if ok and out.strip() else None


def git_dir(root):
    ok, out = run_git(root, "rev-parse", "--git-dir")
    if not ok or not out.strip():
        return None
    p = Path(out.strip())
    return p if p.is_absolute() else (root / p)


def head_sha(root):
    """Lo sha corto di HEAD, o None se il repository non ha ancora un commit."""
    ok, out = run_git(root, "rev-parse", "--short", "HEAD")
    sha = out.strip()
    return sha if ok and re.fullmatch(r"[0-9a-f]{7,40}", sha) else None


# ---------------------------------------------------------------------- configurazione

def load_config(root):
    """
    (configurazione, errore). Un file assente e' normale e vale come vuoto. Un file
    malformato NON vale come vuoto in silenzio: l'errore torna a chi chiama, perche'
    liste di eccezioni perse di colpo fanno sembrare rotti i documenti.
    """
    p = Path(root) / CONFIG_FILE
    if not p.is_file():
        return {}, None
    try:
        with open(p, "rb") as fh:
            return tomllib.load(fh), None
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return {}, f"{CONFIG_FILE} non e' TOML valido: {exc}"


def config_table(cfg, *keys) -> dict:
    """Una tabella annidata della configurazione, o {} se manca o ha la forma sbagliata."""
    cur = cfg
    for k in keys:
        cur = cur.get(k) if isinstance(cur, dict) else None
    return cur if isinstance(cur, dict) else {}


def _prefixes(cfg, key):
    vals = config_table(cfg, "code").get(key, [])
    if not isinstance(vals, list):
        return []
    return [str(v).strip().replace("\\", "/").strip("/") for v in vals if str(v).strip()]


def _under(rel, prefixes):
    return any(rel == p or rel.startswith(p + "/") for p in prefixes)


# ---------------------------------------------------------------------- dove sta il codice

def known_files(root):
    """
    I file che git conosce: tracciati, e nuovi purche' non ignorati. I nuovi contano,
    perche' una cartella appena creata e' gia' codice prima del primo `git add`.
    """
    ok, out = run_git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if not ok:
        return []
    return sorted({f for f in out.split("\0") if f})


def _is_managed(rel):
    return rel in MANAGED_FILES or rel.rsplit("/", 1)[-1] in MANAGED_NAMES


def _has_source_suffix(rel):
    name = rel.rsplit("/", 1)[-1]
    if name in SOURCE_NAMES or name.startswith("Kconfig."):
        return True
    suf = Path(name).suffix.lower()
    return bool(suf) and suf not in NON_SOURCE_SUFFIXES


def code_files(root, cfg):
    """
    Il codice del progetto: cio' che, se cambia, puo' rendere falsi i documenti.

    Fuori: documenti e binari, directory di build e dipendenze, directory che iniziano
    con un punto (configurazione di strumenti: .github, .vscode, .claude...), e i file
    di questo impianto. `[code] include` e `[code] exclude` correggono la regola.
    """
    include, exclude = _prefixes(cfg, "include"), _prefixes(cfg, "exclude")
    out = []
    for rel in known_files(root):
        if _under(rel, exclude):
            continue
        if _under(rel, include):
            out.append(rel)
            continue
        dirs = rel.split("/")[:-1]
        if any(d in NON_SOURCE_DIRS or d.startswith(".") for d in dirs):
            continue
        if _is_managed(rel) or not _has_source_suffix(rel):
            continue
        out.append(rel)
    return out


def tree_files(root, cfg):
    """
    Dove un simbolo citato nei documenti puo' legittimamente vivere. E' piu' largo del
    codice: comprende le directory di configurazione degli strumenti e i file di questo
    impianto, che i documenti citano anche loro.
    """
    exclude = _prefixes(cfg, "exclude")
    out = []
    for rel in known_files(root):
        if _under(rel, exclude):
            continue
        dirs = rel.split("/")[:-1]
        if any(d in NON_SOURCE_DIRS or d == ".git" for d in dirs):
            continue
        if _has_source_suffix(rel):
            out.append(rel)
    return out


def code_scope(root, cfg):
    """
    (pathspec per git, etichette leggibili). Le pathspec servono a `git log` e
    `git status` per chiedere "e' cambiato il codice?" senza elencare mille file.

    Lista vuota = nessun codice ancora. Chi chiama deve saltare il controllo: una
    pathspec vuota, per git, vuol dire TUTTO il repository.
    """
    include = _prefixes(cfg, "include")
    tops = []
    for rel in code_files(root, cfg):
        # Un percorso incluso a mano si sorveglia per quello che e', non allargato alla
        # sua directory di primo livello: `.github/workflows` non e' tutto `.github`.
        top = next((p for p in include if _under(rel, [p])), None)
        if top is None:
            top = rel.split("/", 1)[0] if "/" in rel else rel
        if top not in tops:
            tops.append(top)
    if not tops:
        return [], []
    specs = list(tops)
    specs += [f":(exclude){m}" for m in sorted(MANAGED_FILES)]
    specs += [f":(exclude,glob)**/{n}" for n in sorted(MANAGED_NAMES)]
    specs += [f":(exclude){e}" for e in _prefixes(cfg, "exclude")]
    specs += [f":(exclude,glob)**/*{s}" for s in sorted(NON_SOURCE_SUFFIXES)]
    labels = [t + "/" if (Path(root) / t).is_dir() else t for t in tops]
    return specs, labels


def commits_since(root, sha, specs):
    """(marcatore valido?, righe di log dei commit che hanno toccato il codice)."""
    if not specs:
        return True, []
    ok, out = run_git(root, "log", "--oneline", f"{sha}..HEAD", "--", *specs)
    return ok, [l for l in out.splitlines() if l.strip()]


def dirty(root, specs) -> str:
    """Modifiche non committate sotto le pathspec date (stringa vuota = pulito)."""
    if not specs:
        return ""
    return run_git(root, "status", "--porcelain", "--", *specs)[1].strip()


# ---------------------------------------------------------------------- documento di stato

def read_marker(status_text):
    m = MARKER_RE.search(status_text)
    return m.group(1) if m else None


def extract_marked(status_text):
    """
    Le sezioni da iniettare le dichiara il documento, con
    <!-- session-start: begin --> ... <!-- session-start: end -->.
    Cosi' chi le inietta non sa niente della numerazione delle sezioni.
    """
    return [m.group(1).strip() for m in BLOCK_RE.finditer(status_text) if m.group(1).strip()]


def count_levels(root) -> dict:
    counts = {lvl: 0 for lvl in EVIDENCE_LEVELS}
    ctx = Path(root) / CONTEXT_DIR
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


# ---------------------------------------------------------------------- l'iniezione all'avvio

# Il tetto, in caratteri, dei blocchi session-start che l'hook inietta per intero. E' in
# caratteri perche' l'hook non ha un tokenizer. Quanti token valgano davvero lo misura
# scripts/context_cost.py; come ordine di grandezza, sui documenti in italiano di questo
# impianto un token ha fatto da 1,9 a 2,3 caratteri (stima dalle sessioni, 2026-09-26).
DEFAULT_INJECTION_BUDGET = 8000
# Nell'indice, la prima riga di ogni voce si taglia qui: basta a riconoscerla.
INDEX_LINE_MAX = 160


def injection_budget(cfg) -> int:
    """Il tetto da [context] max_injection_chars in config.toml, o quello di default."""
    val = config_table(cfg, "context").get("max_injection_chars")
    if isinstance(val, int) and not isinstance(val, bool) and val > 0:
        return val
    return DEFAULT_INJECTION_BUDGET


def index_of(blocks) -> str:
    """
    L'indice dei blocchi: i titoli e la prima riga di ogni voce di primo livello. E' cio'
    che si inietta quando i blocchi superano il tetto: l'agente vede cosa c'e' e dove, e
    legge il dettaglio solo di cio' che gli serve.
    """
    out = []
    for block in blocks:
        for line in block.splitlines():
            if re.match(r"^#{1,6}\s", line):
                out.append(line.rstrip())
            elif re.match(r"^(?:[-*]|\d+\.)\s", line):
                text = line.rstrip()
                if len(text) > INDEX_LINE_MAX:
                    text = text[:INDEX_LINE_MAX - 1].rstrip() + "…"
                out.append(text)
        out.append("")
    return "\n".join(out).strip()


def build_injection(root, cfg=None):
    """
    Il testo che l'hook di avvio mette nel contesto dell'agente. Si costruisce qui, e non
    nell'hook, perche' hook, lint e misura dei consumi ne vedano la stessa identica
    versione. None se non c'e' status.md.

    Torna un dizionario: text (il testo esatto), blocks_chars (quanto fanno i blocchi
    session-start per intero), budget, reduced (True se i blocchi superano il tetto e al
    loro posto va l'indice), levels (il cruscotto dell'evidenza).
    """
    root = Path(root)
    status_path = root / STATUS_FILE
    if not status_path.is_file():
        return None
    if cfg is None:
        cfg, _ = load_config(root)
    status = status_path.read_text(encoding="utf-8", errors="replace")
    specs, labels = code_scope(root, cfg)
    where = ", ".join(labels)
    budget = injection_budget(cfg)

    out = [
        "=== Stato del progetto (iniettato da scripts/agent_hooks.py) ===",
        f"Fonte: {STATUS_FILE}. Se agisci su qualcosa di qui sotto, leggi in quel file la "
        f"sezione che ti serve, non il file intero.",
        "",
    ]

    # --- Le sezioni che il documento stesso dichiara volatili ---
    blocks = extract_marked(status)
    blocks_chars = sum(len(b) for b in blocks)
    reduced = blocks_chars > budget
    if not blocks:
        out.append(f"({STATUS_FILE} non ha blocchi <!-- session-start: begin/end -->: "
                   f"nessuna sezione dichiarata volatile.)")
    elif reduced:
        out.append(f"ATTENZIONE: i blocchi session-start di {STATUS_FILE} fanno "
                   f"{blocks_chars} caratteri, oltre il tetto di {budget}. Qui sotto c'e' "
                   f"solo il loro indice: leggi nel file le voci che ti servono. Se lavori "
                   f"su {STATUS_FILE}, riporta i blocchi sotto il tetto (vedi "
                   f"docs/agent_docs_guide.md).")
        out.append("")
        out.append(index_of(blocks))
    else:
        out.append("\n\n".join(blocks))
    out.append("")

    # --- Cruscotto dei livelli di evidenza ---
    levels = count_levels(root)
    out.append("Evidenza nei documenti di contesto: " +
               "  ".join(f"{k}={v}" for k, v in levels.items()))

    # --- Freschezza: il documento e' invecchiato rispetto al codice? ---
    sha = read_marker(status)
    if sha:
        ok, since = commits_since(root, sha, specs)
        if ok and since:
            out.append(f"ATTENZIONE: {len(since)} commit hanno toccato il codice ({where}) "
                       f"dopo {sha}, il punto a cui {STATUS_FILE} dichiara di essere "
                       f"riconciliato. Potrebbe dire cose non piu' vere.")
    elif head_sha(root) is not None:
        out.append(f"ATTENZIONE: {STATUS_FILE} non ha il marcatore context-verified-at: "
                   f"la sua freschezza non e' misurabile.")

    # --- Lavoro non registrato rimasto da una sessione precedente ---
    if dirty(root, specs) and not dirty(root, [STATUS_FILE]):
        out.append(f"ATTENZIONE: ci sono modifiche non committate al codice ({where}) e "
                   f"{STATUS_FILE} e' intatto. Probabile lavoro di una sessione "
                   f"precedente mai registrato: valuta se va annotato.")

    out += ["", "Verifica che i documenti dicano ancora il vero: "
                "python scripts/docs_lint.py",
            "=== fine stato del progetto ==="]
    return {"text": "\n".join(out), "blocks_chars": blocks_chars, "budget": budget,
            "reduced": reduced, "levels": levels}
