#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agent_context_init — prepara in un repo la struttura di contesto/memoria per agenti.

Che cosa fa e che cosa NON fa
-----------------------------
FA la meccanica: crea le cartelle, scrive il lint dei documenti, gli hook e la loro
configurazione con l'interprete giusto per la piattaforma, aggiorna .gitignore, semina
uno scheletro di status.md e stampa il prompt da dare all'agente.

NON crea il contesto. I documenti nascono solo leggendo il repo e chiedendo all'utente
le cose che nel repo non ci sono: stato del lavoro, decisioni prese fuori dal codice,
verifiche fatte a mano. Quello e' il lavoro dell'agente, e questo script gli prepara il
terreno.

Uso
---
    python agent_context_init.py                 # dentro il repo da inizializzare
    python agent_context_init.py --dry-run       # dice cosa farebbe, non tocca niente
    python agent_context_init.py --force         # sovrascrive i file gia' presenti
    python agent_context_init.py --pack          # rigenera il payload dal repo corrente

Funziona su Windows e macOS/Linux: un unico file Python, nessuna dipendenza. L'unica
differenza fra piattaforme e' il nome dell'interprete degli hook ("python" su Windows,
"python3" altrove), e per questo gli hook si dichiarano in .claude/settings.local.json,
che git non traccia: ogni macchina tiene il suo. Il rovescio e' che un clone appena
fatto non ha hook finche' non ci si lancia dentro questo script una volta.

Il payload sta in fondo a questo file, in chiaro. `--pack`, eseguito in un progetto di
riferimento, lo rigenera dai file veri: e' cosi' che si evita la copia che diverge.
Il sentinella compare DUE volte nel sorgente (nella riga che lo definisce, e in fondo):
si taglia sempre sull'ULTIMA, o lo script si tronca da solo. E' successo davvero.
"""

import argparse
import io
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

# La console di Windows non e' UTF-8: senza questo, un trattino lungo esce come "?".
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SENTINEL = "# ==== PAYLOAD (rigenerabile con --pack, non modificare a mano) ===="
FILE_HDR = "# ---- AGENT-CONTEXT-FILE: "
FILE_END = " ----"

# I file veri da cui --pack rigenera il payload, nel progetto di riferimento.
PACK_FILES = [
    "scripts/docs_lint.py",
    ".claude/hooks/hooklib.py",
    ".claude/hooks/session_start.py",
    ".claude/hooks/stop_check.py",
    "docs/agent_docs_guide.md",
]

GITIGNORE_LINES = [".claude/settings.local.json"]

# --------------------------------------------------------------- taratura neutra
#
# I file del payload arrivano dal progetto di riferimento, quindi porterebbero le sue
# costanti: estensioni di quel linguaggio, divieti di quel dominio, lessico di quella
# lingua. Su un altro repo sono sbagliate per costruzione, e lasciarle scaricando la
# ritaratura sull'agente fa sembrare portabile una cosa che non lo e'.
#
# Percio' --pack sostituisce il blocco delimitato con questi valori neutri, e
# l'inizializzatore ne riempie la parte RILEVABILE guardando il repo di destinazione.
# Cio' che non e' rilevabile — divieti e lessico — parte vuoto, per costruzione.

TUNING_BEGIN = "# ==== TARATURA DEL PROGETTO (inizio) ===="
TUNING_END = "# ==== TARATURA DEL PROGETTO (fine) ===="

# Estensioni sorgente di uso comune, indipendenti dal linguaggio. Servono solo come
# rete di sicurezza: l'inizializzatore le sostituisce con quelle davvero presenti.
DEFAULT_SUFFIXES = sorted({
    ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".m", ".mm", ".swift", ".kt", ".java",
    ".py", ".rb", ".php", ".go", ".rs", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
    ".sh", ".ps1", ".sql", ".html", ".css", ".scss",
    ".json", ".yml", ".yaml", ".toml", ".ini", ".conf", ".cfg", ".txt", ".cmake",
})

# Estensioni che non sono codice: non entrano nella rilevazione.
NON_SOURCE_SUFFIXES = {
    ".md", ".rst", ".adoc", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".webp", ".bmp", ".tiff", ".mp3", ".mp4", ".wav", ".zip", ".gz", ".tar", ".7z",
    ".bin", ".hex", ".elf", ".exe", ".dll", ".so", ".dylib", ".lock", ".log", ".csv",
    ".pem", ".der", ".crt", ".key",
    # Font e binari incorporati: sono asset, non sorgenti.
    ".ttf", ".otf", ".woff", ".woff2", ".eot", ".wasm", ".jar", ".class",
    ".o", ".a", ".obj", ".lib", ".pyc", ".pyo", ".db", ".sqlite", ".sqlite3",
}

# Directory che non contengono codice del progetto, per quanto pieni di file.
NON_SOURCE_DIRS = {
    "docs", "doc", "build", "dist", "out", "target", "node_modules", "vendor",
    "third_party", "external", ".git", ".github", ".vscode", ".idea", "__pycache__",
    "venv", ".venv", "firmware", "site-packages",
}

NEUTRAL_LINT_TUNING = '''# Percorsi che compongono "il codice": tutto cio' che una rinomina toccherebbe.
# RILEVATI dall'inizializzatore guardando questo repo. Correggili se ha sbagliato.
CODE_DIRS = {code_dirs}
CODE_FILES = {code_files}
CODE_SUFFIXES = {code_suffixes}
SKIP_DIRS = {skip_dirs}
# I file "meta" contengono la lista dei simboli banditi per poterla applicare o
# trasportare: vanno esclusi dal controllo 1, o si accusano da soli. Restano invece
# nell'albero per tutti gli altri controlli, altrimenti i simboli che definiscono
# risulterebbero inesistenti.
SELF = Path(__file__).resolve()
# L'inizializzatore puo' stare ovunque — di solito nella radice, dove lo si copia —
# quindi si cerca per nome invece di dare per scontato che sia in scripts/.
META_FILES = {{SELF}} | {{p.resolve() for p in ROOT.rglob("agent_context_init.py")
                       if ".git" not in p.parts}}

# Token citati nei documenti che NON devono esistere nel codice, per costruzione:
# un identificatore ritirato, un modulo rimosso, il nome di un altro repository.
# VUOTO DI PROPOSITO: si riempie guardando i falsi positivi del primo giro.
# Ogni voce porta il motivo, e senza motivo non si aggiunge niente — o in sei mesi
# questa e' una discarica che silenzia anche i controlli veri.
EXPECTED_ABSENT = {{
    # "NOME_RITIRATO": "perche' non deve esistere",
}}

# Simboli che esistono, ma in una libreria o in un framework, non in questo albero.
# Sono citati nei documenti perche' spiegano un vincolo esterno. VUOTO DI PROPOSITO.
EXTERNAL_SYMBOLS = {{
    # "API_DELLA_LIBRERIA": "di quale libreria, e perche' e' citata",
}}

# Parole che sembrano identificatori ma sono prosa, unita' di misura o nomi esterni.
# Qui c'e' solo il nucleo indipendente dalla lingua e dal dominio: il resto va
# aggiunto guardando i falsi positivi del primo giro, ed e' specifico della lingua
# in cui sono scritti i documenti.
NOT_SYMBOLS = {{
    "true", "false", "null", "none", "void", "main", "data", "text", "info",
    "test", "build", "error", "warning", "debug", "http", "https", "json", "yaml",
    "git", "origin", "HEAD", "grep", "python", "node", "docker",
    "feat", "fix", "docs", "chore", "refactor", "style", "perf",
    # Parole usate dallo scheletro di status.md: senza, il primo giro del lint
    # segnala il file che l'inizializzatore ha appena scritto.
    "esito", "chi", "prova", "corrente", "regola", "dove", "livello", "nota",
    "head", "cronologia", "stato", "lavoro", "commit",
    "verificato", "dedotto", "assunto",
}}
'''

NEUTRAL_HOOK_TUNING = '''# Le directory il cui cambiamento richiede che lo stato del lavoro venga aggiornato.
# RILEVATE dall'inizializzatore guardando questo repo. Correggile se ha sbagliato.
CODE_PATHS = {code_paths}

# Il documento che tiene lo stato corrente del lavoro.
STATUS_FILE = "docs/context/status.md"

# La directory dei documenti di contesto, per il cruscotto dei livelli di evidenza.
CONTEXT_DIR = "docs/context"

# I livelli di evidenza, nella forma esatta in cui compaiono nei documenti.
EVIDENCE_LEVELS = ["verificato", "dedotto", "assunto"]
'''

STATUS_SKELETON = """# Stato del lavoro
{marker}
**Ultimo aggiornamento: {today}.**

> Il marcatore `context-verified-at` qui sopra e' il commit fino al quale questo
> documento e' stato **riconciliato con il codice**. Chi lo riconcilia lo riporta a
> `HEAD`. `python scripts/docs_lint.py` dice quanti commit hanno toccato il codice da
> allora: e' l'unica misura oggettiva di quanto questo file sia invecchiato.
>
> I blocchi delimitati dai marcatori `session-start` sono le sezioni che l'hook di avvio
> inietta in contesto a ogni sessione. Spostarli cambia cosa l'agente vede appena apre —
> e cosa costa in token a ogni avvio.

> **Se riprendi da qui, salta alla sezione 1.** E' l'unica che descrive lo stato
> **corrente**. Tutto cio' che segue e' cronologia.

## Livelli di evidenza

In questo file ogni affermazione porta il modo in cui e' nota. Non si scrive che una cosa
funziona: si scrive **come lo sappiamo**.

| Livello | Significato |
|---|---|
| **verificato** | un comando eseguito, con il suo esito e la data — o una misura reale |
| **dedotto** | un ragionamento fondato sul codice, che nessuno ha ancora messo alla prova |
| **assunto** | un buco dichiarato: non lo sappiamo |

Le tre parole si scrivono **sempre in grassetto e sempre cosi'**, perche' `git grep -c`
diventi un cruscotto e il lint possa fallire se un verificato non porta la data.

---

## 1. Da sapere prima di riprendere

<!-- session-start: begin -->

### 1.1 Cosa blocca

*(da riempire: cosa impedisce oggi di considerare il lavoro rilasciabile. Se non c'e'
niente, scrivilo — un elenco vuoto e' un'informazione.)*

### 1.2 Difetti noti, aperti

*(da riempire, ognuno col suo livello di evidenza)*

<!-- session-start: end -->

### 1.3 Cosa non e' mai stato verificato

| Cosa | Livello | Nota |
|---|---|---|

### 1.4 Registro di collaudo

Non e' una lista di cose da fare: e' il registro dove si scrive l'esito.
`Esito`: `OK` / `KO` / `-` (non eseguita). Un `OK` senza data e senza nome non vale.

| # | Prova | Esito | Data | Chi |
|---|---|---|---|---|

---

## 2. Cronologia

Dal piu' recente. Le voci risolte si **barrano**, non si cancellano:
`~~voce~~ - FATTO il <data>`.
"""

PROMPT = """Leggi docs/agent_docs_guide.md ed eseguilo su questo repository.
Sono istruzioni operative, non la descrizione di un altro progetto.

Prima di scrivere, chiedimi quello che non e' deducibile dal repo: stato del lavoro,
decisioni prese fuori dal codice, verifiche fatte a mano.

In scripts/ e .claude/ trovi gia' il lint e gli hook, e NON vanno riscritti. Le costanti
che dicono dove sta il codice sono gia' state rilevate e scritte: toccale solo se sono
sbagliate. Restano vuote di proposito NOT_SYMBOLS, EXPECTED_ABSENT ed EXTERNAL_SYMBOLS:
riempile guardando i falsi positivi del primo giro, con il motivo scritto per ogni voce.

Fai girare `python scripts/docs_lint.py` e mostrami l'output vero prima di dichiarare
concluso. Al primo giro sara' rumoroso: correggi prima i CONTROLLI, poi i documenti. Una
segnalazione che descrive un difetto vero — un riferimento a una rinomina mai fatta, un
simbolo sparito — non va messa a tacere: va registrata come lavoro aperto."""


# --------------------------------------------------------------------------- payload

def own_source() -> str:
    return Path(__file__).read_text(encoding="utf-8")


def split_on_sentinel(src: str):
    """
    Sempre sull'ULTIMA occorrenza. La prima e' la riga che definisce il sentinella:
    tagliare li' tronca lo script a meta' di una stringa e lo rende non eseguibile.
    """
    if src.count(SENTINEL) < 2:
        return None, None
    head, _, tail = src.rpartition(SENTINEL)
    return head, tail


def load_payload() -> dict:
    _, body = split_on_sentinel(own_source())
    if body is None:
        return {}
    files, current, buf = {}, None, []
    for line in body.split("\n"):
        if line.startswith(FILE_HDR) and line.rstrip().endswith(FILE_END):
            if current:
                files[current] = "\n".join(buf).strip("\n") + "\n"
            current = line[len(FILE_HDR):].rstrip()[:-len(FILE_END)].strip()
            buf = []
        elif current is not None:
            buf.append(line[2:] if line.startswith("# ") else
                       ("" if line == "#" else line))
    if current:
        files[current] = "\n".join(buf).strip("\n") + "\n"
    return files


def replace_tuning(text: str, neutral: str):
    """Sostituisce il blocco di taratura con quello dato. Ritorna (testo, fatto?)."""
    i = text.find(TUNING_BEGIN)
    j = text.find(TUNING_END)
    if i < 0 or j < 0 or j < i:
        return text, False
    head = text[:i + len(TUNING_BEGIN)]
    return head + "\n" + neutral + text[j:], True


def detect_project(root: Path) -> dict:
    """
    Guarda il repo di destinazione e deduce dove sta il codice e che forma ha.

    Serve perche' le costanti del progetto di riferimento sono sbagliate ovunque
    altro: `.dts` non significa niente in un progetto TypeScript. Si parte dai file
    TRACCIATI, non dal filesystem: build, cache e dipendenze non sono codice, e git
    sa gia' distinguerli.
    """
    r = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(root))
    files = [Path(l) for l in r.stdout.splitlines() if l.strip()] if r.returncode == 0 else []

    def ignored_dir(name: str) -> bool:
        # Le directory che iniziano con un punto sono configurazione di strumenti, non
        # codice del progetto: .serena, .vscode, .devcontainer, .husky... Elencarle a
        # una a una e' una rincorsa persa, perche' ogni tool nuovo ne porta una. L'unica
        # eccezione e' .claude, che qui contiene gli hook e va davvero controllata.
        return name in NON_SOURCE_DIRS or (name.startswith(".") and name != ".claude")

    suffixes, dirs, root_files = {}, {}, []
    for f in files:
        if any(ignored_dir(part) for part in f.parts[:-1]):
            continue
        suf = f.suffix.lower()
        if not suf or suf in NON_SOURCE_SUFFIXES:
            continue
        suffixes[suf] = suffixes.get(suf, 0) + 1
        if len(f.parts) == 1:
            root_files.append(f.name)
        else:
            top = f.parts[0]
            if not ignored_dir(top):
                dirs[top] = dirs.get(top, 0) + 1

    # Estensioni marginali (uno o due file) sono spesso configurazione sparsa: si
    # tengono comunque, perche' escluderle creerebbe falsi positivi nel controllo 2.
    keep_suf = sorted(suffixes) or sorted(DEFAULT_SUFFIXES)
    # Le directory sorgente, dalla piu' popolosa: chi ha un solo file di solito e'
    # un accessorio, ma tenerlo costa poco e perderlo costa un falso positivo.
    keep_dirs = [d for d, _ in sorted(dirs.items(), key=lambda kv: -kv[1])]
    # Il ripiego va deciso PRIMA di aggiungere .claude: altrimenti in un repo vuoto
    # l'unica directory sorgente risulta .claude, e il lint guarda solo se' stesso.
    if not keep_dirs:
        keep_dirs = ["src"]
    if ".claude" not in keep_dirs:
        keep_dirs.append(".claude")

    return {
        "code_dirs": keep_dirs,
        "code_files": sorted(set(root_files)),
        "code_suffixes": keep_suf,
        # Cio' che il hook Stop sorveglia: le sorgenti vere, non gli script di supporto.
        "code_paths": [d for d in keep_dirs if d not in (".claude", "scripts")] or ["src"],
    }


def pack(root: Path) -> int:
    """Rigenera il payload dai file veri del progetto di riferimento."""
    blocks = []
    neutrals = {
        "scripts/docs_lint.py": NEUTRAL_LINT_TUNING.format(
            code_dirs='["src"]', code_files="[]",
            code_suffixes="{" + ", ".join(f'"{s}"' for s in DEFAULT_SUFFIXES) + "}",
            skip_dirs='{"build", ".git", "__pycache__", "node_modules", "dist"}'),
        ".claude/hooks/hooklib.py": NEUTRAL_HOOK_TUNING.format(code_paths='["src"]'),
    }
    for rel in PACK_FILES:
        p = root / rel
        if not p.is_file():
            print(f"  MANCA  {rel} — payload non rigenerato")
            return 1
        text = p.read_text(encoding="utf-8")
        if rel in neutrals:
            text, done = replace_tuning(text, neutrals[rel])
            if not done:
                print(f"  {rel} non ha i marcatori di taratura: la sua taratura di "
                      f"progetto finirebbe nel payload. Aggiungili e rilancia.")
                return 1
            print(f"  neutralizzata la taratura in  {rel}")
        if FILE_HDR in text:
            print(f"  {rel} contiene l'intestazione del payload: non impacchettabile")
            return 1
        commented = "\n".join(("# " + l) if l else "#" for l in text.split("\n"))
        blocks.append(f"{FILE_HDR}{rel}{FILE_END}\n{commented}")
        print(f"  impacchettato  {rel}  ({len(text)} byte)")

    head, _ = split_on_sentinel(own_source())
    if head is None:
        print("  il sentinella compare meno di due volte: sorgente non integro",
              file=sys.stderr)
        return 1
    Path(__file__).write_text(head + SENTINEL + "\n" + "\n".join(blocks) + "\n",
                              encoding="utf-8", newline="\n")

    # Il file appena riscritto deve ancora eseguirsi e rileggere il proprio payload.
    # Senza questo controllo, --pack puo' lasciare uno script rotto e dire "fatto".
    r = subprocess.run([sys.executable, str(Path(__file__)), "--self-test"],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print("  IL FILE RIGENERATO NON SI ESEGUE:\n" + (r.stderr or r.stdout),
              file=sys.stderr)
        return 1
    print(f"\nPayload rigenerato e riletto: {r.stdout.strip()}")

    ok = smoke_test()
    return 0 if ok else 1


def smoke_test() -> bool:
    """
    Monta un repo finto con SOLO cio' che l'inizializzatore genera, e ci fa girare il
    lint che l'inizializzatore genera.

    Esiste perche' due volte di fila lo scheletro di status.md ha fatto fallire il
    proprio lint su una parola che il lessico neutro non conteneva (`Esito`, poi
    `HEAD`). Correggere l'istanza non chiude la classe: solo eseguirlo davvero lo fa.
    Uno strumento che accusa il file che ha appena scritto non viene creduto.
    """
    import shutil
    import tempfile

    payload = load_payload()
    tmp = Path(tempfile.mkdtemp(prefix="agent-context-smoke-"))
    try:
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        run = lambda *a: subprocess.run(a, cwd=str(tmp), capture_output=True,
                                        text=True, encoding="utf-8", env=env)
        run("git", "init", "-q", ".")
        (tmp / "src").mkdir()
        (tmp / "src" / "main.c").write_text("int main(void){return 0;}\n", encoding="utf-8")
        for rel in ("scripts/docs_lint.py", ".claude/hooks/hooklib.py"):
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(payload[rel], encoding="utf-8", newline="\n")
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", "base")
        sha = run("git", "rev-parse", "--short", "HEAD").stdout.strip()

        doc = tmp / "docs" / "context"
        doc.mkdir(parents=True, exist_ok=True)
        (doc / "status.md").write_text(
            STATUS_SKELETON.format(marker=f"\n<!-- context-verified-at: {sha} -->\n",
                                   today=date.today().isoformat()),
            encoding="utf-8", newline="\n")

        r = subprocess.run([sys.executable, "scripts/docs_lint.py"], cwd=str(tmp),
                           capture_output=True, text=True, encoding="utf-8", env=env)
        if r.returncode == 0:
            print("Prova a vuoto: lo scheletro generato passa il lint generato.")
            return True
        print("\nPROVA A VUOTO FALLITA — cio' che questo script genera non passa il\n"
              "controllo che questo script genera. Payload scritto ma da correggere:\n",
              file=sys.stderr)
        for line in r.stdout.splitlines():
            if line.strip().startswith("[") or line.startswith("ERRORI"):
                print("  " + line.strip(), file=sys.stderr)
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------------------- utili

def git(root, *args) -> str:
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=str(root))
        return r.stdout.strip() if r.returncode == 0 else ""
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


class Writer:
    """
    Due categorie di file, e la distinzione e' quella che rende --force sicuro.

    GESTITI (lint, hook, guida): li possiede questo script. Sovrascriverli con --force
    e' il modo previsto di AGGIORNARE un repo gia' inizializzato quando la versione di
    riferimento migliora.

    SEME (docs/context/status.md): e' solo un punto di partenza, e da li' in poi
    contiene lavoro umano. Non si sovrascrive MAI, nemmeno con --force: rigenerarlo
    vorrebbe dire cancellare lo stato del progetto per aggiornare uno script.
    """

    def __init__(self, root: Path, force: bool, dry: bool):
        self.root, self.force, self.dry = root, force, dry
        self.written, self.skipped, self.protected = [], [], []

    def put(self, rel: str, content: str, seed: bool = False) -> None:
        p = self.root / rel
        if p.exists():
            if seed:
                self.protected.append(rel)
                return
            if not self.force:
                self.skipped.append(rel)
                return
        self.written.append(rel)
        if self.dry:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")


HOOK_EVENTS = [("SessionStart", "session_start.py"), ("Stop", "stop_check.py")]


def hook_entry(interp: str, script: str) -> dict:
    return {"hooks": [{
        "type": "command",
        "command": f'{interp} "$CLAUDE_PROJECT_DIR/.claude/hooks/{script}"',
        "timeout": 20,
    }]}


# I nomi con cui un hook puo' invocare Python. Solo un comando che comincia cosi' viene
# riscritto: un percorso assoluto o un virtualenv sono una scelta di chi ce li ha messi.
INTERP_RE = re.compile(r"^\s*(?:python3|python|py)(?:\s+-3)?(?=\s)")


def retarget_hooks(entries: list, interp: str, script: str):
    """
    Riscrive l'interprete degli hook gia' presenti che invocano `script`.

    Serve quando il repo e' stato inizializzato su un'altra piattaforma e poi clonato
    qui: il comando c'e' e punta al file giusto, ma chiama un interprete che su questa
    macchina non esiste — `python3` su Windows, `python` su macOS. Gli hook sono
    fail-open, quindi nessuno protesta: i controlli semplicemente non avvengono piu'.

    Ritorna (riscritti, estranei). Gli estranei sono comandi che invocano i nostri
    script con qualcosa che non riconosciamo: si contano per segnalarli, non si toccano.
    """
    riscritti = estranei = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        inner = entry.get("hooks")
        for h in inner if isinstance(inner, list) else []:
            if not isinstance(h, dict):
                continue
            cmd = h.get("command")
            if not isinstance(cmd, str) or script not in cmd:
                continue
            m = INTERP_RE.match(cmd)
            if not m:
                estranei += 1
                continue
            nuovo = interp + cmd[m.end():]
            if nuovo != cmd:
                h["command"] = nuovo
                riscritti += 1
    return riscritti, estranei


def our_entry(entry, scripts) -> bool:
    """L'entry registra uno dei NOSTRI hook?"""
    if not isinstance(entry, dict):
        return False
    inner = entry.get("hooks")
    for h in inner if isinstance(inner, list) else []:
        if isinstance(h, dict) and isinstance(h.get("command"), str):
            if any(s in h["command"] for s in scripts):
                return True
    return False


def unhook_shared(root: Path, dry: bool) -> str:
    """
    Toglie i NOSTRI hook dal settings.json condiviso, se ce li ha ancora.

    Fino alla versione precedente di questo script ci stavano li'. Adesso stanno nel
    file locale, e dichiararli in tutti e due NON e' innocuo: girano due volte.
    (Provato su Claude Code 2.1.269: sonda in entrambi i file, due esecuzioni.)

    Il file condiviso e' tracciato da git, quindi la rimozione finisce nel diff
    dell'utente: va dichiarata, non fatta di nascosto. Gli hook di altri restano.
    """
    p = root / ".claude" / "settings.json"
    if not p.is_file():
        return ""
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(cfg, dict) or not isinstance(cfg.get("hooks"), dict):
        return ""

    scripts = {s for _, s in HOOK_EVENTS}
    tolti = []
    for ev, _ in HOOK_EVENTS:
        entries = cfg["hooks"].get(ev)
        if not isinstance(entries, list):
            continue
        restano = [e for e in entries if not our_entry(e, scripts)]
        if len(restano) == len(entries):
            continue
        tolti.append(ev)
        if restano:
            cfg["hooks"][ev] = restano
        else:
            del cfg["hooks"][ev]
    if not tolti:
        return ""
    if not cfg["hooks"]:
        del cfg["hooks"]
    if not dry:
        p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                     encoding="utf-8", newline="\n")
    return (f"tolti {', '.join(tolti)} da settings.json (adesso stanno nel file "
            f"locale; dichiarati in due posti girerebbero due volte). E' un file "
            f"tracciato: il diff e' voluto")


def merge_settings(root: Path, interp: str, dry: bool) -> str:
    """
    Gli hook si dichiarano in settings.local.json, che git non traccia.

    Il comando di un hook contiene il nome dell'interprete, che e' un fatto della
    MACCHINA: `python` su Windows, `python3` altrove. In un file tracciato quel nome
    viaggia con il repo e arriva sbagliato ovunque la piattaforma sia un'altra, oppure
    oscilla a ogni passaggio di mano. In un file locale, ogni macchina tiene il suo.

    Il prezzo, che e' giusto conoscere: un clone appena fatto non ha hook finche' non
    ci si lancia dentro questo script una volta. Meglio assenti e visibili che presenti
    e silenziosamente morti, perche' gli hook sono fail-open e non si lamentano.

    Il file va FUSO, non saltato e non sovrascritto: saltarlo perche' esiste lascia gli
    script su disco senza che niente li invochi, sovrascriverlo cancella i permessi
    che l'utente ci ha gia' messo.
    """
    p = root / ".claude" / "settings.local.json"
    if not p.exists():
        cfg = {"hooks": {ev: [hook_entry(interp, s)] for ev, s in HOOK_EVENTS}}
        if not dry:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8", newline="\n")
        return "creato"

    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return (f"NON TOCCATO: non e' JSON valido ({exc}). Gli hook NON sono "
                f"agganciati: correggilo a mano e rilancia")
    if not isinstance(cfg, dict):
        return "NON TOCCATO: non contiene un oggetto JSON. Gli hook NON sono agganciati"

    hooks = cfg.setdefault("hooks", {})
    added, riscritti, estranei = [], 0, 0
    for ev, script in HOOK_EVENTS:
        entries = hooks.setdefault(ev, [])
        if not isinstance(entries, list):
            return f"NON TOCCATO: 'hooks.{ev}' non e' una lista. Aggancia a mano"
        if script in json.dumps(entries):
            # C'e' gia', ma non e' detto che sia eseguibile QUI: vedi retarget_hooks.
            r, e = retarget_hooks(entries, interp, script)
            riscritti += r
            estranei += e
            continue
        entries.append(hook_entry(interp, script))
        added.append(ev)

    if not added and not riscritti:
        return ("gia' agganciato, lasciato com'era" + (
            f"  ({estranei} comando invoca i nostri hook con un interprete che non "
            f"riconosco: controllalo a mano)" if estranei else ""))
    if not dry:
        p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                     encoding="utf-8", newline="\n")
    parti = []
    if added:
        parti.append(f"aggiunti {', '.join(added)}")
    if riscritti:
        parti.append(f"interprete portato a '{interp}' in {riscritti} hook "
                     f"(il repo era stato inizializzato su un'altra piattaforma)")
    return "fuso: " + "; ".join(parti) + " (il resto lasciato intatto)"


CMD_RE = re.compile(r'"command"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"')


def interpreters_in(blob: str) -> list:
    """Con quali interpreti settings.json invoca i NOSTRI hook, senza ripetizioni."""
    nostri = {s for _, s in HOOK_EVENTS}
    nomi = []
    for m in CMD_RE.finditer(blob):
        cmd = m.group(1)
        if not any(s in cmd for s in nostri):
            continue
        n = INTERP_RE.match(cmd)
        if n and n.group(0).strip() not in nomi:
            nomi.append(n.group(0).strip())
    return nomi


def interpreter_works(nome: str) -> bool:
    """
    Lo esegue davvero, invece di fidarsi del nome.

    Su Windows `python3` c'e' quasi sempre nel PATH ed e' un rimando al Microsoft
    Store: non esegue niente ed esce con un codice di errore. Un controllo del tipo
    "esiste nel PATH?" direbbe di si' e sbaglierebbe.
    """
    try:
        r = subprocess.run(nome.split() + ["-c", "pass"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        return r.returncode == 0
    except OSError:
        return False


def diagnose(root: Path, interp: str) -> list:
    """
    Cosa resta NON funzionante dopo l'inizializzazione. Serve soprattutto quando il
    repo aveva gia' un contesto: i file esistenti vengono rispettati, e proprio per
    questo restano privi dei marcatori che gli hook usano.
    """
    problemi = []

    st = root / "docs" / "context" / "status.md"
    if not st.is_file():
        problemi.append("docs/context/status.md non esiste: gli hook non hanno "
                        "niente da leggere.")
    else:
        text = st.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"<!--\s*context-verified-at:\s*[0-9a-f]{7,40}\s*-->", text):
            problemi.append(
                "docs/context/status.md non ha il marcatore di freschezza. Aggiungi in "
                "testa:\n     <!-- context-verified-at: $(git rev-parse --short HEAD) -->\n"
                "     Senza, il controllo 5 del lint e l'avviso dell'hook non funzionano.")
        if "session-start: begin" not in text:
            problemi.append(
                "docs/context/status.md non ha i blocchi <!-- session-start: begin -->\n"
                "     ... <!-- session-start: end -->. L'hook di avvio non inietta niente:\n"
                "     delimita le sezioni che vuoi vedere a ogni sessione (cosa blocca,\n"
                "     difetti aperti).")

    s = root / ".claude" / "settings.local.json"
    if not s.is_file():
        problemi.append(".claude/settings.local.json manca: gli hook NON sono "
                        "agganciati.")
    else:
        try:
            blob = s.read_text(encoding="utf-8")
            for ev, script in HOOK_EVENTS:
                if script not in blob:
                    problemi.append(f"{script} non compare in "
                                    f".claude/settings.local.json: l'hook {ev} NON e' "
                                    f"agganciato.")
            # Dichiarati in tutti e due i file, girerebbero due volte.
            cond = root / ".claude" / "settings.json"
            if cond.is_file():
                altro = cond.read_text(encoding="utf-8", errors="replace")
                if any(script in altro for _, script in HOOK_EVENTS):
                    problemi.append(
                        "i nostri hook compaiono ANCHE in .claude/settings.json: "
                        "girerebbero due volte.\n     Toglili da li', il posto giusto "
                        "e' settings.local.json.")
            # Agganciato non vuol dire eseguibile: l'interprete scritto li' dentro deve
            # esistere QUI. Non basta guardarne il nome, si prova a eseguirlo.
            for nome in interpreters_in(blob):
                if not interpreter_works(nome):
                    problemi.append(
                        f"gli hook invocano `{nome}`, che su questa macchina non esegue "
                        f"niente (provato: `{nome} -c pass`).\n"
                        f"     Sono fail-open: non protesterebbero, semplicemente non "
                        f"girerebbero. Installalo con questo nome,\n"
                        f"     oppure rilancia l'inizializzatore, che riscrive "
                        f"l'interprete.")
        except OSError:
            problemi.append(".claude/settings.json non leggibile.")

    return problemi


def ensure_gitignore(root: Path, dry: bool) -> str:
    gi = root / ".gitignore"
    text = gi.read_text(encoding="utf-8") if gi.is_file() else ""
    add = [l for l in GITIGNORE_LINES if l not in text]
    if not add:
        return "gia' a posto"
    if not dry:
        with open(gi, "a", encoding="utf-8") as fh:
            fh.write("\n# Claude Code: permessi locali della macchina, non condivisi\n")
            for l in add:
                fh.write(l + "\n")
    return f"aggiunte {len(add)} righe"


# ------------------------------------------------------------------------------ main

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Prepara la struttura di contesto/memoria per agenti in un repo.")
    ap.add_argument("--dry-run", action="store_true", help="dice cosa farebbe")
    ap.add_argument("--force", action="store_true",
                    help="aggiorna lint, hook e guida alla versione di riferimento. "
                         "Non tocca docs/context/status.md, che e' tuo")
    ap.add_argument("--pack", action="store_true",
                    help="rigenera il payload dal repo corrente (progetto di riferimento)")
    ap.add_argument("--self-test", action="store_true",
                    help="verifica che il payload sia leggibile ed esce")
    args = ap.parse_args()

    if args.self_test:
        p = load_payload()
        if not p:
            print("payload illeggibile", file=sys.stderr)
            return 1
        print(f"{len(p)} file, {sum(len(v) for v in p.values())} byte")
        return 0

    root = repo_root()
    if root is None:
        print("Non sei dentro un repository git. Fai prima `git init`.", file=sys.stderr)
        return 1

    if args.pack:
        print(f"Rigenero il payload da {root}")
        return pack(root)

    payload = load_payload()
    if not payload:
        print("Questo file non ha payload: rigeneralo con --pack in un progetto di "
              "riferimento.", file=sys.stderr)
        return 1

    interp = "python" if sys.platform == "win32" else "python3"
    print(f"Repository : {root}")
    print(f"Piattaforma: {sys.platform}  ->  interprete degli hook: {interp}")
    if args.dry_run:
        print("MODALITA' DRY-RUN: non viene scritto niente.")
    print()

    det = detect_project(root)
    print("Rilevato in questo repo (dai file tracciati da git):")
    print(f"  directory sorgente : {', '.join(det['code_dirs'])}")
    print(f"  estensioni         : {' '.join(det['code_suffixes'][:14])}"
          + (" …" if len(det["code_suffixes"]) > 14 else ""))
    print(f"  sorvegliate da Stop: {', '.join(det['code_paths'])}")
    print("  (finiscono nelle costanti in cima ai due script; correggile se ho sbagliato)")
    print()

    filled = {
        "scripts/docs_lint.py": NEUTRAL_LINT_TUNING.format(
            code_dirs=repr(det["code_dirs"]),
            code_files=repr(det["code_files"]),
            code_suffixes="{" + ", ".join(f'"{s}"' for s in det["code_suffixes"]) + "}",
            skip_dirs='{"build", ".git", "__pycache__", "node_modules", "dist"}'),
        ".claude/hooks/hooklib.py": NEUTRAL_HOOK_TUNING.format(
            code_paths=repr(det["code_paths"])),
    }

    w = Writer(root, args.force, args.dry_run)

    for rel, content in payload.items():
        if rel in filled:
            content, done = replace_tuning(content, filled[rel])
            if not done:
                print(f"  ATTENZIONE: {rel} nel payload non ha i marcatori di "
                      f"taratura: restano i valori neutri, da ritarare a mano.")
        w.put(rel, content)

    # In un repo senza ancora un commit non esiste uno sha da scrivere. Meglio
    # nessun marcatore, che la diagnosi segnala, di un marcatore finto che passa
    # il controllo di presenza e mente sul contenuto.
    sha = git(root, "rev-parse", "--short", "HEAD")
    marker = f"\n<!-- context-verified-at: {sha} -->\n" if re.fullmatch(r"[0-9a-f]{7,40}", sha or "") else "\n"
    w.put("docs/context/status.md",
          STATUS_SKELETON.format(marker=marker, today=date.today().isoformat()),
          seed=True)

    for rel in w.written:
        print(f"  creato   {rel}")
    for rel in w.skipped:
        print(f"  esisteva {rel}  (--force lo aggiorna alla versione di riferimento)")
    for rel in w.protected:
        print(f"  TUO      {rel}  (contiene il tuo lavoro: mai sovrascritto, "
              f"nemmeno con --force)")
    print(f"  settings:   {merge_settings(root, interp, args.dry_run)}"
          f"  ->  .claude/settings.local.json, che git non traccia")
    ripulito = unhook_shared(root, args.dry_run)
    if ripulito:
        print(f"  migrazione: {ripulito}")
    print(f"  .gitignore: {ensure_gitignore(root, args.dry_run)}")

    problemi = diagnose(root, interp) if not args.dry_run else []
    if not args.dry_run:
        if problemi:
            n = len(problemi)
            print("\n" + "!" * 74)
            print(f"DA SISTEMARE — {n} cosa non funziona ancora." if n == 1
                  else f"DA SISTEMARE — {n} cose non funzionano ancora.")
            print("Tipicamente perche' un file c'era gia' ed e' stato rispettato, quindi")
            print("non ha i marcatori che gli hook usano; oppure perche' il repo non ha")
            print("ancora un commit a cui ancorare il marcatore di freschezza.")
            print("!" * 74)
            for n, msg in enumerate(problemi, 1):
                print(f"  {n}. {msg}")
        else:
            print("\n  Diagnosi: tutto agganciato, marcatori a posto.")

    print("\n" + "=" * 74)
    print("Fatta la meccanica. Il contesto lo deve ancora scrivere l'agente.")
    print("=" * 74)
    print("""
Non devi ritarare niente a mano. Le costanti rilevabili (dove sta il codice, che
estensioni ha, cosa sorveglia lo Stop) sono gia' scritte nei due script, e le trovi
qui sopra sotto "Rilevato": guardale, e correggile SOLO se ho sbagliato.
Le altre tre — NOT_SYMBOLS, EXPECTED_ABSENT, EXTERNAL_SYMBOLS — partono vuote di
proposito e si riempiono guardando i falsi positivi del primo giro di lint: e' un
lavoro di dominio, ed e' gia' chiesto nel prompt qui sotto.

1. Apri una sessione dell'agente e incollagli questo prompt:
""")
    print("-" * 74)
    print(PROMPT)
    if problemi:
        print()
        print("Inoltre l'inizializzatore ha lasciato aperti questi punti, sistemali:")
        for n, msg in enumerate(problemi, 1):
            print(f"{n}. {msg}")
    print("-" * 74)
    print("""
2. Quando ha finito, verifica tu:
     python scripts/docs_lint.py          deve uscire pulito
     git log --oneline -5                 cosa ha committato
   e che l'hook di avvio giri davvero: apri una sessione nuova e guarda
     .git/claude-hooks.log
   Su ogni ALTRA macchina dove clonerai questo repo, rilancia questo script una
   volta: gli hook stanno in .claude/settings.local.json, che non viene clonato.
   Non aspettarti di vedere niente a schermo: l'iniezione va nel contesto
   dell'agente, non nel tuo terminale.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ==== PAYLOAD (rigenerabile con --pack, non modificare a mano) ====
# ---- AGENT-CONTEXT-FILE: scripts/docs_lint.py ----
# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-
# """
# docs_lint — controlla che la documentazione per agenti dica ancora il vero.
#
# Questo progetto non ha CI ne' test automatici: e' l'unico controllo automatico che
# esiste, e non guarda il firmware, guarda i documenti che lo descrivono.
#
# Cinque controlli:
#
#   1. FEATURE BANDITE  — i simboli elencati in docs/context/invariants.md non sono
#                         ricomparsi nel codice. La lista NON e' scritta qui: viene
#                         letta dal documento, che resta l'unica fonte.
#   2. IDENTIFICATORI   — ogni simbolo o percorso citato fra backtick in docs/context/
#                         esiste ancora nell'albero. E' il controllo che intercetta
#                         una rinomina fatta senza aggiornare i documenti.
#   3. EVIDENZA         — in docs/context/ ogni "verificato" porta una data, e il
#                         lessico conversazionale ([Certo]/[Probabile]/[Ipotesi]) non
#                         entra nei documenti. Stampa il cruscotto dei tre livelli.
#   4. LINK E ANCORE    — ogni link markdown locale risolve, ancora compresa.
#   5. FRESCHEZZA       — quanti commit hanno toccato le directory sorgente dopo
#                         il punto in cui status.md dichiara di essere riconciliato.
#
# Uso:   python scripts/docs_lint.py [--quiet]
# Esce 0 se non ci sono errori, 1 se ce n'e' almeno uno. I WARN non fanno fallire.
# """
#
# import io
# import os
# import re
# import subprocess
# import sys
# from pathlib import Path
#
# if hasattr(sys.stdout, "buffer"):
#     sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
#
# # --------------------------------------------------------------------------- setup
#
# def repo_root() -> Path:
#     try:
#         out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
#                              capture_output=True, text=True, encoding="utf-8")
#         if out.returncode == 0 and out.stdout.strip():
#             return Path(out.stdout.strip())
#     except OSError:
#         pass
#     return Path(__file__).resolve().parent.parent
#
# ROOT = repo_root()
# CONTEXT = ROOT / "docs" / "context"
#
# # ==== TARATURA DEL PROGETTO (inizio) ====
# # Percorsi che compongono "il codice": tutto cio' che una rinomina toccherebbe.
# # RILEVATI dall'inizializzatore guardando questo repo. Correggili se ha sbagliato.
# CODE_DIRS = ["src"]
# CODE_FILES = []
# CODE_SUFFIXES = {".c", ".cc", ".cfg", ".cmake", ".conf", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".html", ".ini", ".java", ".js", ".json", ".jsx", ".kt", ".m", ".mm", ".php", ".ps1", ".py", ".rb", ".rs", ".scss", ".sh", ".sql", ".svelte", ".swift", ".toml", ".ts", ".tsx", ".txt", ".vue", ".yaml", ".yml"}
# SKIP_DIRS = {"build", ".git", "__pycache__", "node_modules", "dist"}
# # I file "meta" contengono la lista dei simboli banditi per poterla applicare o
# # trasportare: vanno esclusi dal controllo 1, o si accusano da soli. Restano invece
# # nell'albero per tutti gli altri controlli, altrimenti i simboli che definiscono
# # risulterebbero inesistenti.
# SELF = Path(__file__).resolve()
# # L'inizializzatore puo' stare ovunque — di solito nella radice, dove lo si copia —
# # quindi si cerca per nome invece di dare per scontato che sia in scripts/.
# META_FILES = {SELF} | {p.resolve() for p in ROOT.rglob("agent_context_init.py")
#                        if ".git" not in p.parts}
#
# # Token citati nei documenti che NON devono esistere nel codice, per costruzione:
# # un identificatore ritirato, un modulo rimosso, il nome di un altro repository.
# # VUOTO DI PROPOSITO: si riempie guardando i falsi positivi del primo giro.
# # Ogni voce porta il motivo, e senza motivo non si aggiunge niente — o in sei mesi
# # questa e' una discarica che silenzia anche i controlli veri.
# EXPECTED_ABSENT = {
#     # "NOME_RITIRATO": "perche' non deve esistere",
# }
#
# # Simboli che esistono, ma in una libreria o in un framework, non in questo albero.
# # Sono citati nei documenti perche' spiegano un vincolo esterno. VUOTO DI PROPOSITO.
# EXTERNAL_SYMBOLS = {
#     # "API_DELLA_LIBRERIA": "di quale libreria, e perche' e' citata",
# }
#
# # Parole che sembrano identificatori ma sono prosa, unita' di misura o nomi esterni.
# # Qui c'e' solo il nucleo indipendente dalla lingua e dal dominio: il resto va
# # aggiunto guardando i falsi positivi del primo giro, ed e' specifico della lingua
# # in cui sono scritti i documenti.
# NOT_SYMBOLS = {
#     "true", "false", "null", "none", "void", "main", "data", "text", "info",
#     "test", "build", "error", "warning", "debug", "http", "https", "json", "yaml",
#     "git", "origin", "HEAD", "grep", "python", "node", "docker",
#     "feat", "fix", "docs", "chore", "refactor", "style", "perf",
#     # Parole usate dallo scheletro di status.md: senza, il primo giro del lint
#     # segnala il file che l'inizializzatore ha appena scritto.
#     "esito", "chi", "prova", "corrente", "regola", "dove", "livello", "nota",
#     "head", "cronologia", "stato", "lavoro", "commit",
#     "verificato", "dedotto", "assunto",
# }
# # ==== TARATURA DEL PROGETTO (fine) ====
#
# # La ricerca in NOT_SYMBOLS confronta il token gia' abbassato a minuscolo: una voce
# # scritta in maiuscolo non combacerebbe mai, e il difetto sarebbe invisibile finche'
# # quella parola non compare in un documento. Si normalizza qui, una volta.
# NOT_SYMBOLS = {w.lower() for w in NOT_SYMBOLS}
#
# # Fuga esplicita per il caso legittimo: una riga che PARLA della convenzione invece di
# # applicarla. Va scritta in chiaro nel documento, cosi' si vede e si puo' cercare.
# IGNORE_MARK = "<!-- docs-lint: ignore -->"
#
# # Un token che ha questa forma non e' un simbolo del codice: e' un riferimento git.
# GITREF_RE = re.compile(r"^(?:[0-9a-f]{7,40}|origin/[\w./-]+|feature/[\w./-]+|refs/[\w./-]+)$")
#
#
# def read(p: Path) -> str:
#     try:
#         return p.read_text(encoding="utf-8")
#     except (OSError, UnicodeDecodeError):
#         return ""
#
#
# def strip_fences(text: str) -> str:
#     """Azzera i blocchi di codice recintati, tenendo la numerazione delle righe."""
#     out, inside = [], False
#     for line in text.split("\n"):
#         if line.lstrip().startswith("```"):
#             inside = not inside
#             out.append("")
#             continue
#         out.append("" if inside else line)
#     return "\n".join(out)
#
#
# def code_files(include_meta=True):
#     for name in CODE_FILES:
#         p = ROOT / name
#         if p.is_file():
#             yield p
#     for d in CODE_DIRS:
#         base = ROOT / d
#         if not base.is_dir():
#             continue
#         for p in base.rglob("*"):
#             if any(part in SKIP_DIRS for part in p.parts):
#                 continue
#             if not include_meta and p.resolve() in META_FILES:
#                 continue
#             if p.is_file() and p.suffix.lower() in CODE_SUFFIXES:
#                 yield p
#
#
# def tracked_files():
#     """Solo i file versionati: un documento di appunti non tracciato non fa fallire."""
#     r = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
#                        encoding="utf-8", cwd=ROOT)
#     if r.returncode != 0:
#         return None
#     return {(ROOT / line).resolve() for line in r.stdout.splitlines() if line.strip()}
#
#
# CODE_BLOB = None
#
# def code_blob() -> str:
#     global CODE_BLOB
#     if CODE_BLOB is None:
#         CODE_BLOB = "\n".join(read(p) for p in code_files())
#     return CODE_BLOB
#
#
# def context_files():
#     return sorted(CONTEXT.glob("*.md")) if CONTEXT.is_dir() else []
#
#
# class Report:
#     def __init__(self, quiet=False):
#         self.errors = []
#         self.warns = []
#         self.quiet = quiet
#
#     def error(self, check, msg):
#         self.errors.append((check, msg))
#
#     def warn(self, check, msg):
#         self.warns.append((check, msg))
#
#     def note(self, msg):
#         if not self.quiet:
#             print(msg)
#
#
# # ------------------------------------------------------------ 1. feature bandite
#
# def check_banned(rep: Report):
#     """La lista dei simboli banditi vive in invariants.md, non qui."""
#     inv = CONTEXT / "invariants.md"
#     if not inv.is_file():
#         # Progetto appena inizializzato: gli invarianti non sono ancora stati scritti.
#         # E' un lavoro da fare, non un guasto.
#         rep.warn("BANDITE", "docs/context/invariants.md non esiste ancora: "
#                             "il controllo 1 e' inattivo finche' non c'e'")
#         return
#     text = read(inv)
#     if not text:
#         rep.error("BANDITE", "docs/context/invariants.md esiste ma non e' leggibile")
#         return
#
#     m = re.search(r"##\s*Feature bandite\s*\n(.*?)(?=\n##\s|\Z)", text, re.S)
#     if not m:
#         # Un progetto puo' legittimamente non avere niente di bandito: e' un avviso,
#         # non un errore. Errore lo diventa solo se la sezione c'e' ed e' malformata.
#         rep.warn("BANDITE", "nessuna sezione '## Feature bandite' in invariants.md: "
#                             "il controllo 1 e' inattivo. Se il progetto ha cose che non "
#                             "devono tornare, dichiararle li' le rende verificabili")
#         return
#
#     para = re.search(r"Nessun riferimento nel codice a:(.*?)(?:\n\s*\n|\n\|)", m.group(1), re.S)
#     if not para:
#         rep.error("BANDITE", "il paragrafo 'Nessun riferimento nel codice a:' non ha piu' "
#                              "la forma attesa: aggiorna docs_lint.py o il documento")
#         return
#
#     tokens = re.findall(r"`([^`]+)`", para.group(1))
#     if not tokens:
#         rep.error("BANDITE", "nessun simbolo bandito estratto dal paragrafo")
#         return
#
#     files = list(code_files(include_meta=False))
#     hits = 0
#     for tok in tokens:
#         # Confine a sinistra: senza, `ff.h` trova `poweroff.h`. `*` diventa un glob.
#         body = re.escape(tok).replace(r"\*", r"\w*")
#         pattern = r"(?<![\w./])" + body
#         found = [p for p in files if re.search(pattern, read(p), re.I)]
#         if found:
#             hits += 1
#             where = ", ".join(str(p.relative_to(ROOT)) for p in found[:4])
#             rep.error("BANDITE", f"`{tok}` e' ricomparso nel codice: {where}")
#     rep.note(f"  simboli banditi controllati: {len(tokens)}  —  ricomparsi: {hits}")
#
#
# # --------------------------------------------------------- 2. identificatori vivi
#
# PATH_RE = re.compile(r"^[\w./\-]+\.(c|h|py|json|conf|md|txt|yml|yaml|rst|dts|overlay|pem)$")
# IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{3,}$")
#
#
# def path_exists_anywhere(rel: str) -> bool:
#     """
#     Un documento puo' citare un file per nome senza il percorso completo: `foo.md`
#     che sta in docs/, mentre chi lo cita e' in docs/context/. Cercarlo solo dalla
#     radice e solo accanto a chi lo cita produce un falso positivo, e i falsi positivi
#     sono il modo in cui un lint smette di essere letto. Regge anche i glob (`epd47/*.h`).
#     """
#     if (ROOT / rel).exists():
#         return True
#     try:
#         for hit in ROOT.glob("**/" + rel):
#             if not any(part in SKIP_DIRS for part in hit.parts):
#                 return True
#     except (ValueError, OSError, IndexError):
#         pass
#     return False
#
#
# def _is_prose(tok: str) -> bool:
#     """Frammenti di comando, formule e frasi fra backtick non sono identificatori."""
#     if " " in tok or "=" in tok or "(" in tok or "×" in tok or "@" in tok:
#         return True
#     # Segnaposto in un template: topic MQTT, rotta HTTP, nome di file parametrico.
#     # `epic/{mac}/data` non e' un percorso che debba esistere sul disco.
#     if "{" in tok or "}" in tok or "<" in tok or ">" in tok:
#         return True
#     # Unita' di misura: due segmenti, il secondo cortissimo e alfabetico — `umm/s`,
#     # `km/h`, `entry/s`. La soglia stretta sul secondo segmento evita di scambiare
#     # per unita' una cartella vera come `epic/data`.
#     seg = tok.split("/")
#     if len(seg) == 2 and seg[0].isalpha() and seg[1].isalpha() and len(seg[1]) <= 3:
#         return True
#     if tok.startswith(("-", ".", "~", "#", "/")):
#         return True
#     if tok.startswith("build/"):
#         return True
#     # `Imu_Acq_TryClaim/Release/Current`: scorciatoia di prosa, non un percorso.
#     if "/" in tok and not PATH_RE.match(tok):
#         if any(seg[:1].isupper() for seg in tok.split("/") if seg):
#             return True
#     return False
#
#
# def check_identifiers(rep: Report):
#     tokens = {}
#     for p in context_files():
#         for m in re.finditer(r"`([^`\n]+)`", strip_fences(read(p))):
#             tok = m.group(1).strip()
#             tokens.setdefault(tok, set()).add(p)
#
#     checked = missing = skipped = 0
#     for tok, where in sorted(tokens.items(), key=lambda kv: kv[0]):
#         base = tok.rstrip("*/")
#         names = ", ".join(sorted(p.name for p in where))
#
#         if (_is_prose(tok) or GITREF_RE.match(tok) or tok.startswith("zephyr/")
#                 or tok.lower() in NOT_SYMBOLS or base.lower() in NOT_SYMBOLS
#                 or base in EXTERNAL_SYMBOLS
#                 or any(k.rstrip("*") in tok for k in EXPECTED_ABSENT)):
#             skipped += 1
#             continue
#
#         if PATH_RE.match(tok) or "/" in tok:
#             checked += 1
#             rel = tok.rstrip("/")
#             # Relativo a chi lo cita, poi ovunque nell'albero (glob compresi).
#             if any((p.parent / rel).exists() for p in where) or path_exists_anywhere(rel):
#                 continue
#             missing += 1
#             rep.error("IDENT", f"percorso `{tok}` non esiste  (citato in {names})")
#             continue
#
#         if IDENT_RE.match(tok):
#             checked += 1
#             # Sottostringa, non parola intera: i documenti citano di proposito la coda
#             # di un enum lungo (`INFO_ID_STREAM` per
#             # USB_CONNECTION_PACKET_INFO_ID_STREAM). E' la regola dell'altitudine:
#             # il documento non ripete il prefisso, il controllo lo tollera.
#             if base in code_blob():
#                 continue
#             missing += 1
#             rep.error("IDENT", f"simbolo `{tok}` non esiste nel codice  (citato in {names})")
#         else:
#             skipped += 1
#
#     rep.note(f"  token controllati: {checked}  —  non trovati: {missing}  "
#              f"—  ignorati (prosa o assenza voluta): {skipped}")
#
#
# # ------------------------------------------------------------- 3. livelli evidenza
#
# LEVELS = ("verificato", "dedotto", "assunto")
# DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# CONV_RE = re.compile(r"\[(Certo|Probabile|Ipotesi)\]")
#
#
# def check_evidence(rep: Report):
#     counts = {lvl: 0 for lvl in LEVELS}
#     for p in context_files():
#         text = strip_fences(read(p))
#         in_legend = False
#         for n, line in enumerate(text.split("\n"), 1):
#             for lvl in LEVELS:
#                 counts[lvl] += len(re.findall(r"\*\*" + lvl + r"\*\*", line))
#
#             # La sezione che DEFINISCE il lessico e' esente dal lessico che definisce.
#             if re.match(r"^##\s", line):
#                 in_legend = "livelli di evidenza" in line.lower()
#             if in_legend or IGNORE_MARK in line:
#                 continue
#
#             if re.search(r"\*\*verificato\*\*", line) and not DATE_RE.search(line):
#                 rep.error("EVIDENZA",
#                           f"{p.name}:{n} — '**verificato**' senza data: "
#                           f"un verificato senza data non e' verificabile")
#
#             # collaboration.md e' il file che DEFINISCE il lessico conversazionale.
#             m = CONV_RE.search(line)
#             if m and p.name != "collaboration.md":
#                 rep.error("EVIDENZA",
#                           f"{p.name}:{n} — [{m.group(1)}] e' il lessico della "
#                           f"conversazione: nei documenti si usa "
#                           f"verificato/dedotto/assunto")
#     rep.note("  cruscotto evidenza in docs/context/:  " +
#              "  ".join(f"{lvl}={counts[lvl]}" for lvl in LEVELS))
#     if counts["verificato"] == 0:
#         rep.warn("EVIDENZA", "nessun '**verificato**' in tutta docs/context/")
#
#
# # ---------------------------------------------------------------- 4. link e ancore
#
# def slug(title: str) -> str:
#     t = title.strip().lower()
#     t = re.sub(r"`([^`]*)`", r"\1", t)
#     t = re.sub(r"<[^>]+>", "", t)
#     t = "".join(ch for ch in t if ch.isalnum() or ch in " -_")
#     return t.replace(" ", "-")
#
#
# LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
#
#
# def check_links(rep: Report):
#     anchors = {}
#     for p in ROOT.rglob("*.md"):
#         if any(part in SKIP_DIRS for part in p.parts):
#             continue
#         text = strip_fences(read(p))
#         found = set()
#         for line in text.split("\n"):
#             m = re.match(r"^#{1,6}\s+(.*)$", line)
#             if m:
#                 found.add(slug(m.group(1)))
#         for m in re.finditer(r'<a\s+id="([^"]+)"', text):
#             found.add(m.group(1))
#         anchors[p.resolve()] = found
#
#     targets = [ROOT / "AGENTS.md", ROOT / "CLAUDE.md"]
#     targets += context_files() + sorted((ROOT / "docs").glob("*.md"))
#     tracked = tracked_files()
#
#     checked = broken = skipped_untracked = skipped_received = 0
#     for p in targets:
#         if not p.is_file():
#             continue
#         # Un file di appunti non tracciato non deve far fallire il controllo.
#         if tracked is not None and p.resolve() not in tracked and p not in context_files():
#             skipped_untracked += 1
#             continue
#         # Un documento ricevuto non e' nostro da riparare: vedi RECEIVED_DOCS.
#         if p.name in RECEIVED_DOCS:
#             skipped_received += 1
#             continue
#         for m in LINK_RE.finditer(strip_fences(read(p))):
#             target = m.group(2).strip()
#             if target.startswith(("http://", "https://", "mailto:", "#!")):
#                 continue
#             path, _, anchor = target.partition("#")
#             checked += 1
#             if path == "":
#                 dest = p.resolve()
#             else:
#                 dest = (p.parent / path).resolve()
#                 if not dest.exists():
#                     broken += 1
#                     rep.error("LINK", f"{p.name} -> {target}  (file inesistente)")
#                     continue
#             if anchor:
#                 if dest not in anchors:
#                     broken += 1
#                     rep.error("LINK", f"{p.name} -> {target}  (file non indicizzato)")
#                 elif anchor not in anchors[dest]:
#                     broken += 1
#                     rep.error("LINK", f"{p.name} -> {target}  (ancora assente)")
#     rep.note(f"  link locali controllati: {checked}  —  rotti: {broken}"
#              + (f"  —  file non tracciati saltati: {skipped_untracked}"
#                 if skipped_untracked else "")
#              + (f"  —  documenti ricevuti saltati: {skipped_received}"
#                 if skipped_received else ""))
#
#
# # ------------------------------------------------------------------ 5. freschezza
#
# MARKER_RE = re.compile(r"<!--\s*context-verified-at:\s*([0-9a-f]{7,40})\s*-->")
#
#
# def check_freshness(rep: Report):
#     status = CONTEXT / "status.md"
#     text = read(status)
#     if not text:
#         rep.error("FRESCHEZZA", "docs/context/status.md non leggibile")
#         return
#     m = MARKER_RE.search(text)
#     if not m:
#         rep.error("FRESCHEZZA",
#                   "status.md non ha il marcatore <!-- context-verified-at: <sha> -->: "
#                   "senza, la freschezza non e' misurabile")
#         return
#     sha = m.group(1)
#     r = subprocess.run(["git", "log", "--oneline", f"{sha}..HEAD", "--", "src", "drivers"],
#                        capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
#     if r.returncode != 0:
#         rep.warn("FRESCHEZZA", f"commit {sha} non trovato: il marcatore punta al vuoto")
#         return
#     lines = [l for l in r.stdout.splitlines() if l.strip()]
#     if lines:
#         rep.warn("FRESCHEZZA",
#                  f"{len(lines)} commit hanno toccato src/ o drivers/ dopo {sha}, "
#                  f"a cui status.md dichiara di essere riconciliato:\n      " +
#                  "\n      ".join(lines[:8]))
#     else:
#         rep.note(f"  status.md riconciliato a {sha}: nessun commit su src/ da allora")
#
#
# # ------------------------------------------------------------------------- main
#
# CHECKS = [
#     ("1. FEATURE BANDITE — simboli che non devono tornare", check_banned),
#     ("2. IDENTIFICATORI  — cio' che i doc citano esiste ancora", check_identifiers),
#     ("3. EVIDENZA        — verificato/dedotto/assunto", check_evidence),
#     ("4. LINK E ANCORE   — i rimandi risolvono", check_links),
#     ("5. FRESCHEZZA      — status.md rispetto al codice", check_freshness),
# ]
#
#
# def main():
#     quiet = "--quiet" in sys.argv
#     rep = Report(quiet=quiet)
#     if not quiet:
#         print("=" * 74)
#         print("docs_lint — la documentazione per agenti dice ancora il vero?")
#         print("=" * 74)
#     for title, fn in CHECKS:
#         rep.note("")
#         rep.note(title)
#         try:
#             fn(rep)
#         except Exception as exc:                      # fail-open sul singolo controllo
#             rep.warn("INTERNO", f"{title.split('—')[0].strip()}: {type(exc).__name__}: {exc}")
#
#     print()
#     print("=" * 74)
#     if rep.errors:
#         print(f"ERRORI: {len(rep.errors)}")
#         for check, msg in rep.errors:
#             print(f"  [{check}] {msg}")
#     if rep.warns:
#         print(f"AVVISI: {len(rep.warns)}")
#         for check, msg in rep.warns:
#             print(f"  [{check}] {msg}")
#     if not rep.errors and not rep.warns:
#         print("Tutto a posto.")
#     elif not rep.errors:
#         print("Nessun errore. Gli avvisi non fanno fallire il controllo.")
#     print("=" * 74)
#     return 1 if rep.errors else 0
#
#
# if __name__ == "__main__":
#     sys.exit(main())
#
# ---- AGENT-CONTEXT-FILE: .claude/hooks/hooklib.py ----
# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-
# """
# hooklib — la parte comune dei due hook. Python, non shell, perche' deve girare
# uguale su Windows e su macOS: una sola implementazione, nessuna copia da tenere
# allineata.
#
# =============================================================================
# Costanti del progetto. Su un repo nuovo le scrive `agent_context_init.py`
# rilevandole da `git ls-files`: vanno guardate, e corrette solo se ha sbagliato.
# =============================================================================
# """
#
# # ==== TARATURA DEL PROGETTO (inizio) ====
# # Le directory il cui cambiamento richiede che lo stato del lavoro venga aggiornato.
# # RILEVATE dall'inizializzatore guardando questo repo. Correggile se ha sbagliato.
# CODE_PATHS = ["src"]
#
# # Il documento che tiene lo stato corrente del lavoro.
# STATUS_FILE = "docs/context/status.md"
#
# # La directory dei documenti di contesto, per il cruscotto dei livelli di evidenza.
# CONTEXT_DIR = "docs/context"
#
# # I livelli di evidenza, nella forma esatta in cui compaiono nei documenti.
# EVIDENCE_LEVELS = ["verificato", "dedotto", "assunto"]
# # ==== TARATURA DEL PROGETTO (fine) ====
#
# # =============================================================================
# # Da qui in giu' non c'e' niente di specifico del progetto.
# # =============================================================================
#
# import io
# import os
# import re
# import subprocess
# import sys
# from datetime import datetime
# from pathlib import Path
#
# MARKER_RE = re.compile(r"<!--\s*context-verified-at:\s*([0-9a-f]{7,40})\s*-->")
# # I marcatori devono stare DA SOLI sulla loro riga: senza le ancore di riga, la
# # regex cattura anche il paragrafo che spiega i marcatori citandoli in linea.
# BLOCK_RE = re.compile(
#     r"^[ \t]*<!--\s*session-start:\s*begin\s*-->[ \t]*$"
#     r"(.*?)"
#     r"^[ \t]*<!--\s*session-start:\s*end\s*-->[ \t]*$",
#     re.S | re.M)
#
#
# def setup_stdout() -> None:
#     """La console di Windows non e' UTF-8: senza questo, una freccia uccide l'hook."""
#     try:
#         if hasattr(sys.stdout, "buffer"):
#             sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
#                                           errors="replace")
#     except Exception:
#         pass
#
#
# def run_git(root, *args) -> str:
#     try:
#         r = subprocess.run(["git", *args], capture_output=True, text=True,
#                            encoding="utf-8", errors="replace", cwd=str(root))
#         return r.stdout if r.returncode == 0 else ""
#     except OSError:
#         return ""
#
#
# def repo_root():
#     try:
#         r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
#                            capture_output=True, text=True, encoding="utf-8",
#                            errors="replace")
#         if r.returncode == 0 and r.stdout.strip():
#             return Path(r.stdout.strip())
#     except OSError:
#         pass
#     return None
#
#
# def git_dir(root):
#     out = run_git(root, "rev-parse", "--git-dir").strip()
#     if not out:
#         return None
#     p = Path(out)
#     return p if p.is_absolute() else (root / p)
#
#
# def log(event: str, outcome: str) -> None:
#     """
#     Traccia su file. E' l'UNICO modo in cui l'utente puo' vedere che l'hook e'
#     partito: lo stdout di SessionStart va nel contesto dell'agente, non a schermo, e
#     gli hook sono fail-open, quindi senza questa riga un hook rotto e un hook assente
#     sono indistinguibili. Si scrivono anche gli esiti silenziosi, per lo stesso motivo.
#     """
#     try:
#         root = repo_root()
#         if root is None:
#             return
#         g = git_dir(root)
#         if g is None:
#             return
#         line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {event:<13} {outcome}\n"
#         with open(g / "claude-hooks.log", "a", encoding="utf-8") as fh:
#             fh.write(line)
#     except Exception:
#         pass
#
#
# def read_marker(status_text: str):
#     m = MARKER_RE.search(status_text)
#     return m.group(1) if m else None
#
#
# def extract_marked(status_text: str):
#     """
#     Le sezioni da iniettare le dichiara il documento, con
#     <!-- session-start: begin --> ... <!-- session-start: end -->.
#     Cosi' l'hook non sa niente della numerazione delle sezioni, che cambia da progetto
#     a progetto e drifta dentro lo stesso progetto.
#     """
#     return [m.group(1).strip() for m in BLOCK_RE.finditer(status_text) if m.group(1).strip()]
#
#
# def count_levels(root) -> dict:
#     counts = {lvl: 0 for lvl in EVIDENCE_LEVELS}
#     ctx = root / CONTEXT_DIR
#     if not ctx.is_dir():
#         return counts
#     for p in sorted(ctx.glob("*.md")):
#         try:
#             text = p.read_text(encoding="utf-8", errors="replace")
#         except OSError:
#             continue
#         for lvl in EVIDENCE_LEVELS:
#             counts[lvl] += len(re.findall(r"\*\*" + re.escape(lvl) + r"\*\*", text))
#     return counts
#
#
# def dirty(root, paths) -> str:
#     """Modifiche non committate sotto i percorsi dati (stringa vuota = pulito)."""
#     return run_git(root, "status", "--porcelain", "--", *paths).strip()
#
# ---- AGENT-CONTEXT-FILE: .claude/hooks/session_start.py ----
# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-
# """
# SessionStart — inietta in contesto lo stato corrente del progetto.
#
# Perche' esiste: il file di ingresso (AGENTS.md) e' caricato in automatico, ma i file
# dei sottosistemi e status.md no — si aprono solo se l'agente decide di seguire il
# rinvio. Questo hook toglie di mezzo quella discrezionalita' per il file piu' volatile.
#
# Lo stdout di SessionStart entra nel contesto dell'agente, NON a schermo: l'utente non
# vede niente ed e' normale. La prova che sia partito e' la riga in .git/claude-hooks.log.
# Ogni riga stampata si paga in token a ogni avvio, /clear e compattazione compresi.
#
# FAIL-OPEN: qualunque errore esce 0 e non stampa. Un hook rotto deve degradare ad
# "assente", mai a "bloccante".
# """
#
# import sys
#
# from hooklib import (
#     CODE_PATHS, STATUS_FILE, count_levels, dirty, extract_marked,
#     log, read_marker, repo_root, run_git, setup_stdout,
# )
#
# setup_stdout()
#
#
# def main() -> int:
#     root = repo_root()
#     if root is None:
#         return 0
#
#     status_path = root / STATUS_FILE
#     if not status_path.is_file():
#         log("SessionStart", f"nessun {STATUS_FILE}: niente da iniettare")
#         return 0
#
#     status = status_path.read_text(encoding="utf-8", errors="replace")
#
#     out = [
#         "=== Stato del progetto (iniettato da .claude/hooks/session_start.py) ===",
#         f"Fonte: {STATUS_FILE}. Se agisci su qualcosa di qui sotto, rileggi il file intero.",
#         "",
#     ]
#
#     # --- Le sezioni che il documento stesso dichiara volatili ---
#     blocks = extract_marked(status)
#     if blocks:
#         out.append("\n\n".join(blocks))
#         out.append("")
#     else:
#         out.append(f"({STATUS_FILE} non ha blocchi <!-- session-start: begin/end -->: "
#                    f"nessuna sezione dichiarata volatile.)")
#         out.append("")
#
#     # --- Cruscotto dei livelli di evidenza ---
#     levels = count_levels(root)
#     out.append("Evidenza nei documenti di contesto: " +
#                "  ".join(f"{k}={v}" for k, v in levels.items()))
#
#     # --- Freschezza: il documento e' invecchiato rispetto al codice? ---
#     sha = read_marker(status)
#     if sha:
#         since = run_git(root, "log", "--oneline", f"{sha}..HEAD", "--", *CODE_PATHS)
#         if since:
#             n = len(since.splitlines())
#             out.append(f"ATTENZIONE: {n} commit hanno toccato {'/, '.join(CODE_PATHS)}/ "
#                        f"dopo {sha}, il punto a cui {STATUS_FILE} dichiara di essere "
#                        f"riconciliato. Potrebbe dire cose non piu' vere.")
#     else:
#         out.append(f"ATTENZIONE: {STATUS_FILE} non ha il marcatore context-verified-at: "
#                    f"la sua freschezza non e' misurabile.")
#
#     # --- Lavoro non registrato rimasto da una sessione precedente ---
#     if dirty(root, CODE_PATHS) and not dirty(root, [STATUS_FILE]):
#         out.append(f"ATTENZIONE: ci sono modifiche non committate sotto "
#                    f"{'/, '.join(CODE_PATHS)}/ e {STATUS_FILE} e' intatto. Probabile "
#                    f"lavoro di una sessione precedente mai registrato: valuta se va "
#                    f"annotato.")
#
#     out += ["", "Verifica che i documenti dicano ancora il vero: "
#                 "python scripts/docs_lint.py",
#             "=== fine stato del progetto ==="]
#
#     text = "\n".join(out)
#     print(text)
#     log("SessionStart", f"iniettati {len(text)} caratteri "
#                         f"(assunto={levels.get('assunto', 0)})")
#     return 0
#
#
# if __name__ == "__main__":
#     try:
#         sys.exit(main())
#     except Exception as exc:                      # fail-open, sempre
#         try:
#             log("SessionStart", f"ERRORE INTERNO {type(exc).__name__} "
#                                 f"(fail-open, nessun blocco)")
#         except Exception:
#             pass
#         sys.exit(0)
#
# ---- AGENT-CONTEXT-FILE: .claude/hooks/stop_check.py ----
# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-
# """
# Stop — impedisce di chiudere il turno se il codice e' cambiato e lo stato del lavoro no.
#
# Stop scatta alla fine di OGNI risposta, non a fine sessione. E' esattamente il motivo
# per cui funziona: non esiste un "momento finale" da intercettare, e chiudere il
# terminale non salta nessun controllo, perche' il controllo e' gia' avvenuto a ogni
# turno precedente.
#
# Exit 2 = "prevents Claude from stopping, continues conversation", con il messaggio
# preso da stderr. Blocca UNA SOLA VOLTA per sessione: poi lascia un marcatore in .git/
# e tace, altrimenti diventa martellante.
#
# FAIL-OPEN: qualunque errore esce 0. Un hook rotto non deve mai bloccare il lavoro.
# """
#
# import json
# import re
# import sys
#
# from hooklib import (
#     CODE_PATHS, STATUS_FILE, dirty, git_dir, log, read_marker, repo_root,
#     run_git, setup_stdout,
# )
#
# setup_stdout()
#
# MESSAGE = """Il codice e' cambiato e {status} e' intatto.
#
#   - {reasons}
#
# Prima di chiudere: aggiorna {status} (difetto notato, verifica saltata, decisione
# rimandata, stato del lavoro), oppure dichiara esplicitamente all'utente perche' non
# serve. Se hai riconciliato il documento con il codice, riporta anche il marcatore
# context-verified-at a HEAD.
#
# Questo controllo blocca una volta sola per sessione: non ripartira'."""
#
#
# def session_id() -> str:
#     try:
#         raw = sys.stdin.read()
#     except Exception:
#         return "ignota"
#     if not raw:
#         return "ignota"
#     try:
#         sid = json.loads(raw).get("session_id")
#         return str(sid) if sid else "ignota"
#     except Exception:
#         return "ignota"
#
#
# def main() -> int:
#     sid = session_id()
#     root = repo_root()
#     if root is None:
#         return 0
#     g = git_dir(root)
#     if g is None:
#         return 0
#
#     safe = re.sub(r"[^A-Za-z0-9_-]", "", sid) or "ignota"
#     flag = g / f"docs-status-nag-{safe}.flag"
#     if flag.exists():
#         log("Stop", "ok (gia' segnalato in questa sessione)")
#         return 0
#
#     if dirty(root, [STATUS_FILE]):
#         log("Stop", f"ok ({STATUS_FILE} gia' toccato)")
#         return 0
#
#     reasons = []
#
#     changed = dirty(root, CODE_PATHS)
#     if changed:
#         files = ", ".join(re.sub(r"^\s*\S+\s+", "", l) for l in changed.splitlines())
#         reasons.append(f"modifiche non committate: {files}")
#
#     status_path = root / STATUS_FILE
#     if status_path.is_file():
#         sha = read_marker(status_path.read_text(encoding="utf-8", errors="replace"))
#         if sha:
#             since = run_git(root, "log", "--oneline", f"{sha}..HEAD", "--", *CODE_PATHS)
#             if since.strip():
#                 n = len(since.strip().splitlines())
#                 reasons.append(f"{n} commit su {'/, '.join(CODE_PATHS)}/ dopo {sha}, "
#                                f"il punto a cui {STATUS_FILE} dichiara di essere "
#                                f"riconciliato")
#
#     if not reasons:
#         log("Stop", "ok (codice invariato dal marcatore)")
#         return 0
#
#     flag.write_text("", encoding="utf-8")
#     log("Stop", "BLOCCATO: " + "; ".join(reasons))
#     sys.stderr.write(MESSAGE.format(status=STATUS_FILE,
#                                     reasons="\n  - ".join(reasons)) + "\n")
#     return 2
#
#
# if __name__ == "__main__":
#     try:
#         sys.exit(main())
#     except Exception as exc:                      # fail-open, sempre
#         try:
#             log("Stop", f"ERRORE INTERNO {type(exc).__name__} (fail-open, nessun blocco)")
#         except Exception:
#             pass
#         sys.exit(0)
#
# ---- AGENT-CONTEXT-FILE: docs/agent_docs_guide.md ----
# # Istruzioni per l'agente — creare il contesto di progetto
#
# Sei stato incaricato di organizzare la documentazione per gli agenti AI di questo
# progetto. Segui queste istruzioni. Non sono una descrizione di come è fatto un altro
# repo: sono il compito da eseguire in questo.
#
# ## Obiettivo
#
# Produrre un contesto che l'agente **non debba caricare tutto per fare una cosa sola**,
# che non vada duplicato per ogni tool, e che **non marcisca in silenzio**.
#
# Le prime due sono questioni di struttura. La terza è quella che decide se il lavoro sarà
# ancora utile fra tre mesi, e non si risolve scrivendo meglio: si risolve costruendo un
# piccolo livello che **esegue** invece di ricordare. Se produci solo i documenti, hai fatto
# metà del lavoro.
#
# ## Risultato atteso
#
# ```
# CLAUDE.md            poche righe: rinvio + import verso AGENTS.md
# AGENTS.md            ingresso canonico: cos'è il progetto + tabelle di rotta
# docs/context/        contesto per l'agente
#   invariants.md      regole inviolabili: regola | dove vive | link al perché
#   conventions.md     nomi, unità, scelte lessicali, cosa non si rinomina
#   development.md     build, test, release, comandi di verifica
#   architecture.md    mappa dei moduli, proprietà delle risorse, flusso dei dati
#   collaboration.md   come si lavora: tono, git, dove va una cosa nuova
#   <sottosistema>.md  un file per sottosistema (quanti ne servono)
#   status.md          stato corrente, difetti aperti, registro di collaudo, cronologia
# docs/                documentazione dell'applicazione, per le persone
#
# scripts/docs_lint.py         IL LIVELLO CHE ESEGUE — i documenti dicono ancora il vero?
# scripts/agent_context_init.py  porta tutto questo su un altro repo, in un file solo
# .claude/settings.json        hook versionati (SessionStart, Stop)
# .claude/hooks/               hooklib.py + session_start.py + stop_check.py
# ```
#
# Adatta i nomi al progetto, non la logica della divisione. **Scrivi gli script in Python**,
# non nella shell della piattaforma: devono girare uguali su Windows e su macOS, e due
# implementazioni della stessa cosa divergono — che è il problema che tutto questo esiste
# per evitare.
#
# ## Portare questa struttura su un altro progetto
#
# Non copiare file a mano: c'è **un inizializzatore**, `scripts/agent_context_init.py`, che
# è un solo file Python senza dipendenze e porta il payload dentro di sé.
#
# ```
# cp .../agent_context_init.py .        # nel repo da inizializzare
# python agent_context_init.py --dry-run   # dice cosa farebbe
# python agent_context_init.py             # scrive lint, hook, settings, scheletro
# ```
#
# Crea `scripts/docs_lint.py`, `.claude/hooks/{hooklib,session_start,stop_check}.py`,
# `.claude/settings.json` **con l'interprete giusto per la piattaforma** (`python` su
# Windows, `python3` altrove — rilancialo sull'altra macchina e si adegua), questa guida,
# uno scheletro di `status.md` già marcato, e le righe di `.gitignore`. Non sovrascrive
# niente senza `--force`, ed è idempotente. Alla fine stampa il prompt da incollare.
#
# **Su un repo che ha già un contesto** non si perde niente: ogni file esistente viene
# rispettato, non sovrascritto. Ma proprio per questo resta **mezzo cablato**, e in modi
# silenziosi — è il caso che va gestito bene, non quello del repo vuoto:
#
# - `.claude/settings.json`, se esiste, va **fuso**: aggiungere solo gli hook mancanti e
#   lasciare intatto il resto. Saltarlo perché esiste lascia gli script su disco senza che
#   niente li invochi, e gli hook sono fail-open: nessuno se ne accorge. Sovrascriverlo
#   cancella i permessi già configurati. Nessuna delle due è accettabile.
# - Un `status.md` scritto prima **non ha i marcatori**: né `context-verified-at`, né i
#   blocchi `session-start`. Gli hook girano e non hanno niente su cui lavorare.
#
# Per questo l'inizializzatore chiude con una **diagnosi** che elenca cosa non funziona
# ancora e come sistemarlo. Senza, l'utente crede di aver finito e ha in mano un impianto
# scollegato. Vale come regola generale: uno script che rispetta i file esistenti **deve**
# dire cosa ha lasciato a metà.
#
# **Aggiornare un repo gia' inizializzato**: `--force` riscrive i file **gestiti** — lint,
# hook, guida — alla versione di riferimento, e **non tocca mai** `docs/context/status.md`,
# che dal primo giorno contiene lavoro umano. La distinzione fra file gestiti e file seme
# e' quella che rende `--force` sicuro da usare: senza, aggiornare uno script
# significherebbe cancellare lo stato del progetto, e nessuno lo farebbe mai.
#
# E' il caso che si presenta subito: un repo dove la guida era stata copiata a mano tempo
# prima ha una versione superata proprio del file che dice all'agente cosa fare. Va
# aggiornata, e il resto va lasciato stare.
#
# **Quello che l'inizializzatore NON fa è il contesto.** I documenti nascono solo leggendo
# il repo e chiedendo all'utente ciò che nel repo non c'è. Lo script prepara il terreno; il
# lavoro lo fa l'agente col prompt che ti stampa.
#
# **Le costanti rilevabili le scrive lui.** Dove sta il codice, che estensioni ha, cosa
# sorveglia lo `Stop`: le deduce da `git ls-files` e le stampa, così sono correggibili a
# colpo d'occhio. Non c'è niente da ritarare a mano lì.
#
# Restano vuote di proposito `NOT_SYMBOLS`, `EXPECTED_ABSENT` ed `EXTERNAL_SYMBOLS`: sono
# lavoro di **dominio**, non deducibile dall'albero, e si riempiono guardando i falsi
# positivi del primo giro di lint. `NOT_SYMBOLS` in particolare contiene parole di prosa
# nella lingua dei documenti.
#
# **Mantenere l'inizializzatore.** Il payload è una copia, e una copia diverge. Per questo
# esiste `--pack`: eseguito nel progetto di riferimento, rigenera il payload dai file veri e
# **verifica che il file riscritto si esegua ancora** prima di dichiarare fatto. Quando
# migliori il lint o un hook, rilancialo.
#
# **Come chiederlo all'agente.** L'inizializzatore stampa il prompt, ed è questo. Due frasi
# cambiano l'esito, e vanno messe entrambe:
#
# > Leggi `docs/agent_docs_guide.md` ed eseguilo su questo repository. **Sono istruzioni
# > operative, non la descrizione di un altro progetto.** Prima di scrivere, **chiedimi
# > quello che non è deducibile dal repo**: stato del lavoro, decisioni prese fuori dal
# > codice, verifiche fatte a mano. In `scripts/` e `.claude/` trovi già il lint e gli hook
# > e **non vanno riscritti**: le costanti che dicono dove sta il codice sono già rilevate,
# > restano da riempire solo le liste di dominio, guardando i falsi positivi del primo giro.
#
# Senza la prima, la guida viene letta come documentazione *sul* progetto di origine invece
# che come compito. Senza la seconda, i buchi vengono riempiti per plausibilità invece che
# con una domanda — ed è esattamente l'informazione che questa struttura esiste per
# conservare.
#
# ## Le due categorie, da tenere separate
#
# - **`docs/context/` è per l'agente**: come si lavora *su* questo progetto — struttura,
#   scelte e perché, vincoli, stato del lavoro.
# - **`docs/` è per le persone**: come si comporta il prodotto verso l'esterno, per chi lo
#   integra o ne manutiene il protocollo.
#
# Se un documento serve a entrambi sta in `docs/`, e `docs/context/` ci mette un link.
# **Una sola copia, sempre**: due copie divergono e nessuno sa quale vale.
#
# ## Da dove prendi il contenuto
#
# In quest'ordine, fermandoti quando hai abbastanza:
#
# 1. Un file di istruzioni già esistente (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`, …) —
#    spesso è un monolite cresciuto per strati: è la sorgente principale.
# 2. `README`, documenti in `docs/`, commenti che spiegano un *perché* invece di un *cosa*.
# 3. La storia git: i messaggi di commit che spiegano una scelta, e i fix ricorrenti sullo
#    stesso punto (sono invarianti non scritti).
# 4. Il codice, per la mappa dei moduli e la proprietà delle risorse condivise.
# 5. **Chiedi all'utente** quello che non è deducibile da nessuna delle fonti sopra: stato
#    del lavoro, decisioni prese fuori dal repo, verifiche fatte a mano, e **qual è la
#    regola su commit e push**. Non inventarlo e non dedurlo per plausibilità.
#
# ## Come scrivere l'ingresso
#
# `AGENTS.md` è la convenzione condivisa fra tool diversi: il contenuto sta lì, e il file
# di ciascun tool è solo un rinvio. `CLAUDE.md`:
#
# ```markdown
# Il contesto di progetto è in [`AGENTS.md`](AGENTS.md), unico e condiviso fra tool
# diversi. La riga qui sotto lo importa; se l'import non fosse attivo, leggilo dal link.
#
# @AGENTS.md
# ```
#
# Per aggiungere un tool basta un file con lo stesso rinvio (`GEMINI.md`,
# `.github/copilot-instructions.md`). Crea solo quelli dei tool effettivamente in uso:
# chiedi all'utente quali sono.
#
# Tieni **sia il link sia l'import**: se l'import non venisse espanso, resta un file
# leggibile che dice dove andare, invece di un file quasi vuoto che rompe l'ingresso senza
# segnalare niente.
#
# **Non usare symlink** per condividere il rinvio fra i file dei vari tool: su Windows senza
# modalità sviluppatore git li materializza come file di testo contenenti il path, e
# l'ingresso muore in silenzio.
#
# `AGENTS.md` deve essere **agent-agnostic e code-agnostic**: niente nomi di file sorgente,
# niente istruzioni rivolte a un tool specifico. Sono le cose che cambiano più spesso, e
# ogni volta che cambiano l'ingresso diventa falso.
#
# Il suo cuore è una tabella che mappa **l'intenzione al documento**, non l'argomento al
# documento — l'agente arriva con un compito, non con una curiosità:
#
# ```markdown
# | Prima di… | Leggere |
# |---|---|
# | **qualsiasi modifica** | [invariants](...) · [conventions](...) · [development](...) |
# | orientarsi nel codice | [architecture](...) |
# | toccare un sottosistema | un link per sottosistema |
# | pianificare lavoro o dichiararlo concluso | [status](...) |
# | **dichiarare concluso** un lavoro | esegui il comando di lint dei documenti |
# ```
#
# ## Come scrivere `invariants.md`
#
# È il file che regge tutto il resto. Estrai le regole che, violate, rompono il prodotto
# **dai discorsi che le spiegano**, e mettile in una tabella di **tre** colonne: la regola,
# **dove vive nel codice**, e il link al documento che dice perché.
#
# ```markdown
# | Regola | Dove | Perché |
# |---|---|---|
# | Mai `preferences.begin()` diretto → usa il wrapper | `src/storage.c` | [storage](storage.md#nvs) |
# ```
#
# Chi legge un file solo legge quello giusto; chi sta per contravvenire ha la motivazione a
# un salto. Due misure: se la spiegazione sta nella tabella, è troppo lunga; se la regola
# non sta in una riga, non è una regola, è un capitolo — spostala nel file del sottosistema.
#
# La colonna **Dove** contiene **file e simboli, mai `file:riga`**. I numeri di riga
# driftano a ogni modifica, e una tabella di invarianti che va corretta a ogni commit smette
# di essere letta. Serve a due cose: rende la regola verificabile da uno script, e dice
# all'agente dove guardare senza cercare.
#
# ### Scrivi i divieti in una forma eseguibile
#
# Se il progetto ha feature bandite — cose che erano lì e non devono tornare — non
# descriverle a parole. Scrivi la lista dei **simboli** vietati in un paragrafo di forma
# fissa, e falla **leggere dallo script di lint** invece di duplicarla dentro lo script:
#
# ```markdown
# Nessun riferimento nel codice a: `mt25qu` / `qspi`, `Memory_Flash_*`, FatFs (`ff.h`,
# `fs/fs.h`), `USB_MASS_STORAGE`, `ad7779` / `Eeg_*`, `mcumgr` / `smp_bt`.
# ```
#
# Così il documento **è** il test: aggiungere un divieto è modificare una riga di markdown,
# e il controllo si adegua da solo. Duplicare la lista nello script crea due copie che
# divergono, che è esattamente il problema che tutta questa struttura esiste per evitare.
#
# ## Come dividere il resto
#
# **Per sottosistema** (es. rete, storage, UI, coda di invio), non per tipo di documento
# (decisioni, caveat, problemi). Chi lavora arriva da un sottosistema: deve aprire un file
# solo e trovarci com'è fatto, perché è fatto così, e cosa non deve fare.
#
# `status.md` è l'unica eccezione, perché "a che punto siamo" è una domanda trasversale.
#
# ### `status.md` invecchia male: progettalo per questo
#
# È l'unico file che cresce in modo illimitato — qui, dopo tre settimane, era il più grande
# del repo di un ordine di grandezza. Se non è progettato per invecchiare, una sessione nuova
# lo legge tutto per rispondere a «a che punto siamo», oppure si ferma alla prima sezione e
# crede a uno stato di due settimane fa.
#
# Quattro accorgimenti, tutti pagati sul campo:
#
# - **una data di ultimo aggiornamento in testa**, e un rimando esplicito del tipo «se
#   riprendi da qui, salta a *Da sapere prima di riprendere*»;
# - **una sola sezione dice lo stato corrente**, in una schermata. Il resto è cronologia. Se
#   lo stato attuale va ricostruito leggendo la cronologia in ordine, il file ha già fallito;
# - **le cose risolte si barrano, non si cancellano**: `~~voce~~ — FATTO il <data>` più il
#   link alla sezione che racconta com'è andata. Cancellare fa sparire il perché; lasciarle
#   aperte fa sembrare aperto ciò che non lo è;
# - **un marcatore di freschezza leggibile da una macchina**, in testa al file:
#
#   ```markdown
#   <!-- context-verified-at: <sha del commit> -->
#   ```
#
#   È il commit fino al quale il documento è stato **riconciliato con il codice**. Chi lo
#   riconcilia lo riporta a `HEAD`. Da solo non fa niente: serve perché uno script possa
#   dire *«7 commit hanno toccato `src/` da allora»*. Senza, la freschezza resta una
#   sensazione; con, è un numero. **È il prerequisito degli hook**: senza marcatore, un hook
#   può solo confrontare date di modifica dei file, che è un'euristica debole.
#
# La sezione di stato corrente è quella che si sporca per prima, perché la aggiorna solo chi
# si ricorda che esiste. **Va riletta ogni volta che si dichiara concluso qualcosa**, non ogni
# tanto.
#
# ### Distingui il livello di evidenza, sempre — e rendilo cercabile
#
# È la proprietà più utile emersa dall'uso, e la più facile da perdere. Non scrivere che una
# cosa funziona: scrivi **come lo sai**. Tre livelli bastano, e vanno tenuti distinti anche
# dentro la stessa tabella:
#
# - **verificato** — un comando eseguito, con il suo esito e **la data**;
# - **dedotto** — un ragionamento fondato sul codice, che nessuno ha ancora messo alla prova;
# - **assunto** — un buco dichiarato.
#
# Un test unitario verde e una prova su dispositivo reale non sono la stessa cosa, e scrivere
# «collaudato» per entrambi cancella l'unica informazione che serviva. Vale anche per le
# build: dire *su quale* è stato fatto un collaudo, perché una prova in debug non dice nulla
# sull'offuscamento della release.
#
# **Fissa la forma, non solo il concetto.** Le tre parole si scrivono sempre in grassetto e
# sempre uguali. Non è pedanteria: è ciò che trasforma la convenzione in un cruscotto
# (`git grep -c '\*\*assunto\*\*'`) e la rende controllabile da uno script — che deve
# **fallire se un verificato non porta la data**.
#
# Se il progetto usa anche un lessico di sicurezza nella *conversazione* (`[Certo]`,
# `[Probabile]`, `[Ipotesi]`), tieni i due vocabolari separati e falli separare anche dal
# lint: quello conversazionale non entra nei documenti. Sono due cose diverse — quanto sei
# sicuro adesso mentre parli, e come è nota una cosa scritta.
#
# Serve una **fuga esplicita** per la riga che *parla* della convenzione invece di
# applicarla (la legenda, la tabella che descrive il controllo). Usa un marcatore visibile e
# cercabile in fondo alla riga, `<!-- docs-lint: ignore -->`, non un'eccezione nascosta
# dentro lo script. Se ti serve spesso, la regola è sbagliata, non la riga.
#
# Regola pratica: se stai per scrivere che qualcosa è a posto e non riesci a citare il
# comando, la data o chi l'ha guardato, quello che stai scrivendo è una deduzione — segnala
# che lo è.
#
# ### Il collaudo è un registro, non una lista di cose da fare
#
# Se il progetto ha verifiche manuali ancora da eseguire, non scriverle come checklist. Dalle
# **subito** la forma finale, anche se è vuota:
#
# ```markdown
# | # | Prova | Esito | Data | Chi |
# |---|---|---|---|---|
# | E1 | ... | — | | |
# ```
#
# `Esito`: `OK` · `KO` · `—` (non eseguita). Un `OK` senza data e senza nome non vale: è la
# stessa regola del livello *verificato*.
#
# Costa cinque minuti farlo ora e significa riscrivere risultati già presi se lo fai dopo.
# Su un prodotto con un obbligo di tracciabilità — clinico, industriale, regolato — è la
# differenza fra «l'abbiamo provato» e **«possiamo dimostrare di averlo provato»**.
#
# Dentro ogni file: prima com'è fatto, poi perché quella scelta e cosa era stato scartato.
# Il *perché* è la parte che il codice non contiene e che nessuno può ricostruire dopo.
#
# ## Il livello che esegue
#
# Tutto quello sopra è **convenzione**, e una convenzione vale quanto l'aderenza di chi la
# applica. I due modi in cui questa struttura fallisce sono:
#
# 1. **Nessuno aggiorna i documenti.** L'utente se ne accorge e deve chiederlo ogni volta.
# 2. **I documenti mentono.** Una funzione è stata rinominata, il build resta verde, e non
#    se ne accorge nessuno finché qualcuno non ci lavora sopra e sbaglia.
#
# Il secondo è il pericoloso: il primo lo vede l'utente, il secondo no. Costruisci due cose,
# e **prova che funzionino** prima di dichiararle fatte.
#
# ### 1. Il lint dei documenti — è la parte più importante
#
# Uno script, versionato, che non guarda il prodotto ma **i documenti che lo descrivono**.
# Cinque controlli, in ordine di valore:
#
# | # | Controllo | Cosa intercetta |
# |---|---|---|
# | 1 | **Feature bandite** | un simbolo vietato tornato nell'albero. Lista letta da `invariants.md`, non duplicata |
# | 2 | **Identificatori** | un simbolo o percorso citato fra backtick in `docs/context/` che non esiste più |
# | 3 | **Evidenza** | un *verificato* senza data, o il lessico conversazionale entrato in un documento |
# | 4 | **Link e ancore** | un rimando o un'ancora che non risolve |
# | 5 | **Freschezza** | quanti commit hanno toccato il codice dopo il marcatore `context-verified-at` |
#
# Esce non-zero se trova errori. Quattro scelte di progetto che contano:
#
# - **Le costanti tarabili stanno in un blocco delimitato**, e chi trasporta lo script le
#   sostituisce con valori neutri. E' la differenza fra portabile e portabile a parole: le
#   estensioni, i divieti e il lessico del progetto di origine sono **sbagliati per
#   costruzione** altrove — `.dts` non significa niente in un repo TypeScript — e lasciarli
#   scaricando la ritaratura sull'agente sposta il lavoro senza risolverlo. Le due categorie
#   vanno separate:
#   - **rilevabile dal repo** (dove sta il codice, che estensioni ha, cosa sorvegliare): lo
#     deduce l'inizializzatore da `git ls-files`, che gia' distingue le sorgenti da build,
#     cache e dipendenze. Su un progetto TypeScript trova `src, api` e
#     `.ts .tsx .js .scss .json`; su uno PlatformIO, `include, lib, src` e `.cpp .h .ini`.
#   - **non rilevabile** (i divieti, il lessico di prosa): parte **vuota**, con il formato e
#     l'obbligo del motivo scritti nel commento. Un elenco vuoto e' onesto; un elenco pieno
#     di roba di un altro progetto silenzia i controlli veri.
# - **Assenza non e' errore.** `invariants.md` che non c'e' ancora, la sezione dei divieti
#   mancante, nessun `verificato`: in un progetto appena inizializzato sono lo stato
#   normale. Vanno segnalati come avvisi che dichiarano quale controllo e' inattivo, non
#   come errori — o il primo giro esce rosso e nessuno lo guarda piu'.
# - **Confronto per sottostringa** sugli identificatori. I documenti citano di proposito la
#   coda di un enum lungo (`INFO_ID_STREAM` per `USB_CONNECTION_PACKET_INFO_ID_STREAM`): è
#   la regola dell'altitudine, e il controllo deve tollerarla o diventa rumore.
# - **Due tabelle di eccezioni con il motivo obbligatorio**: `EXPECTED_ABSENT` (assente per
#   costruzione: un id ritirato, un modulo rimosso) e `EXTERNAL_SYMBOLS` (esiste, ma in una
#   libreria, non nel tuo albero). Senza motivo scritto non si aggiunge niente, o in sei mesi
#   la lista è una discarica che silenzia i controlli veri.
# - **Solo i file tracciati** per il controllo dei link: un documento di appunti non
#   versionato non deve far fallire niente.
# - **Escludi lo script da sé stesso** nel controllo sui simboli banditi — li contiene per
#   poterli cercare, e senza esclusione si accusa da solo. Ma **solo lì**: se lo escludi da
#   tutto l'albero, i simboli che lo script stesso definisce risultano inesistenti.
#
# ### 2. Gli hook — li esegue l'harness, non l'agente
#
# È tutta la differenza: `CLAUDE.md`, `AGENTS.md` e le skill dipendono dall'aderenza
# dell'agente, che è la variabile che sta fallendo. Un hook parte comunque. Vanno in un file
# di configurazione **versionato**, così valgono su ogni macchina; i permessi locali della
# macchina restano in un file separato, ignorato da git.
#
# **`SessionStart`** — inietta in contesto, a ogni avvio (`/clear` e compattazione compresi),
# le sezioni volatili: cosa è bloccato, cosa è rotto, il cruscotto dell'evidenza, e un avviso
# se il codice è andato avanti rispetto al marcatore di freschezza. Non «ricordati di
# leggere»: è già lì. Il suo stdout entra nel contesto, quindi ogni riga si paga in token a
# ogni avvio — inietta le due sezioni che contano, non tutto il file.
#
# **`Stop`** — scatta **alla fine di ogni risposta**, non a fine sessione: è il punto che
# viene frainteso più spesso, ed è anche il motivo per cui funziona. Se il codice è cambiato
# e il documento di stato è intatto, esce `2` e il turno non si chiude finché non è stato
# gestito. Non esiste nessun «momento finale» da intercettare, quindi chiudere il terminale
# non salta nessun controllo: è già avvenuto a ogni turno precedente.
#
# **Non usare un hook di fine sessione.** Non può bloccare, il suo output viene ignorato, e
# non scatta se il processo viene ucciso. `SessionStart` + `Stop` chiudono le due estremità e
# rendono quell'evento irrilevante.
#
# Due proprietà non negoziabili:
#
# - **Fail-open.** Qualunque errore interno esce `0` e non stampa. Un hook rotto deve
#   degradare ad «assente», mai a «bloccante».
# - **Una traccia su file**, in una directory non versionata (es. `.git/`), con orario,
#   evento ed esito — inclusi gli esiti silenziosi. È **obbligatoria**, non un lusso: essendo
#   fail-open, un hook rotto è indistinguibile da un hook assente, e senza traccia l'utente
#   non ha modo di sapere quale dei due ha. Non dirgli mai «se non compare l'iniezione
#   all'avvio non funziona»: lo stdout di `SessionStart` va nel contesto dell'agente, **non a
#   schermo**, quindi l'utente non vede nulla neanche quando funziona perfettamente. È
#   l'errore che ho commesso, e ha portato l'utente a credere rotto un hook che girava.
# - **Blocca una volta sola per sessione.** `Stop` scattando a ogni turno diventa martellante
#   se ripete. Lascia un marcatore (in una directory non versionata, es. `.git/`) e taci.
#
# ## Procedura
#
# L'ordine conta: è quello che evita di perdere informazione mentre riordini.
#
# 1. **Inventario.** Leggi le fonti e decidi per ogni blocco dove va. Non riscrivere ancora
#    niente.
# 2. **Sposta quasi verbatim.** Prima muovi, poi riformuli. Se riscrivi mentre sposti non
#    hai più un riferimento contro cui verificare.
# 3. **Estrai gli invarianti** in tabella, lasciando le spiegazioni dove sono.
# 4. **Scrivi l'ingresso** e i rinvii dei tool.
# 5. **Verifica** (sotto).
# 6. **Solo adesso deduplica** e accorcia, ri-verificando dopo ogni passata.
# 7. **Costruisci il livello che esegue**: prima il lint, poi gli hook. Il lint per primo,
#    perché è quello che gli hook eseguiranno, e perché ti trova errori nei documenti che
#    hai appena scritto — **aspettati che ne trovi**, ed è il segno che funziona.
# 8. **Provalo davvero.** Il lint sul repo vero; gli hook in un repo di prova usa-e-getta,
#    costruito apposta, perché nel repo vero l'albero è sporco e le condizioni non si
#    riproducono. Copri il caso in cui deve tacere, quello in cui deve bloccare, quello in
#    cui non deve ripetersi, e l'input malformato.
#
# Il passo 6 è quello che morde: togliendo un blocco che *sembra* già presente altrove
# sparisce la frase che in quel blocco era l'unica non duplicata.
#
# ## Verifica
#
# Due verifiche, con destini diversi.
#
# **Usa e getta — nessuna perdita di contenuto.** Vale solo per la migrazione: scrivi lo
# script, mostra l'output all'utente, buttalo. Ogni riga sostanziale delle fonti originali si
# ritrova in qualche file nuovo. Confronta su un frammento normalizzato (es. i primi 60
# caratteri senza spazi multipli), non sulla riga esatta: così tolleri la riformulazione ma
# la sparizione emerge. **L'output non è una lista di errori**: classifica in tre categorie —
# ritrovata verbatim, riformulata (copertura delle parole di contenuto sopra una soglia), da
# esaminare a mano — e **leggi a mano solo la terza**, decidendo per ciascuna se è una
# riscrittura voluta o una perdita. Riferisci i tre conteggi e le perdite vere che hai
# reintegrato.
#
# **Permanente — link e ancore.** Non buttarlo: **è il controllo 4 del lint**, e da lì in poi
# vive con il repo. Per ogni link markdown verso un percorso locale, con o senza ancora
# (`file.md#ancora`), il file esiste e l'ancora corrisponde a un titolo (slug in stile GitHub:
# minuscolo, spazi in trattini, punteggiatura via). Le ancore si rompono per prime: basta
# ritoccare un titolo. Salta i blocchi di codice, altrimenti i commenti `#` diventano titoli
# e i link degli esempi risultano rotti. **Includi i file di ingresso nella lista**: sono
# quelli che contengono quasi tutti i link, ed è banale dimenticarli e ottenere un "OK" che
# non ha controllato niente. Indicizza anche le ancore HTML esplicite (`<a id="...">`), che
# servono quando un titolo numerato produce uno slug che non vuoi citare.
#
# E poi: **fai girare il lint completo e mostra l'output vero**, non un riassunto.
#
# ## Trappole
#
# - **Rinominare cambiando solo maiuscole/minuscole su Windows**: il filesystem è
#   case-insensitive e `git mv A.md a.md` non fa nulla. Serve il doppio passaggio,
#   `git mv A.md tmp.md && git mv tmp.md a.md`.
# - **Cartelle non tracciate**: `git mv` fallisce; usa `mv` e poi `git add -A`.
# - **Riferimenti fuori dai `.md`**: prima di chiudere fai un `grep` dei path vecchi su
#   tutto il repo. Un commento nel codice che cita un documento rinominato non lo trova
#   nessun controllo sui markdown.
# - **Archivi storici** (piani, specifiche, note di sessioni passate): lasciali com'erano,
#   riferimenti vecchi inclusi. Riscriverli falsifica il registro di cosa si sapeva e quando.
# - **L'import va verificato davvero**, in una sessione nuova. In Claude Code lo dice
#   `/memory`, che elenca i file caricati. **Non puoi provarlo dalla sessione in cui lo
#   scrivi**: dillo all'utente invece di dichiararlo funzionante.
# - **Non confondere «l'utente non lo vede» con «non funziona».** Vale per tutto ciò che un
#   hook inietta nel contesto: è per l'agente, non per lo schermo. Quando spieghi all'utente
#   come verificare, dagli un controllo che può eseguire da solo — una traccia su file — non
#   qualcosa che dovrebbe comparirgli davanti.
# - **Il lint accusa il testo che descrive il lint.** Le righe che parlano della convenzione
#   ne violano la forma. Serve la fuga esplicita, non un'eccezione nello script.
# - **Un output di lint rumoroso non viene letto.** Se al primo giro escono cinquanta
#   segnalazioni, non correggere i documenti: **correggi i controlli** finché restano solo
#   quelle vere, poi correggi i documenti. Un lint con dieci falsi positivi è peggio di
#   nessun lint, perché insegna a ignorarlo.
# - **Il repo puo' non avere ancora un commit.** Lanciare l'inizializzatore prima del
#   primo commit e' legittimo, ma non c'e' nessuno sha a cui ancorare il marcatore di
#   freschezza. Non scrivere un marcatore finto per far passare il controllo di presenza:
#   ometterlo e segnalarlo e' l'unica opzione onesta, e il controllo va fatto sulla
#   **forma** dello sha, non sulla presenza della stringa.
# - **Lo scheletro che generi deve passare il lint che generi.** Sembra ovvio e non lo e':
#   il primo giro segnalava parole usate dallo scheletro stesso (`Esito`, `Chi`) perche' il
#   lessico neutro non le conteneva. Uno strumento che accusa il file che ha appena scritto
#   perde credibilita' al primo sguardo.
# - **La console Windows non è UTF-8.** Uno script che stampa `→` o `«»` muore con
#   `UnicodeEncodeError`. Forza la codifica dello stdout.
# - **Il costo in token dell'hook di avvio è ricorrente**, e si paga anche a ogni `/clear` e
#   a ogni compattazione. Misuralo e dillo all'utente in numeri, non a sensazione.
#
# ## Criteri di accettazione
#
# - [ ] `AGENTS.md` sta in una schermata e non nomina né file sorgente né tool.
# - [ ] Il file di ogni tool in uso è un rinvio di poche righe, con link **e** import.
# - [ ] Ogni regola inviolabile è una riga in `invariants.md` con **dove vive** e il link al
#       perché.
# - [ ] I divieti sono scritti in forma eseguibile, e il lint legge la lista dal documento.
# - [ ] Ogni sottosistema ha un file, e quel file dice anche *perché* è fatto così.
# - [ ] Ogni affermazione porta il suo livello di evidenza, nella forma fissata; ogni
#       *verificato* porta la data.
# - [ ] `status.md` ha il marcatore `context-verified-at` e una sola sezione di stato
#       corrente.
# - [ ] Le verifiche manuali sono un registro con `Esito | Data | Chi`, non una checklist.
# - [ ] Il lint esiste, è versionato, **gira pulito**, e il suo output è stato mostrato
#       all'utente.
# - [ ] Gli hook esistono, sono versionati e fail-open, e sono stati **provati** nei casi
#       taci / blocca / non ripetere / input malformato.
# - [ ] Esiste una traccia su file degli hook, e all'utente è stato spiegato come leggerla —
#       non come «guardare se compare qualcosa a schermo».
# - [ ] Nessun path vecchio è rimasto nel repo, `.md` o no.
# - [ ] La regola su commit e push che l'utente ha dichiarato è stata rispettata.
#
# ## Cosa dire alla fine
#
# Riferisci: l'albero prodotto, l'output **vero** del lint e delle prove sugli hook, cosa hai
# chiesto all'utente e cosa hai dedotto, le informazioni che non sei riuscito a collocare, e
# **cosa non hai potuto verificare da qui** (l'import, l'aggancio degli hook nella sessione
# successiva). Se una scelta ti sembrava sbagliata e l'hai fatta lo stesso perché richiesta,
# dillo.
#
# ## Mantenerla, dopo
#
# Lascia scritte le tre domande che dicono dove va una cosa nuova, in quest'ordine:
#
# 1. È una regola che, violata, rompe qualcosa? → riga in `invariants.md`, più la
#    spiegazione nel file del sottosistema.
# 2. Riguarda un sottosistema? → il suo file.
# 3. È stato del lavoro (problema noto, TODO, verifica fatta)? → `status.md`.
#
# Il lavoro che emerge durante una sessione — un difetto notato di sfuggita, una verifica
# saltata, una decisione rimandata — va in `status.md` **subito**, senza aspettare che
# l'utente lo chieda. È l'unica cosa che sopravvive alla fine della sessione.
#
# E una regola sull'ingresso: **`AGENTS.md` cresce solo se nasce un sottosistema.** Se stai
# aggiungendo una riga di contenuto lì dentro, quasi certamente va in un file linkato.
#
# Infine, la regola che tiene in piedi il livello che esegue: **il lint va fatto girare prima
# di dichiarare concluso qualcosa**, e quando trova qualcosa si corregge il documento, non si
# allarga l'eccezione.
#
