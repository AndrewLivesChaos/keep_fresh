#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
docs_lint — controlla che la documentazione per agenti dica ancora il vero.

Non guarda il prodotto: guarda i documenti che lo descrivono.

Sei controlli:

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
  5. FRESCHEZZA       — quanti commit hanno toccato il codice dopo il punto in cui
                        status.md dichiara di essere riconciliato.
  6. PESO             — quanto testo l'hook di avvio mette nel contesto a ogni
                        sessione. Avvisa se i blocchi session-start superano il tetto
                        di config.toml: in quel caso l'hook inietta solo l'indice.

Dove sta il codice non e' scritto qui: lo rileva scripts/context_core.py a ogni
esecuzione. Le eccezioni scritte a mano stanno in docs/context/config.toml.

Uso:   python scripts/docs_lint.py [--quiet]
Esce 0 se non ci sono errori, 1 se ce n'e' almeno uno. I WARN non fanno fallire.
"""

import io
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Importare context_core non deve lasciare __pycache__ nel repository.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import context_core as core  # noqa: E402

# --------------------------------------------------------------------------- setup

ROOT = core.repo_root() or Path(__file__).resolve().parent.parent
CONTEXT = ROOT / core.CONTEXT_DIR
CONFIG, CONFIG_ERROR = core.load_config(ROOT)

EXPECTED_ABSENT = core.config_table(CONFIG, "lint", "expected_absent")
EXTERNAL_SYMBOLS = core.config_table(CONFIG, "lint", "external_symbols")
RECEIVED_DOCS = core.config_table(CONFIG, "lint", "received_docs")

# Parole che sembrano identificatori ma sono prosa. Qui c'e' solo il nucleo indipendente
# dal progetto; il resto sta in [lint.not_symbols] della configurazione.
NOT_SYMBOLS_CORE = {
    "true", "false", "null", "none", "void", "main", "data", "text", "info",
    "test", "build", "error", "warning", "debug", "http", "https", "json", "yaml",
    "toml", "git", "origin", "HEAD", "grep", "python", "node", "docker",
    "feat", "fix", "docs", "chore", "refactor", "style", "perf",
    # Parole usate dallo scheletro di status.md: senza, il primo giro del lint
    # segnala il file che l'inizializzatore ha appena scritto.
    "esito", "chi", "prova", "corrente", "regola", "dove", "livello", "nota",
    "head", "cronologia", "stato", "lavoro", "commit",
    "verificato", "dedotto", "assunto",
}
# Il confronto avviene sul token gia' abbassato a minuscolo: una voce in maiuscolo non
# combacerebbe mai, e il difetto resterebbe invisibile. Si normalizza qui, una volta.
NOT_SYMBOLS = {w.lower() for w in NOT_SYMBOLS_CORE | set(
    core.config_table(CONFIG, "lint", "not_symbols"))}

# Directory da non attraversare quando si cerca un file citato per nome.
SKIP_DIRS = core.NON_SOURCE_DIRS - {"docs", "doc"} | {".git"}

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


def tracked_files():
    """Solo i file versionati: un documento di appunti non tracciato non fa fallire."""
    ok, out = core.run_git(ROOT, "ls-files")
    if not ok:
        return None
    return {(ROOT / line).resolve() for line in out.splitlines() if line.strip()}


CODE_BLOB = None

def code_blob() -> str:
    global CODE_BLOB
    if CODE_BLOB is None:
        CODE_BLOB = "\n".join(read(ROOT / rel) for rel in core.tree_files(ROOT, CONFIG))
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


# ---------------------------------------------------------------- 0. configurazione

def check_config(rep: Report):
    if CONFIG_ERROR:
        rep.error("CONFIG", CONFIG_ERROR + " — le eccezioni scritte li' sono ignorate")
    files = core.code_files(ROOT, CONFIG)
    _, labels = core.code_scope(ROOT, CONFIG)
    if labels:
        shown = ", ".join(labels[:12]) + (" …" if len(labels) > 12 else "")
        rep.note(f"  codice rilevato: {len(files)} file in {shown}")
    else:
        rep.note("  codice rilevato: nessuno, per ora. I controlli sul codice restano "
                 "inattivi finche' non ce n'e'.")


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

    para = re.search(r"Nessun riferimento nel codice a:(.*?)(?:\n\s*\n|\n\||\Z)",
                     m.group(1), re.S)
    if not para:
        rep.error("BANDITE", "il paragrafo 'Nessun riferimento nel codice a:' non ha piu' "
                             "la forma attesa: aggiorna docs_lint.py o il documento")
        return

    tokens = re.findall(r"`([^`]+)`", para.group(1))
    if not tokens:
        rep.error("BANDITE", "nessun simbolo bandito estratto dal paragrafo")
        return

    # Il codice del progetto, senza i file di questo impianto: il lint e l'inizializzatore
    # contengono i nomi banditi per poterli cercare, e si accuserebbero da soli.
    files = [ROOT / rel for rel in core.code_files(ROOT, CONFIG)]
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

# Un elenco chiuso di estensioni, non "qualunque cosa dopo un punto": altrimenti
# `sys.stdout` o `obj.field` diventerebbero percorsi inesistenti.
PATH_RE = re.compile(
    r"^[\w./\-]+\.(?:c|h|cc|cpp|hpp|cs|m|mm|swift|kt|java|py|rb|php|go|rs|js|jsx|ts|tsx"
    r"|vue|svelte|sh|ps1|sql|html|css|scss|json|toml|yml|yaml|ini|cfg|conf|xml|md|rst"
    r"|txt|cmake|dts|dtsi|overlay|pem|lock|env|gradle|csproj|sln)$")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{3,}$")


def path_exists_anywhere(rel: str) -> bool:
    """
    Un documento puo' citare un file per nome senza il percorso completo: `foo.md`
    che sta in docs/, mentre chi lo cita e' in docs/context/. Cercarlo solo dalla
    radice e solo accanto a chi lo cita produce un falso positivo, e i falsi positivi
    sono il modo in cui un lint smette di essere letto. Regge anche i glob (`lib/*.h`).
    """
    if (ROOT / rel).exists():
        return True
    try:
        for hit in ROOT.glob("**/" + rel):
            if not any(part in SKIP_DIRS for part in hit.relative_to(ROOT).parts):
                return True
    except (ValueError, OSError, IndexError, NotImplementedError):
        pass
    return False


def _is_prose(tok: str) -> bool:
    """Frammenti di comando, formule e frasi fra backtick non sono identificatori."""
    if " " in tok or "=" in tok or "(" in tok or "×" in tok or "@" in tok:
        return True
    # Segnaposto in un template: topic, rotta HTTP, nome di file parametrico.
    # `epic/{mac}/data` non e' un percorso che debba esistere sul disco.
    if "{" in tok or "}" in tok or "<" in tok or ">" in tok:
        return True
    # Unita' di misura: due segmenti, il secondo cortissimo e alfabetico — `m/s`,
    # `km/h`, `entry/s`. La soglia stretta sul secondo segmento evita di scambiare
    # per unita' una cartella vera come `epic/data`.
    seg = tok.split("/")
    if len(seg) == 2 and seg[0].isalpha() and seg[1].isalpha() and len(seg[1]) <= 3:
        return True
    if tok.startswith(("-", ".", "~", "#", "/")):
        return True
    if tok.startswith("build/"):
        return True
    # `Acq_TryClaim/Release/Current`: scorciatoia di prosa, non un percorso.
    if "/" in tok and not PATH_RE.match(tok):
        if any(seg[:1].isupper() for seg in tok.split("/") if seg):
            return True
    return False


def _is_external(tok: str, base: str) -> bool:
    if base in EXTERNAL_SYMBOLS:
        return True
    return any(k.endswith("/") and tok.startswith(k) for k in EXTERNAL_SYMBOLS)


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

        if (_is_prose(tok) or GITREF_RE.match(tok)
                or tok.lower() in NOT_SYMBOLS or base.lower() in NOT_SYMBOLS
                or _is_external(tok, base)
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
            # di un nome lungo (`INFO_ID_STREAM` per PACKET_INFO_ID_STREAM). E' la
            # regola dell'altitudine: il documento non ripete il prefisso.
            if base in code_blob():
                continue
            missing += 1
            rep.error("IDENT", f"simbolo `{tok}` non esiste nel codice  (citato in {names})")
        else:
            skipped += 1

    rep.note(f"  token controllati: {checked}  —  non trovati: {missing}  "
             f"—  ignorati (prosa o assenza voluta): {skipped}")


# ------------------------------------------------------------- 3. livelli evidenza

LEVELS = core.EVIDENCE_LEVELS
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
        if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
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

    # I file di ingresso degli agenti stanno nella radice e contengono quasi tutti i
    # link: si prendono tutti i .md della radice, non un elenco di nomi da aggiornare.
    targets = sorted(ROOT.glob("*.md"))
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
        # Un documento ricevuto non e' nostro da riparare: vedi [lint.received_docs].
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

def check_freshness(rep: Report):
    status = CONTEXT / "status.md"
    text = read(status)
    if not text:
        rep.error("FRESCHEZZA", "docs/context/status.md non esiste o non e' leggibile")
        return
    sha = core.read_marker(text)
    if not sha:
        if core.head_sha(ROOT) is None:
            # Nessun commit ancora: non c'e' uno sha a cui ancorarsi, ed e' normale.
            rep.warn("FRESCHEZZA", "il repository non ha ancora un commit: la freschezza "
                                   "si misura dal primo. Dopo il commit rilancia "
                                   "agent_context_init.py, che aggiunge il marcatore")
            return
        rep.error("FRESCHEZZA",
                  "status.md non ha il marcatore <!-- context-verified-at: <sha> -->: "
                  "senza, la freschezza non e' misurabile")
        return
    specs, labels = core.code_scope(ROOT, CONFIG)
    if not specs:
        rep.note(f"  status.md riconciliato a {sha}; nessun codice da sorvegliare, per ora")
        return
    ok, lines = core.commits_since(ROOT, sha, specs)
    if not ok:
        rep.warn("FRESCHEZZA", f"commit {sha} non trovato: il marcatore punta al vuoto")
        return
    where = ", ".join(labels[:8]) + (" …" if len(labels) > 8 else "")
    if lines:
        rep.warn("FRESCHEZZA",
                 f"{len(lines)} commit hanno toccato il codice ({where}) dopo {sha}, "
                 f"a cui status.md dichiara di essere riconciliato:\n      " +
                 "\n      ".join(lines[:8]))
    else:
        rep.note(f"  status.md riconciliato a {sha}: nessun commit sul codice da allora")


# ------------------------------------------------------------------------- main

# ---------------------------------------------------------------- 6. peso all'avvio

def check_weight(rep: Report):
    """
    Cosa entra nel contesto dell'agente a ogni avvio per opera di questo impianto. Solo
    caratteri: il lint non ha un tokenizer, i token veri li misura context_cost.py.
    """
    inj = core.build_injection(ROOT, CONFIG)
    if inj is None:
        rep.note("  nessun status.md: l'hook di avvio non inietta niente")
    else:
        rep.note(f"  iniezione di avvio: {len(inj['text'])} caratteri  —  blocchi "
                 f"session-start: {inj['blocks_chars']} su un tetto di {inj['budget']}")
        if inj["reduced"]:
            rep.warn("PESO", f"i blocchi session-start di {core.STATUS_FILE} fanno "
                             f"{inj['blocks_chars']} caratteri, oltre il tetto di "
                             f"{inj['budget']}: l'hook inietta solo il loro indice. "
                             f"Riportali sotto il tetto: vedi la guida, «status.md "
                             f"invecchia male».")
    for name in ("AGENTS.md", "CLAUDE.md"):
        p = ROOT / name
        if p.is_file():
            rep.note(f"  {name}: {len(read(p))} caratteri, caricati a ogni sessione "
                     f"(piu' cio' che importa)")
    rep.note("  i token veri: python scripts/context_cost.py")


CHECKS = [
    ("0. CONFIGURAZIONE  — cosa viene considerato codice", check_config),
    ("1. FEATURE BANDITE — simboli che non devono tornare", check_banned),
    ("2. IDENTIFICATORI  — cio' che i doc citano esiste ancora", check_identifiers),
    ("3. EVIDENZA        — verificato/dedotto/assunto", check_evidence),
    ("4. LINK E ANCORE   — i rimandi risolvono", check_links),
    ("5. FRESCHEZZA      — status.md rispetto al codice", check_freshness),
    ("6. PESO            — cosa entra nel contesto a ogni avvio", check_weight),
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
