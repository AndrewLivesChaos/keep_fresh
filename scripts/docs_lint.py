#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
docs_lint — controlla che la documentazione per agenti dica ancora il vero.

Questo progetto non ha CI ne' test automatici: e' l'unico controllo automatico che
esiste, e non guarda il firmware, guarda i documenti che lo descrivono.

Cinque controlli:

  1. FEATURE BANDITE  — i simboli elencati in docs/context/invariants.md non sono
                        ricomparsi nel codice. La lista NON e' scritta qui: viene
                        letta dal documento, che resta l'unica fonte.
  2. IDENTIFICATORI   — ogni simbolo o percorso citato fra backtick in docs/context/
                        esiste ancora nell'albero. E' il controllo che intercetta
                        una rinomina fatta senza aggiornare i documenti.
  3. EVIDENZA         — in docs/context/ ogni "verificato" porta una data, e il
                        lessico conversazionale ([Certo]/[Probabile]/[Ipotesi]) non
                        entra nei documenti. Stampa il cruscotto dei tre livelli.
  4. LINK E ANCORE    — ogni link markdown locale risolve, ancora compresa.
  5. FRESCHEZZA       — quanti commit hanno toccato le directory sorgente dopo
                        il punto in cui status.md dichiara di essere riconciliato.

Uso:   python scripts/docs_lint.py [--quiet]
Esce 0 se non ci sono errori, 1 se ce n'e' almeno uno. I WARN non fanno fallire.
"""

import io
import os
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# --------------------------------------------------------------------------- setup

def repo_root() -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, encoding="utf-8")
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except OSError:
        pass
    return Path(__file__).resolve().parent.parent

ROOT = repo_root()
CONTEXT = ROOT / "docs" / "context"

# ==== TARATURA DEL PROGETTO (inizio) ====
# Tutto cio' che sta fra questi due marcatori e' specifico di QUESTO repository.
# `agent_context_init.py --pack` lo sostituisce con valori neutri prima di
# trasportarlo altrove, e l'inizializzatore lo riempie rilevandolo dal repo di
# destinazione. Non spostare i marcatori.

# Percorsi che compongono "il codice": tutto cio' che una rinomina toccherebbe.
CODE_DIRS = ["src", "drivers", "boards", "sysbuild", "scripts", ".claude"]
CODE_FILES = ["CMakeLists.txt", "Kconfig", "prj.conf", "sysbuild.conf", "pm_static.yml"]
CODE_SUFFIXES = {".c", ".h", ".py", ".conf", ".txt", ".yml", ".yaml", ".cmake",
                 ".dts", ".dtsi", ".overlay", ".json", ".rst", ".defconfig"}
SKIP_DIRS = {"build", ".git", "__pycache__", "firmware"}
# Documenti RICEVUTI da terzi. Sono conservati verbatim perche' sono la traccia di cosa
# e' stato detto e quando: i loro link puntano dentro il workspace di chi li ha scritti e
# non sono nostri da riparare. Riscriverli falsificherebbe il documento, che e' la stessa
# ragione per cui gli archivi in docs/superpowers/ non si riscrivono. Restano soggetti a
# tutti gli altri controlli: qui salta solo la verifica dei link.
RECEIVED_DOCS = {
    "documento-ricevuto-1.md",
    "documento-ricevuto-2.md",
}
# I file "meta" contengono la lista dei simboli banditi per poterla applicare o
# trasportare: vanno esclusi dal controllo 1, o si accusano da soli. Restano invece
# nell'albero per tutti gli altri controlli, altrimenti i simboli che definiscono
# risulterebbero inesistenti.
SELF = Path(__file__).resolve()
# L'inizializzatore puo' stare ovunque — di solito nella radice, dove lo si copia —
# quindi si cerca per nome invece di dare per scontato che sia in scripts/.
META_FILES = {SELF} | {p.resolve() for p in ROOT.rglob("agent_context_init.py")
                       if ".git" not in p.parts}

# Token citati nei documenti che NON devono esistere nel codice, per costruzione.
# Ogni voce porta il motivo: senza motivo non si aggiunge niente a questa lista.
EXPECTED_ABSENT = {
    "SET_DEVICE_ID":      "id-code 0x14 ritirato: il buco e' voluto",
    "ENABLE_STREAM":      "ritirato su entrambi i canali",
    "TEST_ENDED":         "INFO 0x0B ritirato (Task 5, protocollo V2): assorbito in TEST_REPORT",
    "deviceId":           "campo del vecchio protocollo Cruise Dongle, rimosso",
    "DEVID":              "idem",
    "DEVID_IDX":          "idem",
    "Memory_Flash_":      "feature bandita, elencata negli invarianti",
    "USB_MASS_STORAGE":   "feature bandita",
    "CONFIG_BT_SMP":      "disabilitato per scelta: compare come assenza, non come simbolo",
    "mcumgr":             "feature bandita",
    "smp_bt":             "feature bandita",
    "ff.h":               "feature bandita (FatFs)",
    "fs/fs.h":            "feature bandita (FatFs)",
    "ad7779":             "feature bandita (EEG)",
    "Eeg_":               "feature bandita (EEG)",
    "mt25qu":             "feature bandita (flash esterna)",
    "qspi":               "feature bandita (flash esterna)",
    "CONFIG_FILE_SYSTEM": "citato come trappola da NON abilitare",
    "bq27xxx":            "cartella driver rimossa: il gauge e' gestito in bsm.c",
    "Modulo_Funzione":    "e' lo schema di naming, non un simbolo",
    "progetto_origine":        "il progetto di origine, non un simbolo di questo albero",
    "sense_healt":        "repo di riferimento esterno",
    "usb_protocol":       "modulo inglobato in usb_connection (4744d3c)",
}

# Simboli che esistono, ma in Zephyr / NCS, non in questo albero. Sono citati nei
# documenti perche' spiegano un vincolo esterno. Ogni voce porta il motivo.
EXTERNAL_SYMBOLS = {
    "BT_LE_ADV_OPT_CONN":       "opzione Zephyr deprecata, citata per spiegare la migrazione",
    "BT_LE_ADV_CONN_FAST_2":    "macro Zephyr usata via API, non definita qui",
    "CONFIG_DISABLE_FLASH_PATCH": "Kconfig Zephyr, citato come raccomandazione CMake",
    "DISABLE_FLASH_PATCH":      "banner CMake di Zephyr",
    "Kconfig.zephyr":           "file di Zephyr, incluso dal nostro Kconfig",
    "flash_img":                "API Zephyr usata dal DFU custom",
    "usbd_msg_register_cb":     "API Zephyr",
    "atomic_cas":               "API Zephyr",
    "SessionStart":             "evento hook di Claude Code",
    "SessionEnd":               "evento hook di Claude Code",
    "PreCompact":               "evento hook di Claude Code",
    "UserPromptSubmit":         "evento hook di Claude Code",
    "PreToolUse":               "evento hook di Claude Code",
}

# Parole che sembrano identificatori ma sono prosa, unita' di misura o nomi esterni.
NOT_SYMBOLS = {
    "acc", "gyr", "mag", "sfl", "dps", "raw", "byte", "bytes", "true", "false",
    "null", "void", "atomic", "round", "notify", "write", "connect", "develop",
    "main", "origin", "head", "git", "west", "python", "nrfutil", "grep",
    "markdown", "kconfig", "prj", "conf", "hex", "bin", "elf", "swap", "move",
    "slot0", "slot1", "storage", "flash", "ram", "rom", "noinit", "little",
    "endian", "watermark", "stream", "test", "owner", "canale", "trasporto",
    "severita", "warning", "error", "fatal", "info", "exec", "request",
    "ottotipo", "peripheral", "central", "advertising", "pairing", "beacon",
    "chore", "docs", "feat", "fix", "refactor", "style", "perf", "build", "text",
    "verificato", "dedotto", "assunto", "clinico", "sensor", "board",
    "esito", "data", "chi", "prova", "regola", "dove", "perche",
    # Progetto sorella: l'interfaccia PC Qt, repo separato in ../progetto_pc.
    "progetto_pc",
    # API di sistema Windows citate dalla parte PC: non sono simboli di questo firmware.
    "QueryPerformanceCounter",
}
# ==== TARATURA DEL PROGETTO (fine) ====

# La ricerca in NOT_SYMBOLS confronta il token gia' abbassato a minuscolo: una voce
# scritta in maiuscolo non combacerebbe mai, e il difetto sarebbe invisibile finche'
# quella parola non compare in un documento. Si normalizza qui, una volta.
NOT_SYMBOLS = {w.lower() for w in NOT_SYMBOLS}

# Fuga esplicita per il caso legittimo: una riga che PARLA della convenzione invece di
# applicarla. Va scritta in chiaro nel documento, cosi' si vede e si puo' cercare.
IGNORE_MARK = "<!-- docs-lint: ignore -->"

# Un token che ha questa forma non e' un simbolo del codice: e' un riferimento git.
GITREF_RE = re.compile(r"^(?:[0-9a-f]{7,40}|origin/[\w./-]+|feature/[\w./-]+|refs/[\w./-]+)$")


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def strip_fences(text: str) -> str:
    """Azzera i blocchi di codice recintati, tenendo la numerazione delle righe."""
    out, inside = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            inside = not inside
            out.append("")
            continue
        out.append("" if inside else line)
    return "\n".join(out)


def code_files(include_meta=True):
    for name in CODE_FILES:
        p = ROOT / name
        if p.is_file():
            yield p
    for d in CODE_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if not include_meta and p.resolve() in META_FILES:
                continue
            if p.is_file() and p.suffix.lower() in CODE_SUFFIXES:
                yield p


def tracked_files():
    """Solo i file versionati: un documento di appunti non tracciato non fa fallire."""
    r = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                       encoding="utf-8", cwd=ROOT)
    if r.returncode != 0:
        return None
    return {(ROOT / line).resolve() for line in r.stdout.splitlines() if line.strip()}


CODE_BLOB = None

def code_blob() -> str:
    global CODE_BLOB
    if CODE_BLOB is None:
        CODE_BLOB = "\n".join(read(p) for p in code_files())
    return CODE_BLOB


def context_files():
    return sorted(CONTEXT.glob("*.md")) if CONTEXT.is_dir() else []


class Report:
    def __init__(self, quiet=False):
        self.errors = []
        self.warns = []
        self.quiet = quiet

    def error(self, check, msg):
        self.errors.append((check, msg))

    def warn(self, check, msg):
        self.warns.append((check, msg))

    def note(self, msg):
        if not self.quiet:
            print(msg)


# ------------------------------------------------------------ 1. feature bandite

def check_banned(rep: Report):
    """La lista dei simboli banditi vive in invariants.md, non qui."""
    inv = CONTEXT / "invariants.md"
    if not inv.is_file():
        # Progetto appena inizializzato: gli invarianti non sono ancora stati scritti.
        # E' un lavoro da fare, non un guasto.
        rep.warn("BANDITE", "docs/context/invariants.md non esiste ancora: "
                            "il controllo 1 e' inattivo finche' non c'e'")
        return
    text = read(inv)
    if not text:
        rep.error("BANDITE", "docs/context/invariants.md esiste ma non e' leggibile")
        return

    m = re.search(r"##\s*Feature bandite\s*\n(.*?)(?=\n##\s|\Z)", text, re.S)
    if not m:
        # Un progetto puo' legittimamente non avere niente di bandito: e' un avviso,
        # non un errore. Errore lo diventa solo se la sezione c'e' ed e' malformata.
        rep.warn("BANDITE", "nessuna sezione '## Feature bandite' in invariants.md: "
                            "il controllo 1 e' inattivo. Se il progetto ha cose che non "
                            "devono tornare, dichiararle li' le rende verificabili")
        return

    para = re.search(r"Nessun riferimento nel codice a:(.*?)(?:\n\s*\n|\n\|)", m.group(1), re.S)
    if not para:
        rep.error("BANDITE", "il paragrafo 'Nessun riferimento nel codice a:' non ha piu' "
                             "la forma attesa: aggiorna docs_lint.py o il documento")
        return

    tokens = re.findall(r"`([^`]+)`", para.group(1))
    if not tokens:
        rep.error("BANDITE", "nessun simbolo bandito estratto dal paragrafo")
        return

    files = list(code_files(include_meta=False))
    hits = 0
    for tok in tokens:
        # Confine a sinistra: senza, `ff.h` trova `poweroff.h`. `*` diventa un glob.
        body = re.escape(tok).replace(r"\*", r"\w*")
        pattern = r"(?<![\w./])" + body
        found = [p for p in files if re.search(pattern, read(p), re.I)]
        if found:
            hits += 1
            where = ", ".join(str(p.relative_to(ROOT)) for p in found[:4])
            rep.error("BANDITE", f"`{tok}` e' ricomparso nel codice: {where}")
    rep.note(f"  simboli banditi controllati: {len(tokens)}  —  ricomparsi: {hits}")


# --------------------------------------------------------- 2. identificatori vivi

PATH_RE = re.compile(r"^[\w./\-]+\.(c|h|py|json|conf|md|txt|yml|yaml|rst|dts|overlay|pem)$")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{3,}$")


def path_exists_anywhere(rel: str) -> bool:
    """
    Un documento puo' citare un file per nome senza il percorso completo: `foo.md`
    che sta in docs/, mentre chi lo cita e' in docs/context/. Cercarlo solo dalla
    radice e solo accanto a chi lo cita produce un falso positivo, e i falsi positivi
    sono il modo in cui un lint smette di essere letto. Regge anche i glob (`epd47/*.h`).
    """
    if (ROOT / rel).exists():
        return True
    try:
        for hit in ROOT.glob("**/" + rel):
            if not any(part in SKIP_DIRS for part in hit.parts):
                return True
    except (ValueError, OSError, IndexError):
        pass
    return False


def _is_prose(tok: str) -> bool:
    """Frammenti di comando, formule e frasi fra backtick non sono identificatori."""
    if " " in tok or "=" in tok or "(" in tok or "×" in tok or "@" in tok:
        return True
    # Segnaposto in un template: topic MQTT, rotta HTTP, nome di file parametrico.
    # `epic/{mac}/data` non e' un percorso che debba esistere sul disco.
    if "{" in tok or "}" in tok or "<" in tok or ">" in tok:
        return True
    # Unita' di misura: due segmenti, il secondo cortissimo e alfabetico — `umm/s`,
    # `km/h`, `entry/s`. La soglia stretta sul secondo segmento evita di scambiare
    # per unita' una cartella vera come `epic/data`.
    seg = tok.split("/")
    if len(seg) == 2 and seg[0].isalpha() and seg[1].isalpha() and len(seg[1]) <= 3:
        return True
    if tok.startswith(("-", ".", "~", "#", "/")):
        return True
    if tok.startswith("build/"):
        return True
    # `Imu_Acq_TryClaim/Release/Current`: scorciatoia di prosa, non un percorso.
    if "/" in tok and not PATH_RE.match(tok):
        if any(seg[:1].isupper() for seg in tok.split("/") if seg):
            return True
    return False


def check_identifiers(rep: Report):
    tokens = {}
    for p in context_files():
        for m in re.finditer(r"`([^`\n]+)`", strip_fences(read(p))):
            tok = m.group(1).strip()
            tokens.setdefault(tok, set()).add(p)

    checked = missing = skipped = 0
    for tok, where in sorted(tokens.items(), key=lambda kv: kv[0]):
        base = tok.rstrip("*/")
        names = ", ".join(sorted(p.name for p in where))

        if (_is_prose(tok) or GITREF_RE.match(tok) or tok.startswith("zephyr/")
                or tok.lower() in NOT_SYMBOLS or base.lower() in NOT_SYMBOLS
                or base in EXTERNAL_SYMBOLS
                or any(k.rstrip("*") in tok for k in EXPECTED_ABSENT)):
            skipped += 1
            continue

        if PATH_RE.match(tok) or "/" in tok:
            checked += 1
            rel = tok.rstrip("/")
            # Relativo a chi lo cita, poi ovunque nell'albero (glob compresi).
            if any((p.parent / rel).exists() for p in where) or path_exists_anywhere(rel):
                continue
            missing += 1
            rep.error("IDENT", f"percorso `{tok}` non esiste  (citato in {names})")
            continue

        if IDENT_RE.match(tok):
            checked += 1
            # Sottostringa, non parola intera: i documenti citano di proposito la coda
            # di un enum lungo (`INFO_ID_STREAM` per
            # USB_CONNECTION_PACKET_INFO_ID_STREAM). E' la regola dell'altitudine:
            # il documento non ripete il prefisso, il controllo lo tollera.
            if base in code_blob():
                continue
            missing += 1
            rep.error("IDENT", f"simbolo `{tok}` non esiste nel codice  (citato in {names})")
        else:
            skipped += 1

    rep.note(f"  token controllati: {checked}  —  non trovati: {missing}  "
             f"—  ignorati (prosa o assenza voluta): {skipped}")


# ------------------------------------------------------------- 3. livelli evidenza

LEVELS = ("verificato", "dedotto", "assunto")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
CONV_RE = re.compile(r"\[(Certo|Probabile|Ipotesi)\]")


def check_evidence(rep: Report):
    counts = {lvl: 0 for lvl in LEVELS}
    for p in context_files():
        text = strip_fences(read(p))
        in_legend = False
        for n, line in enumerate(text.split("\n"), 1):
            for lvl in LEVELS:
                counts[lvl] += len(re.findall(r"\*\*" + lvl + r"\*\*", line))

            # La sezione che DEFINISCE il lessico e' esente dal lessico che definisce.
            if re.match(r"^##\s", line):
                in_legend = "livelli di evidenza" in line.lower()
            if in_legend or IGNORE_MARK in line:
                continue

            if re.search(r"\*\*verificato\*\*", line) and not DATE_RE.search(line):
                rep.error("EVIDENZA",
                          f"{p.name}:{n} — '**verificato**' senza data: "
                          f"un verificato senza data non e' verificabile")

            # collaboration.md e' il file che DEFINISCE il lessico conversazionale.
            m = CONV_RE.search(line)
            if m and p.name != "collaboration.md":
                rep.error("EVIDENZA",
                          f"{p.name}:{n} — [{m.group(1)}] e' il lessico della "
                          f"conversazione: nei documenti si usa "
                          f"verificato/dedotto/assunto")
    rep.note("  cruscotto evidenza in docs/context/:  " +
             "  ".join(f"{lvl}={counts[lvl]}" for lvl in LEVELS))
    if counts["verificato"] == 0:
        rep.warn("EVIDENZA", "nessun '**verificato**' in tutta docs/context/")


# ---------------------------------------------------------------- 4. link e ancore

def slug(title: str) -> str:
    t = title.strip().lower()
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = "".join(ch for ch in t if ch.isalnum() or ch in " -_")
    return t.replace(" ", "-")


LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def check_links(rep: Report):
    anchors = {}
    for p in ROOT.rglob("*.md"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        text = strip_fences(read(p))
        found = set()
        for line in text.split("\n"):
            m = re.match(r"^#{1,6}\s+(.*)$", line)
            if m:
                found.add(slug(m.group(1)))
        for m in re.finditer(r'<a\s+id="([^"]+)"', text):
            found.add(m.group(1))
        anchors[p.resolve()] = found

    targets = [ROOT / "AGENTS.md", ROOT / "CLAUDE.md"]
    targets += context_files() + sorted((ROOT / "docs").glob("*.md"))
    tracked = tracked_files()

    checked = broken = skipped_untracked = skipped_received = 0
    for p in targets:
        if not p.is_file():
            continue
        # Un file di appunti non tracciato non deve far fallire il controllo.
        if tracked is not None and p.resolve() not in tracked and p not in context_files():
            skipped_untracked += 1
            continue
        # Un documento ricevuto non e' nostro da riparare: vedi RECEIVED_DOCS.
        if p.name in RECEIVED_DOCS:
            skipped_received += 1
            continue
        for m in LINK_RE.finditer(strip_fences(read(p))):
            target = m.group(2).strip()
            if target.startswith(("http://", "https://", "mailto:", "#!")):
                continue
            path, _, anchor = target.partition("#")
            checked += 1
            if path == "":
                dest = p.resolve()
            else:
                dest = (p.parent / path).resolve()
                if not dest.exists():
                    broken += 1
                    rep.error("LINK", f"{p.name} -> {target}  (file inesistente)")
                    continue
            if anchor:
                if dest not in anchors:
                    broken += 1
                    rep.error("LINK", f"{p.name} -> {target}  (file non indicizzato)")
                elif anchor not in anchors[dest]:
                    broken += 1
                    rep.error("LINK", f"{p.name} -> {target}  (ancora assente)")
    rep.note(f"  link locali controllati: {checked}  —  rotti: {broken}"
             + (f"  —  file non tracciati saltati: {skipped_untracked}"
                if skipped_untracked else "")
             + (f"  —  documenti ricevuti saltati: {skipped_received}"
                if skipped_received else ""))


# ------------------------------------------------------------------ 5. freschezza

MARKER_RE = re.compile(r"<!--\s*context-verified-at:\s*([0-9a-f]{7,40})\s*-->")


def check_freshness(rep: Report):
    status = CONTEXT / "status.md"
    text = read(status)
    if not text:
        rep.error("FRESCHEZZA", "docs/context/status.md non leggibile")
        return
    m = MARKER_RE.search(text)
    if not m:
        rep.error("FRESCHEZZA",
                  "status.md non ha il marcatore <!-- context-verified-at: <sha> -->: "
                  "senza, la freschezza non e' misurabile")
        return
    sha = m.group(1)
    r = subprocess.run(["git", "log", "--oneline", f"{sha}..HEAD", "--", "src", "drivers"],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    if r.returncode != 0:
        rep.warn("FRESCHEZZA", f"commit {sha} non trovato: il marcatore punta al vuoto")
        return
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    if lines:
        rep.warn("FRESCHEZZA",
                 f"{len(lines)} commit hanno toccato src/ o drivers/ dopo {sha}, "
                 f"a cui status.md dichiara di essere riconciliato:\n      " +
                 "\n      ".join(lines[:8]))
    else:
        rep.note(f"  status.md riconciliato a {sha}: nessun commit su src/ da allora")


# ------------------------------------------------------------------------- main

CHECKS = [
    ("1. FEATURE BANDITE — simboli che non devono tornare", check_banned),
    ("2. IDENTIFICATORI  — cio' che i doc citano esiste ancora", check_identifiers),
    ("3. EVIDENZA        — verificato/dedotto/assunto", check_evidence),
    ("4. LINK E ANCORE   — i rimandi risolvono", check_links),
    ("5. FRESCHEZZA      — status.md rispetto al codice", check_freshness),
]


def main():
    quiet = "--quiet" in sys.argv
    rep = Report(quiet=quiet)
    if not quiet:
        print("=" * 74)
        print("docs_lint — la documentazione per agenti dice ancora il vero?")
        print("=" * 74)
    for title, fn in CHECKS:
        rep.note("")
        rep.note(title)
        try:
            fn(rep)
        except Exception as exc:                      # fail-open sul singolo controllo
            rep.warn("INTERNO", f"{title.split('—')[0].strip()}: {type(exc).__name__}: {exc}")

    print()
    print("=" * 74)
    if rep.errors:
        print(f"ERRORI: {len(rep.errors)}")
        for check, msg in rep.errors:
            print(f"  [{check}] {msg}")
    if rep.warns:
        print(f"AVVISI: {len(rep.warns)}")
        for check, msg in rep.warns:
            print(f"  [{check}] {msg}")
    if not rep.errors and not rep.warns:
        print("Tutto a posto.")
    elif not rep.errors:
        print("Nessun errore. Gli avvisi non fanno fallire il controllo.")
    print("=" * 74)
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
