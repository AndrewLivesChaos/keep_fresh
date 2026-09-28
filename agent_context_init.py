#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agent_context_init — prepara in un repo la struttura di contesto/memoria per agenti.

Che cosa fa e che cosa NON fa
-----------------------------
FA la meccanica: scrive il lint dei documenti, gli hook e la loro configurazione con
l'interprete giusto per la piattaforma, aggiorna .gitignore, semina uno scheletro di
status.md e una configurazione vuota, e stampa il prompt da dare all'agente.

NON crea il contesto. I documenti nascono solo leggendo il repo e chiedendo all'utente
le cose che nel repo non ci sono: stato del lavoro, decisioni prese fuori dal codice,
verifiche fatte a mano. Quello e' il lavoro dell'agente, e questo script gli prepara il
terreno.

Funziona in qualunque repository git, anche vuoto: dove sta il codice non viene scritto
da nessuna parte, lo rilevano il lint e gli hook a ogni esecuzione. Un progetto che nasce
vuoto e cresce, o che si riorganizza, non richiede di rilanciare niente.

Uso
---
    python agent_context_init.py                 # dentro il repo da inizializzare
    python agent_context_init.py --dry-run       # dice cosa farebbe, non tocca niente
    python agent_context_init.py --force         # aggiorna lint, hook e guida
    python agent_context_init.py --pack          # nel repo sorgente: rigenera il payload

Un unico file Python, nessuna dipendenza. Gli hook si dichiarano in
.claude/settings.local.json, che git non traccia: il comando contiene il nome
dell'interprete, che e' un fatto della macchina. Il rovescio e' che un clone appena
fatto non ha hook finche' non ci si lancia dentro questo script una volta.

Il payload sta in fondo a questo file, in chiaro. `--pack`, eseguito nel repository
sorgente dello strumento, lo rigenera dai file veri in payload/.
Il sentinella compare DUE volte nel sorgente (nella riga che lo definisce, e in fondo):
si taglia sempre sull'ULTIMA, o lo script si tronca da solo. E' successo davvero.
"""

import argparse
import ast
import io
import json
import os
import re
import subprocess
import sys
import tomllib
import types
from datetime import date
from pathlib import Path

# La console di Windows non e' UTF-8: senza questo, un trattino lungo esce come "?".
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SENTINEL = "# ==== PAYLOAD (rigenerabile con --pack, non modificare a mano) ===="
FILE_HDR = "# ---- AGENT-CONTEXT-FILE: "
FILE_END = " ----"

# Il timbro dice da dove e quando viene questa copia. Lo scrive --pack fra le due righe
# qui sotto: ogni copia dello script e' una fotografia, e senza timbro due copie
# diverse sono indistinguibili finche' non si confronta il contenuto a mano.
# ==== TIMBRO (scritto da --pack) ====
STAMP = {
    'packed_at': '2026-09-28T10:22:37',
    'source': 'context_script',
    'commit': '8ba27e8',
    'payload_dirty': True,
    'payload_sha': 'df23ecac3846',
}
# ==== TIMBRO (fine) ====
STAMP_RE = re.compile(r"^# ==== TIMBRO \(scritto da --pack\) ====\n.*?"
                      r"^# ==== TIMBRO \(fine\) ====$", re.S | re.M)

# Dove il repository di destinazione registra quale versione ha installato. E' un file
# gestito: lo aggiorna --force insieme agli altri.
VERSION_FILE = "scripts/agent_context_version.json"

# Nel repository sorgente dello strumento, i file veri del payload stanno qui, con gli
# stessi percorsi che avranno nel repository di destinazione.
PAYLOAD_DIR = "payload"

STATUS_FILE = "docs/context/status.md"
CONFIG_FILE = "docs/context/config.toml"
# I file SEME: scritti solo se mancano, mai sovrascritti, nemmeno con --force.
SEED_FILES = {CONFIG_FILE}

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

In scripts/ trovi gia' il lint e gli hook, e NON vanno riscritti. Dove sta il
codice lo rilevano da soli a ogni esecuzione. La taratura a mano sta in
docs/context/config.toml: le liste di eccezioni del lint partono vuote di proposito, e si
riempiono guardando i falsi positivi del primo giro, con il motivo scritto per ogni voce.

Fai girare `python scripts/docs_lint.py` e mostrami l'output vero prima di dichiarare
concluso. Al primo giro sara' rumoroso: correggi prima i CONTROLLI, poi i documenti. Una
segnalazione che descrive un difetto vero — un riferimento a una rinomina mai fatta, un
simbolo sparito — non va messa a tacere: va registrata come lavoro aperto."""

# Aggiunta al prompt quando il repository aveva un contesto della versione precedente.
# Senza, l'agente legge "partono vuote" e "esegui la guida" come un lavoro da rifare da
# zero, e i documenti continuano a descrivere hook e script che non esistono piu'.
PROMPT_UPGRADE = """Il contesto esiste gia', scritto con una versione precedente di questo impianto:
non ricominciare da zero, allinealo alla guida attuale. config.toml contiene la taratura
migrata dal lint precedente: sostituisci i motivi generici con quelli veri e togli le voci
che non riguardano questo progetto. Togli dai documenti i riferimenti agli hook in
.claude/hooks/ e a ogni file che non esiste piu' (il lint li segnala), e descrivi gli hook
comuni in scripts/agent_hooks.py e il loro aggancio locale per ogni agente. La
cronologia di status.md non si riscrive: le voci superate si barrano."""


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


def payload_core(payload: dict):
    """
    Il context_core del payload, caricato in memoria. L'inizializzatore mostra cosa
    viene rilevato come codice usando lo STESSO modulo che useranno lint e hook: una
    seconda implementazione qui divergerebbe.
    """
    src = payload.get("scripts/context_core.py")
    if not src:
        return None
    mod = types.ModuleType("context_core")
    exec(compile(src, "context_core.py", "exec"), mod.__dict__)
    return mod


def payload_hash(files: dict) -> str:
    """
    L'identita' del contenuto del payload: due copie con lo stesso hash installano gli
    stessi file, qualunque cosa dicano data e commit. Si calcola sul contenuto come lo
    rilegge load_payload, cosi' --self-test puo' ricalcolarlo e confrontarlo.
    """
    import hashlib
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode("utf-8") + b"\0" + files[rel].encode("utf-8") + b"\0")
    return h.hexdigest()[:12]


def describe_stamp(stamp: dict) -> str:
    if not stamp:
        return "senza timbro (copia mai impacchettata con --pack)"
    stato = ("payload committato" if not stamp.get("payload_dirty")
             else "payload con modifiche NON committate")
    return (f"{stamp.get('packed_at', '?')}, {stamp.get('source', '?')}@"
            f"{stamp.get('commit') or 'nessun commit'} ({stato}), "
            f"payload {stamp.get('payload_sha', '?')}")


def make_stamp(root: Path, files: dict) -> dict:
    """
    Il timbro di questo impacchettamento. La data resta quella del timbro precedente se
    non e' cambiato niente di cio' che il timbro descrive: impacchettare due volte lo
    stesso contenuto non deve produrre una copia "diversa".
    """
    remote = git(root, "remote", "get-url", "origin")
    stamp = {
        "source": remote or root.name,
        "commit": head_sha(root),
        # Il timbro nomina un commit: se payload/ ha modifiche non committate, il
        # contenuto impacchettato non e' quello di quel commit, e va detto.
        "payload_dirty": bool(git(root, "status", "--porcelain", "--", PAYLOAD_DIR)),
        "payload_sha": payload_hash(files),
    }
    same = all(STAMP.get(k) == v for k, v in stamp.items())
    from datetime import datetime
    stamp["packed_at"] = (STAMP["packed_at"] if same and STAMP.get("packed_at")
                          else datetime.now().isoformat(timespec="seconds"))
    return {k: stamp[k] for k in ("packed_at", "source", "commit", "payload_dirty",
                                  "payload_sha")}


def pack(root: Path) -> int:
    """Rigenera il payload dai file veri in payload/."""
    base = root / PAYLOAD_DIR
    if not base.is_dir():
        print(f"  {PAYLOAD_DIR}/ non esiste in {root}: --pack si lancia nel repository "
              f"sorgente dello strumento", file=sys.stderr)
        return 1
    files = sorted(p for p in base.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts
                   and p.suffix not in (".pyc", ".pyo"))
    if not files:
        print(f"  {PAYLOAD_DIR}/ e' vuota: niente da impacchettare", file=sys.stderr)
        return 1

    blocks, contents = [], {}
    for p in files:
        rel = p.relative_to(base).as_posix()
        text = p.read_text(encoding="utf-8").replace("\r\n", "\n")
        if FILE_HDR in text or SENTINEL in text:
            print(f"  {rel} contiene l'intestazione del payload: non impacchettabile")
            return 1
        commented = "\n".join(("# " + l) if l else "#" for l in text.split("\n"))
        blocks.append(f"{FILE_HDR}{rel}{FILE_END}\n{commented}")
        contents[rel] = text.strip("\n") + "\n"
        print(f"  impacchettato  {rel}  ({len(text)} byte)")

    head, _ = split_on_sentinel(own_source())
    if head is None:
        print("  il sentinella compare meno di due volte: sorgente non integro",
              file=sys.stderr)
        return 1
    if len(STAMP_RE.findall(head)) != 1:
        print("  i marcatori del timbro non compaiono esattamente una volta: sorgente "
              "non integro", file=sys.stderr)
        return 1
    stamp = make_stamp(root, contents)
    literal = ("STAMP = {\n" + "".join(f"    {k!r}: {v!r},\n" for k, v in stamp.items())
               + "}")
    head = STAMP_RE.sub(lambda _: "# ==== TIMBRO (scritto da --pack) ====\n" + literal
                        + "\n# ==== TIMBRO (fine) ====", head)
    Path(__file__).write_text(head + SENTINEL + "\n" + "\n".join(blocks) + "\n",
                              encoding="utf-8", newline="\n")
    print(f"\nTimbro: {describe_stamp(stamp)}")
    if stamp["payload_dirty"]:
        print(f"  ATTENZIONE: {PAYLOAD_DIR}/ ha modifiche non committate. Il timbro lo "
              f"dichiara, ma il commit che nomina non contiene questo payload: per una "
              f"copia rintracciabile committa {PAYLOAD_DIR}/ e rilancia --pack.")

    # Il file appena riscritto deve ancora eseguirsi e rileggere il proprio payload.
    # Senza questo controllo, --pack puo' lasciare uno script rotto e dire "fatto".
    r = subprocess.run([sys.executable, str(Path(__file__)), "--self-test"],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print("  IL FILE RIGENERATO NON SI ESEGUE:\n" + (r.stderr or r.stdout),
              file=sys.stderr)
        return 1
    print(f"\nPayload rigenerato e riletto: {r.stdout.strip()}")

    return 0 if smoke_test() else 1


def smoke_test() -> bool:
    """
    Usa lo script appena scritto su un repository finto, dall'inizio: cartella vuota,
    primo commit, codice che compare dopo in una directory qualunque.

    Esiste perche' ogni difetto trovato finora stava in un passaggio che nessuno aveva
    eseguito: lo scheletro di status.md che non passava il proprio lint; un controllo
    del lint che andava in crash in ogni repository tranne quello di origine, mascherato
    da avviso; un repository nato vuoto che restava sorvegliato su una cartella
    inesistente. Correggere l'istanza non chiude la classe: solo eseguirlo davvero lo fa.
    """
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="agent-context-smoke-"))
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
               GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.autocrlf",
               GIT_CONFIG_VALUE_0="false")
    failures = []

    def run(*args, stdin=None):
        return subprocess.run(args, cwd=str(tmp), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, input=stdin)

    def step(name, cond, detail=""):
        if not cond:
            failures.append(f"{name}" + (f"\n      {detail}" if detail else ""))

    def lint(name):
        r = run(sys.executable, "scripts/docs_lint.py")
        out = r.stdout + r.stderr
        step(f"{name}: il lint esce 0", r.returncode == 0, _lint_lines(out))
        step(f"{name}: nessun errore interno del lint", "[INTERNO]" not in out,
             _lint_lines(out))
        return out

    init = [sys.executable, str(Path(__file__).resolve())]

    def stop_hook(stdin):
        return run(sys.executable, "scripts/agent_hooks.py", "stop", "--agent", "prova",
                   stdin=stdin)
    try:
        run("git", "init", "-q", ".")

        # 1. Cartella vuota, nessun commit.
        r = run(*init)
        step("repo vuoto: l'inizializzatore esce 0", r.returncode == 0, r.stderr[-800:])
        lint("repo vuoto")

        # 2. Primo commit, e secondo giro: lo scheletro intatto riceve il marcatore.
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", "init")
        r = run(*init)
        status = (tmp / STATUS_FILE).read_text(encoding="utf-8")
        step("dopo il primo commit: marcatore aggiunto allo scheletro",
             "context-verified-at:" in status, r.stdout[-800:])
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", "marcatore")
        lint("dopo il primo commit")

        # 3. Il codice compare dopo, in una directory che nessuno ha dichiarato.
        (tmp / "lib").mkdir()
        (tmp / "lib" / "core.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        r = stop_hook('{"session_id":"s1"}')
        step("codice nuovo non committato: Stop blocca", _blocks(r, "lib"),
             f"exit {r.returncode}: {r.stdout[-400:]}")
        r = stop_hook('{"session_id":"s1"}')
        step("Stop non blocca due volte nella stessa sessione",
             r.returncode == 0 and not r.stdout.strip(), f"exit {r.returncode}: {r.stdout}")
        r = stop_hook('{"session_id":"s9","stop_hook_active":true}')
        step("Stop non blocca un turno gia' prolungato da un hook",
             r.returncode == 0 and not r.stdout.strip(), f"exit {r.returncode}: {r.stdout}")
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", "codice in lib")
        out = lint("codice comparso dopo")
        step("il lint vede il commit sul codice nuovo",
             "[FRESCHEZZA]" in out and "lib/" in out, _lint_lines(out))
        r = stop_hook('{"session_id":"s2"}')
        step("codice nuovo committato: Stop blocca in una sessione nuova",
             _blocks(r, "lib/"), f"exit {r.returncode}: {r.stdout[-400:]}")
        r = run(sys.executable, "scripts/agent_hooks.py", "session-start", "--agent", "prova",
                stdin='{"source":"startup"}')
        step("SessionStart esce 0 e inietta lo stato",
             r.returncode == 0 and "Stato del progetto" in r.stdout
             and "lib/" in r.stdout, f"exit {r.returncode}: {r.stdout[-400:]}")
        r = stop_hook("non json")
        step("Stop con input malformato non va in errore", r.returncode == 0,
             f"exit {r.returncode}: {r.stderr[-300:]}")
        log = tmp / ".git" / "agent-hooks.log"
        step("la traccia degli hook registra l'agente",
             log.is_file() and "prova" in log.read_text(encoding="utf-8"))

        # Il tetto all'iniezione: oltre il tetto l'hook inietta l'indice e il lint avvisa,
        # senza fallire. Si abbassa il tetto invece di gonfiare status.md.
        cfg_p = tmp / CONFIG_FILE
        cfg_orig = cfg_p.read_text(encoding="utf-8")
        cfg_p.write_text(cfg_orig.replace("max_injection_chars = 8000",
                                          "max_injection_chars = 40"), encoding="utf-8")
        r = run(sys.executable, "scripts/agent_hooks.py", "session-start", "--agent", "prova",
                stdin='{"source":"startup"}')
        step("oltre il tetto SessionStart inietta solo l'indice",
             r.returncode == 0 and "solo il loro indice" in r.stdout,
             f"exit {r.returncode}: {r.stdout[-400:]}")
        r = run(sys.executable, "scripts/docs_lint.py")
        step("oltre il tetto il lint avvisa e non fallisce",
             r.returncode == 0 and "[PESO]" in r.stdout, _lint_lines(r.stdout))
        cfg_p.write_text(cfg_orig, encoding="utf-8")

        # La misura dei consumi, su una trascrizione finta con numeri noti. Il messaggio
        # m1 compare due volte, come fa lo streaming: conta una volta, con l'ultimo usage.
        home = Path(tempfile.mkdtemp(prefix="agent-context-claude-"))
        try:
            proj = home / "projects" / "finto"
            proj.mkdir(parents=True)
            base = {"sessionId": "S1", "cwd": str(tmp.resolve()),
                    "timestamp": "2026-09-01T10:00:00Z"}

            def asst(mid, usage):
                return dict(base, type="assistant", message={
                    "id": mid, "model": "claude-opus-5-5", "content": [], "usage": usage})
            rows = [dict(base, type="user", message={"role": "user", "content": "ciao"}),
                    asst("m1", {"input_tokens": 2, "cache_creation_input_tokens": 1000,
                                "cache_read_input_tokens": 0, "output_tokens": 1}),
                    asst("m1", {"input_tokens": 2, "cache_creation_input_tokens": 1000,
                                "cache_creation": {"ephemeral_1h_input_tokens": 1000,
                                                   "ephemeral_5m_input_tokens": 0},
                                "cache_read_input_tokens": 0, "output_tokens": 10}),
                    asst("m2", {"input_tokens": 3, "cache_creation_input_tokens": 0,
                                "cache_read_input_tokens": 1000, "output_tokens": 20})]
            (proj / "s1.jsonl").write_text(
                "".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")
            r = subprocess.run([sys.executable, "scripts/context_cost.py", "--json"],
                               cwd=str(tmp), capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               env=dict(env, CLAUDE_CONFIG_DIR=str(home),
                                        CODEX_HOME=str(home / "codex")))
            try:
                ss = json.loads(r.stdout)["claude_sessions"]
            except (ValueError, KeyError):
                ss = []
            s = ss[0] if len(ss) == 1 else {}
            # (2+3)*4 + 1000*4*2 + 1000*0,20 + (10+20)*20, in milionesimi di dollaro
            step("context_cost: token e costo esatti su una trascrizione nota",
                 s.get("calls") == 2 and s.get("in") == 5 and s.get("w1") == 1000
                 and s.get("r") == 1000 and s.get("out") == 30
                 and abs(s.get("cost", 0) - 0.00882) < 1e-9,
                 f"exit {r.returncode}: {r.stdout[-300:]}{r.stderr[-300:]}")
        finally:
            shutil.rmtree(home, ignore_errors=True)

        # Ogni agente del registro e' agganciato nel suo file locale, ignorato da git,
        # con un comando che punta allo script che esiste.
        gi = (tmp / ".gitignore").read_text(encoding="utf-8")
        for name, agent in AGENTS.items():
            try:
                cfg = json.loads((tmp / agent["config"]).read_text(encoding="utf-8"))
                cmds = [h["command"] for ev, _ in HOOK_EVENTS
                        for e in cfg["hooks"][ev] for h in e["hooks"]]
            except (OSError, ValueError, KeyError, TypeError):
                cmds = []
            step(f"{agent['label']}: due hook agganciati a {HOOKS_SCRIPT}, senza percorsi",
                 len(cmds) == 2 and all(HOOK_BOOTSTRAP in c and f"--agent {name}" in c
                                        and str(tmp) not in c and tmp.as_posix() not in c
                                        for c in cmds), f"{cmds}")
            # Il comando agganciato, eseguito davvero da una sottocartella: e' cosi' che
            # lo lancia Codex quando la sessione parte li'.
            sub = tmp / "lib"
            for c in cmds[:1]:
                r = subprocess.run(c, shell=True, cwd=str(sub), capture_output=True,
                                   text=True, encoding="utf-8", errors="replace",
                                   env=env, input='{"source":"startup"}')
                step(f"{agent['label']}: il comando agganciato gira da una sottocartella",
                     r.returncode == 0 and "Stato del progetto" in r.stdout,
                     f"exit {r.returncode}: {r.stdout[-300:]}{r.stderr[-300:]}")
            step(f"{agent['label']}: {agent['config']} e' in .gitignore",
                 agent["config"] in gi)
        step("nessun __pycache__ lasciato nel repository",
             not any(tmp.rglob("__pycache__")))

        # 4. Versione: registrata all'installazione, deriva segnalata, --force la sana.
        try:
            rec = json.loads((tmp / VERSION_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rec = {}
        # Il timbro va riletto dal file: questo processo e' partito prima che --pack lo
        # riscrivesse, e in memoria ha ancora quello vecchio.
        head, _ = split_on_sentinel(own_source())
        m = STAMP_RE.search(head or "")
        try:
            written = ast.literal_eval(m.group(0).split("STAMP = ", 1)[1]
                                       .rsplit("# ==== TIMBRO (fine)", 1)[0].strip())
        except (AttributeError, IndexError, ValueError, SyntaxError):
            written = None
        step("la versione installata e' registrata col timbro dello script",
             bool(written) and rec == written, f"registrata {rec}, timbro {written}")
        lint_py = tmp / "scripts" / "docs_lint.py"
        lint_py.write_text(lint_py.read_text(encoding="utf-8") + "# ritocco\n",
                           encoding="utf-8")
        r = run(*init)
        step("un file gestito diverso dal payload viene segnalato",
             "non coincidono con questa copia" in r.stdout and "docs_lint.py" in r.stdout,
             r.stdout[-600:])
        r = run(*init, "--force")
        r2 = run(*init)
        step("--force riallinea e la segnalazione sparisce",
             r.returncode == 0 and "non coincidono" not in r2.stdout, r2.stdout[-600:])

        # 5. Un repository con il contesto della versione precedente, com'era
        # un progetto: lint con la taratura e CODE_DIRS scritti dentro, un archivio
        # escluso di proposito che contiene un simbolo bandito, hook in .claude/hooks/
        # con i loro compilati committati, una copia vecchia dell'inizializzatore.
        # Un repository nuovo, non la stessa cartella svuotata: su Windows gli oggetti di
        # git sono in sola lettura e rmtree li lascia dove sono.
        primo = tmp
        tmp = Path(tempfile.mkdtemp(prefix="agent-context-smoke-"))
        run("git", "init", "-q", ".")
        for rel, text in {
            "src/app.ts": "export const x = 1\n",
            "archivio/proto.html": "<p>blurb</p>\n",
            "scripts/docs_lint.py": (f"{TUNING_BEGIN}\nCODE_DIRS = ['src']\nCODE_FILES = []\n"
                                     f"EXPECTED_ABSENT = {{'blurb': 'ritirato'}}\n"
                                     f"{TUNING_END}\n"),
            "scripts/agent_context_init.py": "# copia vecchia, senza timbro\n",
            ".claude/hooks/hooklib.py": "\n",
            ".claude/hooks/session_start.py": "\n",
            ".claude/hooks/stop_check.py": "\n",
            ".claude/hooks/__pycache__/hooklib.cpython-314.pyc": "x",
        }.items():
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp / rel).write_text(text, encoding="utf-8")
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", "versione precedente")
        r = run(*init, "--force")
        step("aggiornamento dalla versione precedente: esce 0", r.returncode == 0,
             r.stderr[-800:])
        cfg = (tmp / CONFIG_FILE).read_text(encoding="utf-8")
        step("l'archivio escluso dal lint precedente resta escluso",
             '"archivio/"' in cfg and '"blurb"' in cfg, cfg[:600])
        step(".claude/hooks/ tolta del tutto, compilati compresi",
             not (tmp / ".claude" / "hooks").exists(), r.stdout[-600:])
        step("la copia vecchia dell'inizializzatore viene segnalata",
             "scripts/agent_context_init.py e' un'altra copia" in r.stdout, r.stdout[-800:])
        step("il prompt chiede di allineare, non di rifare",
             "Il contesto esiste gia'" in r.stdout, r.stdout[-800:])
        lint("aggiornamento dalla versione precedente")
    finally:
        for d in {tmp, locals().get("primo", tmp)}:
            shutil.rmtree(d, ignore_errors=True)

    if not failures:
        print("Prova a vuoto: repo vuoto, primo commit, codice comparso dopo e "
              "aggiornamento dalla versione precedente, tutto ok.")
        return True
    print("\nPROVA A VUOTO FALLITA — cio' che questo script genera non si comporta come\n"
          "dovrebbe. Payload scritto ma da correggere:", file=sys.stderr)
    for f in failures:
        print("  - " + f, file=sys.stderr)
    return False


def _blocks(r, needle: str) -> bool:
    """L'hook di fine turno ha chiesto di non chiudere, citando `needle`?"""
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return False
    return (r.returncode == 0 and d.get("decision") == "block"
            and needle in d.get("reason", ""))


def _lint_lines(out: str) -> str:
    return "\n      ".join(l.strip() for l in out.splitlines()
                           if l.strip().startswith("[") or l.startswith("ERRORI"))


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


def head_sha(root):
    sha = git(root, "rev-parse", "--short", "HEAD")
    return sha if re.fullmatch(r"[0-9a-f]{7,40}", sha or "") else None


class Writer:
    """
    Due categorie di file, e la distinzione e' quella che rende --force sicuro.

    GESTITI (lint, modulo comune, hook, guida): li possiede questo script. Sovrascriverli
    con --force e' il modo previsto di AGGIORNARE un repo gia' inizializzato.

    SEME (status.md, config.toml): sono solo un punto di partenza, e da li' in poi
    contengono lavoro umano. Non si sovrascrivono MAI, nemmeno con --force.
    """

    def __init__(self, root: Path, force: bool, dry: bool):
        self.root, self.force, self.dry = root, force, dry
        self.written, self.updated, self.skipped, self.protected = [], [], [], []

    def put(self, rel: str, content: str, seed: bool = False) -> None:
        p = self.root / rel
        if p.exists():
            if seed:
                self.protected.append(rel)
                return
            if not self.force:
                self.skipped.append(rel)
                return
        (self.updated if p.exists() else self.written).append(rel)
        if self.dry:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")


# ------------------------------------------------------------ migrazione e marcatore

TUNING_BEGIN = "# ==== TARATURA DEL PROGETTO (inizio) ===="
TUNING_END = "# ==== TARATURA DEL PROGETTO (fine) ===="
LEGACY_TABLES = [("NOT_SYMBOLS", "not_symbols"), ("EXPECTED_ABSENT", "expected_absent"),
                 ("EXTERNAL_SYMBOLS", "external_symbols"), ("RECEIVED_DOCS", "received_docs")]


def legacy_tuning(root: Path, payload: dict) -> dict:
    """
    Le liste di dominio di un lint della versione precedente, che le teneva in un blocco
    di taratura dentro lo script. Servono a riempire config.toml la prima volta che
    viene creato, cosi' --force non cancella la taratura fatta a mano.

    Le costanti su dove sta il codice non si migrano: adesso si rilevano.
    """
    p = root / "scripts" / "docs_lint.py"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    i, j = text.find(TUNING_BEGIN), text.find(TUNING_END)
    if i < 0 or j < i:
        return {}
    try:
        tree = ast.parse(text[i:j])
    except SyntaxError:
        return {}
    # Le parole del nucleo neutro stanno gia' nel lint nuovo: migrarle sarebbe rumore.
    core_words = set()
    m = re.search(r"NOT_SYMBOLS_CORE = (\{.*?\n\})", payload.get("scripts/docs_lint.py", ""), re.S)
    if m:
        try:
            core_words = {w.lower() for w in ast.literal_eval(m.group(1))}
        except (ValueError, SyntaxError):
            pass

    found = {}
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        name = node.targets[0].id
        table = dict(LEGACY_TABLES).get(name)
        if not table:
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            continue
        if isinstance(value, dict):
            entries = {str(k): str(v) for k, v in value.items()}
        elif isinstance(value, (set, list, tuple)):
            entries = {str(k): "migrato dalla taratura della versione precedente"
                       for k in value}
        else:
            continue
        if table == "not_symbols":
            entries = {k: v for k, v in entries.items() if k.lower() not in core_words}
        if entries:
            found[table] = entries

    # Prefissi di percorsi esterni scritti direttamente nel codice del controllo 2
    # (`tok.startswith("zephyr/")`): adesso sono voci di external_symbols che finiscono
    # con "/". `build/` resta escluso dal lint nuovo per conto suo.
    for prefix in re.findall(r'tok\.startswith\("([^"]+/)"\)', text):
        if prefix != "build/":
            found.setdefault("external_symbols", {}).setdefault(
                prefix, "prefisso esterno migrato dalla versione precedente del lint")
    return found


def legacy_code_scope(root: Path):
    """
    Cosa considerava codice un lint della versione precedente: CODE_DIRS e CODE_FILES,
    scritti a mano. None se il lint non e' di quella versione.

    Il lint nuovo il codice lo rileva da solo, e rileva anche quello che il vecchio
    escludeva DI PROPOSITO — un archivio congelato, un export — tacendo le ragioni.
    Senza questo confronto la migrazione perde l'esclusione e il primo giro di lint
    accusa l'archivio.
    """
    try:
        text = (root / "scripts" / "docs_lint.py").read_text(encoding="utf-8")
    except OSError:
        return None
    if "context_core" in text:
        return None
    names = set()
    for const in ("CODE_DIRS", "CODE_FILES"):
        m = re.search(rf"^{const}\s*=\s*(\[.*?\]|\{{.*?\}})", text, re.S | re.M)
        if not m:
            continue
        try:
            names |= {str(v).strip("/") for v in ast.literal_eval(m.group(1))}
        except (ValueError, SyntaxError):
            return None
    return names or None


def render_config(seed: str, tables: dict, exclude: list = ()) -> str:
    """Scrive le voci migrate sotto le rispettive tabelle del seme, dopo i commenti."""
    if exclude:
        voci = "".join(f"    {json.dumps(e, ensure_ascii=False)},  # non era codice per "
                       f"il lint della versione precedente\n" for e in exclude)
        seed = seed.replace("\nexclude = []\n", f"\nexclude = [\n{voci}]\n", 1)
    lines = seed.split("\n")
    for table, entries in tables.items():
        header = f"[lint.{table}]"
        if header not in lines:
            continue
        k = lines.index(header) + 1
        while k < len(lines) and lines[k].startswith("#"):
            k += 1
        new = [f"{json.dumps(key, ensure_ascii=False)} = {json.dumps(val, ensure_ascii=False)}"
               for key, val in sorted(entries.items(), key=lambda kv: kv[0].lower())]
        lines[k:k] = new
    return "\n".join(lines)


def skeleton_intact(text: str) -> bool:
    """status.md e' ancora lo scheletro, a parte la data? Allora e' ancora nostro."""
    norm = lambda s: re.sub(r"\s+", " ",
                            re.sub(r"\*\*Ultimo aggiornamento: [^*]*\*\*", "", s)).strip()
    return norm(text) == norm(STATUS_SKELETON.format(marker="", today=""))


def add_marker(root: Path, dry: bool) -> str:
    """
    Aggiunge il marcatore di freschezza allo scheletro rimasto senza, perche' era stato
    scritto prima del primo commit. Solo se lo scheletro e' intatto: uno status.md
    toccato a mano contiene lavoro, e il marcatore lo mette chi lo riconcilia.
    """
    p = root / STATUS_FILE
    sha = head_sha(root)
    if not p.is_file() or sha is None:
        return ""
    text = p.read_text(encoding="utf-8", errors="replace")
    if "context-verified-at:" in text or not skeleton_intact(text):
        return ""
    if not dry:
        p.write_text(STATUS_SKELETON.format(marker=f"\n<!-- context-verified-at: {sha} -->\n",
                                            today=date.today().isoformat()),
                     encoding="utf-8", newline="\n")
    return f"marcatore di freschezza aggiunto allo scheletro di status.md ({sha})"


# ------------------------------------------------------------------ agenti e loro hook

HOOKS_SCRIPT = "scripts/agent_hooks.py"
# (evento come lo chiamano gli agenti, argomento di agent_hooks.py)
HOOK_EVENTS = [("SessionStart", "session-start"), ("Stop", "stop")]

# Gli script di hook delle versioni precedenti, specifici di Claude Code. Riconoscerli
# serve a migrare gli agganci che li invocano, e a toglierli con --force.
LEGACY_HOOK_FILES = [".claude/hooks/hooklib.py", ".claude/hooks/session_start.py",
                     ".claude/hooks/stop_check.py"]
# Un comando e' "nostro" se invoca uno di questi.
OUR_SCRIPTS = ("agent_hooks.py", "session_start.py", "stop_check.py")

# Il registro degli agenti. L'unica cosa specifica di un agente e' DOVE si aggancia: gli
# script sono comuni, e il protocollo (stdout all'avvio, decisione JSON a fine turno) e'
# quello che gli agenti qui elencati hanno in comune. Aggiungere un agente con lo stesso
# formato di configurazione vuol dire aggiungere una voce.
#
#   config  file LOCALE della macchina dove si dichiarano gli hook; va in .gitignore,
#           perche' il comando contiene il nome dell'interprete (python o python3)
#   shared  file di configurazione versionato dello stesso agente, da cui una versione
#           precedente potrebbe aver lasciato i nostri hook (girerebbero due volte)
#   steps   cosa deve fare l'utente su ogni macchina perche' gli hook partano davvero
AGENTS = {
    "claude": {
        "label": "Claude Code",
        "config": ".claude/settings.local.json",
        "shared": ".claude/settings.json",
        "steps": "Nessun passo: gli hook in .claude/settings.local.json partono alla "
                 "prossima sessione",
    },
    "codex": {
        "label": "Codex",
        "config": ".codex/hooks.json",
        "shared": None,
        # Provato il 2026-09-17 su Windows con Codex 0.154.0: senza progetto fidato e
        # senza approvazione, gli hook del repository vengono saltati SENZA avvisi.
        "steps": "Apri Codex in questo repository e accetta di fidarti del progetto; "
                 "poi, dentro Codex, `/hooks` e approva i due hook. Va rifatto se "
                 ".codex/hooks.json cambia",
    },
}

GITIGNORE_LINES = [a["config"] for a in AGENTS.values()]

# I nomi con cui un hook puo' invocare Python. Solo un comando che comincia cosi' viene
# riscritto: un percorso assoluto o un virtualenv sono una scelta di chi ce li ha messi.
INTERP_RE = re.compile(r"^\s*(?:python3|python|py)(?:\s+-3)?(?=\s)")


# Trova la radice del repository da dove parte la sessione ed esegue lo script da li'.
# Niente sintassi di shell (niente $, %, backtick, virgolette doppie interne): lo stesso
# testo gira in PowerShell, cmd, bash e sh. Se lo script manca, l'errore e' visibile
# nell'agente: un aggancio rotto non deve sembrare un aggancio assente.
HOOK_BOOTSTRAP = ("import runpy,subprocess,sys;"
                  "r=subprocess.run(['git','rev-parse','--show-toplevel'],"
                  "capture_output=True,text=True).stdout.strip();"
                  f"r and runpy.run_path(r+'/{HOOKS_SCRIPT}',run_name='__main__')")


def hook_command(interp: str, event_arg: str, agent: str) -> str:
    """
    Nessun percorso nel comando: la radice la trova git a ogni esecuzione, quindi spostare
    o rinominare la cartella del repository non rompe l'aggancio. Un percorso relativo non
    basterebbe: Codex esegue il comando dalla cartella in cui e' partita la sessione, che
    puo' essere una sottocartella. E nemmeno $CLAUDE_PROJECT_DIR: su Windows Codex esegue
    il comando in PowerShell (provato il 2026-09-17), dove $NOME non e' una variabile
    d'ambiente. Provato il 2026-09-26 su Windows in PowerShell 5.1, cmd e Git Bash, da una
    sottocartella.
    """
    return f'{interp} -c "{HOOK_BOOTSTRAP}" {event_arg} --agent {agent}'


def hook_entry(command: str) -> dict:
    return {"hooks": [{"type": "command", "command": command, "timeout": 20}]}


def _our_hooks(entries):
    """Coppie (entry, hook) dei nostri hook in una lista di entry di un evento."""
    found = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        inner = entry.get("hooks")
        for h in inner if isinstance(inner, list) else []:
            if isinstance(h, dict) and isinstance(h.get("command"), str) \
                    and any(s in h["command"] for s in OUR_SCRIPTS):
                found.append((entry, h))
    return found


def _drop_hook(entries: list, entry: dict, hook: dict) -> None:
    entry["hooks"] = [h for h in entry["hooks"] if h is not hook]
    if not entry["hooks"]:
        entries.remove(entry)


def unhook_shared(root: Path, dry: bool) -> list:
    """
    Toglie i NOSTRI hook dai file di configurazione versionati degli agenti.

    Una versione precedente di questo script li metteva li'. Adesso stanno nel file
    locale, e dichiararli in tutti e due NON e' innocuo: girano due volte. (Provato su
    Claude Code 2.1.269: sonda in entrambi i file, due esecuzioni.)

    Il file condiviso e' tracciato da git, quindi la rimozione finisce nel diff
    dell'utente: va dichiarata, non fatta di nascosto. Gli hook di altri restano.
    """
    messaggi = []
    for name, agent in AGENTS.items():
        if not agent["shared"]:
            continue
        p = root / agent["shared"]
        try:
            cfg = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
        except (OSError, ValueError):
            cfg = None
        if not isinstance(cfg, dict) or not isinstance(cfg.get("hooks"), dict):
            continue
        tolti = []
        for ev, _ in HOOK_EVENTS:
            entries = cfg["hooks"].get(ev)
            ours = _our_hooks(entries)
            if not ours:
                continue
            for entry, hook in ours:
                _drop_hook(entries, entry, hook)
            tolti.append(ev)
            if not entries:
                del cfg["hooks"][ev]
        if not tolti:
            continue
        if not cfg["hooks"]:
            del cfg["hooks"]
        if not dry:
            p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8", newline="\n")
        messaggi.append(f"tolti {', '.join(tolti)} da {agent['shared']} (adesso stanno "
                        f"in {agent['config']}; dichiarati in due posti girerebbero due "
                        f"volte). E' un file tracciato: il diff e' voluto")
    return messaggi


def merge_agent(root: Path, name: str, interp: str, dry: bool) -> str:
    """
    Aggancia i nostri hook nel file locale dell'agente. Il file va FUSO, non saltato e
    non sovrascritto: saltarlo perche' esiste lascia gli script su disco senza che
    niente li invochi, sovrascriverlo cancella i permessi e gli hook di altri.

    I nostri hook gia' presenti si riscrivono se invocano Python per nome: vale per un
    interprete di un'altra piattaforma (il repo e' stato clonato da un'altra macchina),
    per il percorso assoluto che le versioni precedenti scrivevano nel comando e per
    gli script di una versione precedente. Un comando con un interprete che non
    riconosciamo — un percorso assoluto, un virtualenv — e' una scelta di chi l'ha
    scritto: non si tocca, si segnala.
    """
    p = root / AGENTS[name]["config"]
    wanted = {ev: hook_command(interp, arg, name) for ev, arg in HOOK_EVENTS}

    if not p.exists():
        cfg = {"hooks": {ev: [hook_entry(cmd)] for ev, cmd in wanted.items()}}
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
    if not isinstance(cfg, dict) or not isinstance(cfg.setdefault("hooks", {}), dict):
        return "NON TOCCATO: non ha la forma attesa. Gli hook NON sono agganciati"

    added, riscritti, doppi, estranei = [], 0, 0, 0
    for ev, cmd in wanted.items():
        entries = cfg["hooks"].setdefault(ev, [])
        if not isinstance(entries, list):
            return f"NON TOCCATO: 'hooks.{ev}' non e' una lista. Aggancia a mano"
        ours = _our_hooks(entries)
        if not ours:
            entries.append(hook_entry(cmd))
            added.append(ev)
            continue
        tenuto = False
        for entry, hook in ours:
            if not INTERP_RE.match(hook["command"]):
                estranei += 1
                continue
            if tenuto:
                _drop_hook(entries, entry, hook)       # un doppione: girerebbe due volte
                doppi += 1
                continue
            tenuto = True
            if hook["command"] != cmd:
                hook["command"] = cmd
                riscritti += 1

    if not (added or riscritti or doppi):
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
        parti.append(f"{riscritti} comandi riscritti (interprete, percorso o script di "
                     f"una versione precedente)")
    if doppi:
        parti.append(f"{doppi} doppioni tolti")
    return "fuso: " + "; ".join(parti) + " (il resto lasciato intatto)"


def retire_legacy_hooks(root: Path, force: bool, dry: bool) -> str:
    """
    Gli script di hook della versione precedente, in .claude/hooks/. Si tolgono solo con
    --force, come ogni file gestito, e solo se nessun aggancio locale li invoca ancora:
    togliere uno script che un comando su misura usa lo farebbe fallire in silenzio.
    """
    presenti = [rel for rel in LEGACY_HOOK_FILES if (root / rel).is_file()]
    if not presenti:
        return ""
    # I compilati degli stessi script: senza toglierli la cartella non resta vuota, e
    # capita che siano stati anche committati.
    cache = root / ".claude" / "hooks" / "__pycache__"
    compilati = [p for p in cache.glob("*.pyc")
                 if p.name.split(".", 1)[0] in {Path(r).stem for r in LEGACY_HOOK_FILES}]
    for agent in AGENTS.values():
        p = root / agent["config"]
        try:
            blob = p.read_text(encoding="utf-8") if p.is_file() else ""
        except OSError:
            blob = ""
        if any(Path(rel).name in blob for rel in presenti):
            return (f"{', '.join(presenti)} ancora invocati da {agent['config']}: "
                    f"lasciati dove sono")
    if not force:
        return (f"{', '.join(presenti)} non servono piu' (gli hook ora sono in "
                f"{HOOKS_SCRIPT}): --force li toglie")
    if not dry:
        for p in [root / rel for rel in presenti] + compilati:
            p.unlink()
        for d in (cache, root / ".claude" / "hooks"):
            try:
                if d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
            except OSError:
                pass
    tolti = presenti + ([f"{len(compilati)} compilati in .claude/hooks/__pycache__/"]
                        if compilati else [])
    return f"tolti {', '.join(tolti)}: gli hook ora sono in {HOOKS_SCRIPT}"


CMD_RE = re.compile(r'"command"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"')


def interpreter_works(nome: str) -> bool:
    """
    Lo esegue davvero, invece di fidarsi del nome.

    Su Windows `python3` c'e' quasi sempre nel PATH ed e' un rimando al Microsoft
    Store: non esegue niente ed esce con un codice di errore. Un controllo del tipo
    "esiste nel PATH?" direbbe di si' e sbaglierebbe.
    """
    try:
        # Non basta che parta: lint e hook leggono config.toml con tomllib, che esiste
        # da Python 3.11. Un python3 di sistema piu' vecchio (macOS ha la 3.9) parte e
        # poi fallisce sull'import, e gli hook fail-open non lo dicono.
        r = subprocess.run(nome.split() + ["-c", "import tomllib"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        return r.returncode == 0
    except OSError:
        return False


def codex_trusted(root: Path):
    """
    Il progetto risulta fidato nella configurazione utente di Codex? None se non si
    puo' dire. Il confronto e' sul percorso esatto: provato il 2026-09-17 che una
    cartella madre fidata non basta a far partire gli hook di un repository al suo
    interno. La forma delle chiavi e' quella osservata su Windows; altrove e' dedotta.
    """
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    try:
        with open(home / "config.toml", "rb") as fh:
            projects = tomllib.load(fh).get("projects", {})
    except (OSError, tomllib.TOMLDecodeError):
        return None
    norm = lambda s: os.path.normcase(os.path.normpath(str(s))).rstrip("\\/")
    target = norm(root.resolve())
    for key, val in projects.items() if isinstance(projects, dict) else []:
        if norm(key) == target and isinstance(val, dict):
            return val.get("trust_level") == "trusted"
    return False


def git_tracks(root: Path, rel: str) -> bool:
    try:
        r = subprocess.run(["git", "ls-files", "--error-unmatch", "--", rel],
                           capture_output=True, text=True, cwd=str(root))
        return r.returncode == 0
    except OSError:
        return False


# ------------------------------------------------------------------------- diagnosi

def diagnose(root: Path, interp: str) -> list:
    """
    Cosa resta NON funzionante dopo l'inizializzazione. Serve soprattutto quando il
    repo aveva gia' un contesto: i file esistenti vengono rispettati, e proprio per
    questo possono restare privi di cio' che lint e hook usano. Si controlla OGNI agente
    del registro: "tutto agganciato" per uno non dice niente degli altri.
    """
    problemi = []

    lint = root / "scripts" / "docs_lint.py"
    if lint.is_file() and "context_core" not in lint.read_text(encoding="utf-8",
                                                               errors="replace"):
        problemi.append(
            "scripts/docs_lint.py e' della versione precedente, con la taratura scritta\n"
            "     dentro lo script. Rilancia con --force per aggiornarlo: le liste di\n"
            "     eccezioni sono gia' state copiate in docs/context/config.toml, e\n"
            "     config.toml non viene mai sovrascritto.")
    for rel in ("scripts/context_core.py", HOOKS_SCRIPT):
        if not (root / rel).is_file():
            problemi.append(f"{rel} manca: lint e hook non funzionano. Rilancia con --force.")

    c = root / CONFIG_FILE
    if c.is_file():
        try:
            with open(c, "rb") as fh:
                tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            problemi.append(f"{CONFIG_FILE} non e' TOML valido ({exc}): il lint lo "
                            f"segnala come errore e ne ignora le eccezioni.")

    st = root / STATUS_FILE
    if not st.is_file():
        problemi.append(f"{STATUS_FILE} non esiste: gli hook non hanno niente da leggere.")
    else:
        text = st.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"<!--\s*context-verified-at:\s*[0-9a-f]{7,40}\s*-->", text):
            if head_sha(root) is None:
                problemi.append(
                    "il repository non ha ancora un commit, quindi status.md non ha il\n"
                    "     marcatore di freschezza. Fai il primo commit e rilancia questo "
                    "script:\n     lo aggiunge da solo.")
            else:
                problemi.append(
                    f"{STATUS_FILE} non ha il marcatore di freschezza. Aggiungi in "
                    "testa:\n     <!-- context-verified-at: $(git rev-parse --short HEAD) -->\n"
                    "     Senza, il controllo 5 del lint e l'avviso dell'hook non funzionano.")
        if "session-start: begin" not in text:
            problemi.append(
                f"{STATUS_FILE} non ha i blocchi <!-- session-start: begin -->\n"
                "     ... <!-- session-start: end -->. L'hook di avvio non inietta niente:\n"
                "     delimita le sezioni che vuoi vedere a ogni sessione (cosa blocca,\n"
                "     difetti aperti).")

    provati = {}
    for name, agent in AGENTS.items():
        label, rel = agent["label"], agent["config"]
        p = root / rel
        if not p.is_file():
            problemi.append(f"{label}: {rel} manca, gli hook NON sono agganciati.")
            continue
        try:
            blob = p.read_text(encoding="utf-8")
        except OSError:
            problemi.append(f"{label}: {rel} non leggibile.")
            continue
        comandi = [json.loads('"' + m.group(1) + '"') for m in CMD_RE.finditer(blob)]
        nostri = [cmd for cmd in comandi if any(s in cmd for s in OUR_SCRIPTS)]
        for ev, arg in HOOK_EVENTS:
            if not any(HOOKS_SCRIPT.rsplit("/", 1)[-1] in cmd and f" {arg}" in cmd
                       for cmd in nostri):
                problemi.append(f"{label}: l'hook {ev} non invoca {HOOKS_SCRIPT} in {rel}.")
        if git_tracks(root, rel):
            problemi.append(f"{label}: {rel} e' tracciato da git, ma contiene "
                            f"l'interprete di QUESTA macchina.\n     Toglilo dall'indice "
                            f"(git rm --cached {rel}): e' gia' in .gitignore.")
        if agent["shared"] and (root / agent["shared"]).is_file():
            altro = (root / agent["shared"]).read_text(encoding="utf-8", errors="replace")
            if any(s in altro for s in OUR_SCRIPTS):
                problemi.append(f"{label}: i nostri hook compaiono ANCHE in "
                                f"{agent['shared']}: girerebbero due volte.")
        for cmd in nostri:
            # Le versioni precedenti scrivevano il percorso assoluto dello script: basta
            # spostare la cartella perche' l'aggancio punti al vuoto.
            m = re.search(r'"([^"]+\.py)"', cmd)
            if m and not Path(m.group(1)).is_file():
                problemi.append(f"{label}: un hook invoca {m.group(1)}, che non esiste. "
                                f"Rilancia l'inizializzatore, che riscrive il comando.")
            elif m:
                problemi.append(f"{label}: un hook invoca lo script con un percorso "
                                f"assoluto, che si rompe se la cartella si sposta.\n"
                                f"     Rilancia l'inizializzatore, che lo riscrive senza "
                                f"percorsi.")
            # Agganciato non vuol dire eseguibile: l'interprete deve esistere QUI.
            n = INTERP_RE.match(cmd)
            nome = n.group(0).strip() if n else None
            if nome and nome not in provati:
                provati[nome] = interpreter_works(nome)
                if not provati[nome]:
                    problemi.append(
                        f"gli hook invocano `{nome}`, che su questa macchina non esegue "
                        f"niente o e' piu' vecchio di Python 3.11\n"
                        f"     (provato: `{nome} -c \"import tomllib\"`). Sono fail-open: "
                        f"non protesterebbero, semplicemente non\n     girerebbero. "
                        f"Installa un Python 3.11 o piu' recente raggiungibile con questo "
                        f"nome,\n     oppure riscrivi a mano il comando con l'interprete "
                        f"che usi.")
        if name == "codex" and codex_trusted(root) is False:
            problemi.append(f"{label}: il progetto non risulta fidato in "
                            f"~/.codex/config.toml, e senza fiducia Codex salta gli hook\n"
                            f"     del repository senza avvisare.\n     {agent['steps']}.")
    problemi += stale_copies(root)
    return problemi


def stale_copies(root: Path) -> list:
    """
    Altre copie dell'inizializzatore nel repository, diverse da questa. Un progetto ne
    tiene una versionata per agganciare gli hook sui cloni: dopo un aggiornamento fatto
    con una copia piu' nuova, quella resta indietro e il prossimo clone installa lei.
    """
    me = Path(__file__).resolve()
    vecchie = []
    # Solo i file che git conosce: node_modules e simili non contano, e sono lenti.
    elenco = git(root, "ls-files", "--cached", "--others", "--exclude-standard",
                 "--", "*agent_context_init.py")
    for rel in filter(None, elenco.splitlines()):
        p = root / rel
        if not p.is_file() or p.resolve() == me:
            continue
        try:
            head, _ = split_on_sentinel(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            head = None
        m = STAMP_RE.search(head or "")
        try:
            suo = ast.literal_eval(m.group(0).split("STAMP = ", 1)[1]
                                   .rsplit("# ==== TIMBRO (fine)", 1)[0].strip())
        except (AttributeError, IndexError, ValueError, SyntaxError):
            suo = None
        if suo != STAMP:
            vecchie.append(
                f"{rel} e' un'altra copia dell'inizializzatore, diversa da questa: "
                f"{describe_stamp(suo) if suo else 'senza timbro, versione precedente'}.\n"
                f"     Chi la lancia su un clone installa quella. Sostituiscila con questa "
                f"copia, o toglila se non serve.")
    return vecchie


def version_drift(root: Path, payload: dict) -> list:
    """
    I file gestiti installati sono quelli di questa copia dello script? Si confronta il
    CONTENUTO, non la registrazione: la registrazione dice chi li ha scritti, ma un file
    toccato a mano dopo non lo dice nessuno.
    """
    lint = root / "scripts" / "docs_lint.py"
    if lint.is_file() and "context_core" not in lint.read_text(encoding="utf-8",
                                                               errors="replace"):
        return []                       # versione precedente: la diagnosi lo dice gia'

    diversi = []
    for rel, content in payload.items():
        p = root / rel
        if rel in SEED_FILES or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8").replace("\r\n", "\n")
        except (OSError, UnicodeDecodeError):
            text = None
        if text is None or text.strip("\n") != content.strip("\n"):
            diversi.append(rel)
    if not diversi:
        return []

    try:
        installata = describe_stamp(json.loads((root / VERSION_FILE).read_text(
            encoding="utf-8")))
    except (OSError, ValueError):
        installata = "non registrata"
    return [
        f"{len(diversi)} file gestiti non coincidono con questa copia dello script: "
        f"{', '.join(diversi)}.\n"
        f"     Installata: {installata}\n"
        f"     Questa    : {describe_stamp(STAMP)}\n"
        f"     Se questa e' piu' recente, rilancia con --force (status.md e config.toml "
        f"non vengono toccati).\n     Se quei file sono stati modificati a mano, "
        f"--force cancella le modifiche: guardale prima."]


def ensure_gitignore(root: Path, dry: bool) -> str:
    gi = root / ".gitignore"
    text = gi.read_text(encoding="utf-8") if gi.is_file() else ""
    add = [l for l in GITIGNORE_LINES if l not in text]
    if not add:
        return "gia' a posto"
    if not dry:
        with open(gi, "a", encoding="utf-8") as fh:
            fh.write("\n# Agenti: aggancio degli hook, con l'interprete di questa "
                     "macchina\n")
            for l in add:
                fh.write(l + "\n")
    return f"aggiunte {len(add)} righe"


# ------------------------------------------------------------------------------ main

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Prepara la struttura di contesto/memoria per agenti in un repo.")
    ap.add_argument("--dry-run", action="store_true", help="dice cosa farebbe")
    ap.add_argument("--force", action="store_true",
                    help="aggiorna lint, hook e guida. Non tocca status.md ne' "
                         "config.toml, che sono tuoi")
    ap.add_argument("--pack", action="store_true",
                    help="nel repository sorgente dello strumento: rigenera il payload "
                         "da payload/")
    ap.add_argument("--self-test", action="store_true",
                    help="verifica che il payload sia leggibile e coincida col timbro")
    ap.add_argument("--version", action="store_true",
                    help="dice da dove e quando viene questa copia ed esce")
    args = ap.parse_args()

    if args.version:
        print(f"agent_context_init — {describe_stamp(STAMP)}")
        return 0

    if args.self_test:
        p = load_payload()
        if not p:
            print("payload illeggibile", file=sys.stderr)
            return 1
        # Un payload ritoccato a mano dopo l'impacchettamento non e' piu' quello che il
        # timbro descrive: la copia mentirebbe su cosa installa.
        if STAMP and STAMP.get("payload_sha") != payload_hash(p):
            print(f"il payload non coincide col timbro: hash {payload_hash(p)}, timbro "
                  f"{STAMP.get('payload_sha')}. E' stato modificato dopo --pack.",
                  file=sys.stderr)
            return 1
        print(f"{len(p)} file, {sum(len(v) for v in p.values())} byte, "
              f"hash {payload_hash(p)}")
        return 0

    root = repo_root()
    if root is None:
        print("Non sei dentro un repository git. Fai prima `git init`.", file=sys.stderr)
        return 1

    if args.pack:
        print(f"Rigenero il payload da {root / PAYLOAD_DIR}")
        return pack(root)

    payload = load_payload()
    if not payload:
        print("Questo file non ha payload: rigeneralo con --pack nel repository "
              "sorgente dello strumento.", file=sys.stderr)
        return 1

    interp = "python" if sys.platform == "win32" else "python3"
    print(f"Versione   : {describe_stamp(STAMP)}")
    print(f"Repository : {root}")
    print(f"Piattaforma: {sys.platform}  ->  interprete degli hook: {interp}")
    if args.dry_run:
        print("MODALITA' DRY-RUN: non viene scritto niente.")
    print()

    # Un contesto della versione precedente va riconosciuto PRIMA di scrivere: dopo,
    # --force ha gia' sostituito il lint e tolto gli hook vecchi.
    old_lint = root / "scripts" / "docs_lint.py"
    precedente = (any((root / rel).is_file() for rel in LEGACY_HOOK_FILES)
                  or (old_lint.is_file() and "context_core" not in
                      old_lint.read_text(encoding="utf-8", errors="replace")))

    core, labels = payload_core(payload), []
    if core is not None:
        cfg, _ = core.load_config(root)
        files = core.code_files(root, cfg)
        _, labels = core.code_scope(root, cfg)
        print("Codice rilevato adesso (lint e hook lo rilevano di nuovo a ogni esecuzione):")
        if labels:
            print(f"  {len(files)} file in {', '.join(labels[:12])}"
                  + (" …" if len(labels) > 12 else ""))
        else:
            print("  nessuno, per ora. Va bene: quando il codice arriva, viene visto.")
        print()

    # La taratura di una versione precedente va letta PRIMA che --force riscriva il lint.
    migrated = {} if (root / CONFIG_FILE).exists() else legacy_tuning(root, payload)
    # Cio' che la rilevazione prende e il lint precedente escludeva. Si continua a
    # escluderlo: e' il comportamento che il progetto aveva, e lo si dice.
    old_scope = None if (root / CONFIG_FILE).exists() else legacy_code_scope(root)
    excluded = [l for l in labels if l.rstrip("/") not in old_scope] if old_scope else []

    w = Writer(root, args.force, args.dry_run)
    for rel, content in payload.items():
        if rel == CONFIG_FILE and (migrated or excluded):
            rendered = render_config(content, migrated, excluded)
            try:
                tomllib.loads(rendered)
                content = rendered
            except tomllib.TOMLDecodeError as exc:
                print(f"  ATTENZIONE: la taratura precedente non e' migrabile ({exc}): "
                      f"config.toml parte vuoto, riportala a mano.")
                migrated, excluded = {}, []
        w.put(rel, content, seed=rel in SEED_FILES)
    if STAMP:
        # Segue la regola dei file gestiti: se i file non vengono aggiornati, nemmeno
        # la registrazione di quale versione li ha scritti.
        w.put(VERSION_FILE, json.dumps(STAMP, indent=2, ensure_ascii=False) + "\n")

    # In un repo senza ancora un commit non esiste uno sha da scrivere. Meglio
    # nessun marcatore, che il giro dopo il primo commit aggiunge, di un marcatore
    # finto che passa il controllo di presenza e mente sul contenuto.
    sha = head_sha(root)
    marker = f"\n<!-- context-verified-at: {sha} -->\n" if sha else "\n"
    status_existed = (root / STATUS_FILE).exists()
    w.put(STATUS_FILE, STATUS_SKELETON.format(marker=marker, today=date.today().isoformat()),
          seed=True)

    for rel in w.written:
        print(f"  creato   {rel}")
    for rel in w.updated:
        print(f"  aggiornato {rel}")
    for rel in w.skipped:
        print(f"  esisteva {rel}  (--force lo aggiorna)")
    for rel in w.protected:
        print(f"  TUO      {rel}  (mai sovrascritto, nemmeno con --force)")
    if migrated and CONFIG_FILE in w.written:
        n = sum(len(v) for v in migrated.values())
        print(f"  migrate  {n} voci di taratura dal lint precedente in {CONFIG_FILE}")
    if excluded and CONFIG_FILE in w.written:
        print(f"  migrate  esclusi dal codice, come nel lint precedente: "
              f"{', '.join(excluded)}\n"
              f"           Se uno di questi e' codice, toglilo da [code] exclude in "
              f"{CONFIG_FILE}.")
    if status_existed:
        fatto = add_marker(root, args.dry_run)
        if fatto:
            print(f"  status:     {fatto}")
    for name, agent in AGENTS.items():
        print(f"  {agent['label']:<12}{merge_agent(root, name, interp, args.dry_run)}"
              f"  ->  {agent['config']}")
    for msg in unhook_shared(root, args.dry_run):
        print(f"  migrazione: {msg}")
    vecchi = retire_legacy_hooks(root, args.force, args.dry_run)
    if vecchi:
        print(f"  hook vecchi: {vecchi}")
    print(f"  .gitignore: {ensure_gitignore(root, args.dry_run)}")

    problemi = (diagnose(root, interp) + version_drift(root, payload)
                if not args.dry_run else [])
    # L'elenco si stampa UNA volta, dentro il prompt: e' li' che serve, perche' il prompt
    # e' cio' che si copia all'agente. Qui sopra resta solo l'avviso che c'e'.
    if not args.dry_run:
        if problemi:
            n = len(problemi)
            print("\n" + "!" * 74)
            print(f"DA SISTEMARE — {n} cosa non funziona ancora." if n == 1
                  else f"DA SISTEMARE — {n} cose non funzionano ancora.")
            print("L'elenco e' in fondo al prompt qui sotto, per l'agente o per te.")
            print("!" * 74)
        else:
            print("\n  Diagnosi: tutto agganciato, marcatori a posto.")

    print("\n" + "=" * 74)
    print("Fatta la meccanica. Il contesto lo deve ancora scrivere l'agente.")
    print("=" * 74)
    taratura = ("parte con quanto migrato dal lint precedente: va controllata"
                if (migrated or excluded) and CONFIG_FILE in w.written
                else "parte vuota di\nproposito")
    print(f"""
Non devi ritarare niente a mano. Dove sta il codice lo rilevano il lint e gli hook a
ogni esecuzione. La taratura di dominio sta in docs/context/config.toml, {taratura}
e si completa guardando i falsi positivi del primo giro di lint: e' gia'
chiesto nel prompt qui sotto.

1. Apri una sessione dell'agente e incollagli questo prompt:
""")
    print("-" * 74)
    print(PROMPT)
    if precedente:
        print()
        print(PROMPT_UPGRADE)
    if problemi:
        print()
        print("Inoltre l'inizializzatore ha lasciato aperti questi punti, sistemali:")
        for n, msg in enumerate(problemi, 1):
            print(f"  {n}. {msg}")
    print("-" * 74)
    print("""
2. Perche' gli hook partano davvero, per ogni agente che usi su questa macchina:""")
    for agent in AGENTS.values():
        print(f"     {agent['label']}: {agent['steps']}.")
    print("""
3. Quando l'agente ha finito, verifica tu:
     python scripts/docs_lint.py          deve uscire senza errori
     git log --oneline -5                 cosa ha committato
   e che gli hook girino davvero: apri una sessione nuova e guarda
     .git/agent-hooks.log                 una riga per ogni esecuzione, con l'agente
   Non aspettarti di vedere niente a schermo: l'iniezione va nel contesto
   dell'agente, non nel tuo terminale.
   Su ogni ALTRA macchina dove clonerai questo repo, rilancia questo script una
   volta: gli agganci degli hook sono locali e non vengono clonati.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ==== PAYLOAD (rigenerabile con --pack, non modificare a mano) ====
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
# AGENTS.md            ingresso canonico: cos'è il progetto + tabelle di rotta
# CLAUDE.md            poche righe: rinvio + import verso AGENTS.md (solo se si usa Claude Code)
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
# docs/context/config.toml     taratura a mano del lint: eccezioni, correzioni alla rilevazione
#
# scripts/docs_lint.py         IL LIVELLO CHE ESEGUE — i documenti dicono ancora il vero?
# scripts/agent_hooks.py       hook di avvio e di fine turno, uguali per ogni agente
# scripts/context_core.py      comune a lint e hook: dove sta il codice, marcatori
# scripts/context_cost.py      quanto pesa il contesto: sessioni misurate, misura esatta
#
# aggancio degli hook, NON versionato, uno per agente e per macchina:
# .claude/settings.local.json  Claude Code
# .codex/hooks.json            Codex
# ```
#
# Adatta i nomi al progetto, non la logica della divisione. **Scrivi gli script in Python**,
# non nella shell della piattaforma: devono girare uguali su Windows e su macOS, e due
# implementazioni della stessa cosa divergono — che è il problema che tutto questo esiste
# per evitare.
#
# ## Portare questa struttura su un altro progetto
#
# Non copiare file a mano: c'è **un inizializzatore**, `agent_context_init.py`, che è un
# solo file Python senza dipendenze e porta il payload dentro di sé. Lo si copia nel repo e
# lo si lancia; funziona anche in un repo appena creato con `git init`, senza codice.
#
# ```
# python agent_context_init.py --dry-run   # dice cosa farebbe
# python agent_context_init.py             # scrive lint, hook, aggancio, scheletri
# ```
#
# Crea `scripts/docs_lint.py`, `scripts/agent_hooks.py`, `scripts/context_core.py`, questa
# guida, uno scheletro di `status.md`, una `config.toml` vuota, e aggancia gli hook nel file
# locale di **ogni agente supportato** (oggi Claude Code e Codex) **con l'interprete giusto
# per la macchina** (`python` su Windows, `python3` altrove). Il comando non contiene
# percorsi: la radice del repository la trova git a ogni esecuzione, quindi spostare la
# cartella non rompe gli hook. Non sovrascrive niente senza `--force`, ed è idempotente. Alla fine stampa il
# prompt da incollare e i passi che restano all'utente per ciascun agente.
#
# **L'aggancio degli hook non è versionato, di proposito.** Il comando contiene il nome
# dell'interprete, che è un fatto della macchina: in un file tracciato viaggerebbero con il repo e
# arriverebbero sbagliati altrove, e gli hook, essendo fail-open, non girerebbero senza
# dirlo. Per questo **non dichiarare mai gli hook in un file di configurazione versionato**,
# come `.claude/settings.json`: dichiarati sia lì sia nel file locale girano due volte. Il
# prezzo è che un clone appena fatto non ha hook finché non si lancia l'inizializzatore una
# volta su quella macchina: va detto all'utente.
#
# **Codex salta gli hook del repository senza avvisare** finché il progetto non è segnato
# come fidato e gli hook non sono stati approvati dall'utente con `/hooks` dentro Codex; va
# rifatto quando `.codex/hooks.json` cambia. L'agente non può farlo al posto dell'utente:
# glielo deve dire.
#
# **Su un repo che ha già un contesto** non si perde niente: ogni file esistente viene
# rispettato, non sovrascritto. Ma proprio per questo resta **mezzo cablato**, e in modi
# silenziosi — è il caso che va gestito bene, non quello del repo vuoto:
#
# - il file locale di un agente, se esiste, va **fuso**: aggiungere solo gli hook
#   mancanti e lasciare intatto il resto. Saltarlo perché esiste lascia gli script su disco
#   senza che niente li invochi, e gli hook sono fail-open: nessuno se ne accorge.
#   Sovrascriverlo cancella i permessi già configurati. Nessuna delle due è accettabile.
# - Un `status.md` scritto prima **non ha i marcatori**: né `context-verified-at`, né i
#   blocchi `session-start`. Gli hook girano e non hanno niente su cui lavorare.
#
# Per questo l'inizializzatore chiude con una **diagnosi** che elenca cosa non funziona
# ancora e come sistemarlo. Senza, l'utente crede di aver finito e ha in mano un impianto
# scollegato. Vale come regola generale: uno script che rispetta i file esistenti **deve**
# dire cosa ha lasciato a metà.
#
# **Aggiornare un repo gia' inizializzato**: `--force` riscrive i file **gestiti** — lint,
# modulo comune, hook, guida — alla versione di riferimento, e **non tocca mai** i file
# **seme**, `docs/context/status.md` e `docs/context/config.toml`, che dal primo giorno
# contengono lavoro umano. La distinzione fra file gestiti e file seme e' quella che rende
# `--force` sicuro da usare: senza, aggiornare uno script significherebbe cancellare lo
# stato del progetto o la taratura, e nessuno lo farebbe mai.
#
# E' il caso che si presenta subito: un repo dove la guida era stata copiata a mano tempo
# prima ha una versione superata proprio del file che dice all'agente cosa fare. Va
# aggiornata, e il resto va lasciato stare.
#
# **Quello che l'inizializzatore NON fa è il contesto.** I documenti nascono solo leggendo
# il repo e chiedendo all'utente ciò che nel repo non c'è. Lo script prepara il terreno; il
# lavoro lo fa l'agente col prompt che ti stampa.
#
# **Dove sta il codice non si scrive da nessuna parte.** Lint e hook lo rilevano a ogni
# esecuzione dai file che git conosce, tracciati e nuovi non ignorati. Un progetto che nasce
# vuoto, cresce o si riorganizza resta sorvegliato senza toccare niente. Il lint stampa cosa
# ha rilevato nel controllo 0: se sbaglia, si corregge con `[code] include` ed `exclude` in
# `docs/context/config.toml`, non modificando gli script.
#
# Restano vuote di proposito le tabelle `[lint.not_symbols]`, `[lint.expected_absent]`,
# `[lint.external_symbols]` e `[lint.received_docs]` di `config.toml`: sono lavoro di
# **dominio**, non deducibile dall'albero, e si riempiono guardando i falsi positivi del
# primo giro di lint. `not_symbols` in particolare contiene parole di prosa nella lingua dei
# documenti.
#
# **Non modificare gli script installati.** Sono gestiti: `--force` li riporta alla versione
# di riferimento. Una correzione fatta lì dentro si perde al primo aggiornamento; se serve,
# va fatta nello strumento, non nella copia.
#
# **Come chiederlo all'agente.** L'inizializzatore stampa il prompt, ed è questo. Due frasi
# cambiano l'esito, e vanno messe entrambe:
#
# > Leggi `docs/agent_docs_guide.md` ed eseguilo su questo repository. **Sono istruzioni
# > operative, non la descrizione di un altro progetto.** Prima di scrivere, **chiedimi
# > quello che non è deducibile dal repo**: stato del lavoro, decisioni prese fuori dal
# > codice, verifiche fatte a mano. In `scripts/` trovi già il lint e gli hook
# > e **non vanno riscritti**: dove sta il codice lo rilevano da soli, restano da riempire
# > solo le liste di dominio in `config.toml`, guardando i falsi positivi del primo giro.
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
# di ciascun tool è solo un rinvio, e solo per i tool che non leggono `AGENTS.md` da soli.
# Codex lo legge da solo, anche partendo da una sottocartella (provato il 2026-09-17 con
# Codex 0.154.0). Claude Code legge `CLAUDE.md` e non `AGENTS.md`, secondo la sua
# documentazione, quindi gli serve il rinvio. `CLAUDE.md`:
#
# ```markdown
# Il contesto di progetto è in [`AGENTS.md`](AGENTS.md), unico e condiviso fra tool
# diversi. La riga qui sotto lo importa; se l'import non fosse attivo, leggilo dal link.
#
# @AGENTS.md
# ```
#
# Per aggiungere un tool che non legge `AGENTS.md` basta un file con lo stesso rinvio.
# Crea solo quelli dei tool effettivamente in uso: chiedi all'utente quali sono, e verifica
# sulla documentazione del tool se legge `AGENTS.md` da solo, invece di darlo per scontato.
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
# Sei accorgimenti, tutti pagati sul campo:
#
# - **una data di ultimo aggiornamento in testa**, e un rimando esplicito del tipo «se
#   riprendi da qui, salta a *Da sapere prima di riprendere*»;
# - **una sola sezione dice lo stato corrente**, in una schermata. Il resto è cronologia. Se
#   lo stato attuale va ricostruito leggendo la cronologia in ordine, il file ha già fallito;
# - **le cose risolte si barrano e, nello stesso commit, escono dalla sezione degli aperti**:
#   `~~voce~~ — FATTO il <data>` va nella cronologia, e fra gli aperti resta al più il link.
#   Cancellare fa sparire il perché; lasciarle fra gli aperti fa sembrare aperto ciò che non
#   lo è, e le fa pagare in token a ogni avvio (vedi sotto);
# - **i blocchi `session-start` restano sotto il tetto** di `config.toml`
#   (`[context] max_injection_chars`, 8000 caratteri di partenza): lo stato corrente in una
#   schermata e i difetti aperti come **indice**, una riga per voce con il link all'ancora
#   del dettaglio, che sta fuori dai blocchi. Quello che sta fra i marcatori entra nel
#   contesto a ogni avvio, `/clear` e compattazione, e resta in ogni chiamata della sessione.
#   Oltre il tetto l'hook inietta solo titoli e prime righe, e il lint avvisa;
# - **i registri che crescono in modo illimitato** — collaudo, cronologia — stanno in file
#   propri linkati da `status.md` appena superano qualche schermata. `status.md` risponde a
#   «a che punto siamo»; se per rispondere va letto un file da centinaia di KB, costa più
#   della domanda;
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
# Cosa succede senza questi accorgimenti, misurato su un repository di questo impianto: in
# tre settimane la sezione dei difetti aperti è arrivata a 53 voci, almeno 8 delle quali già chiuse,
# e i blocchi iniettati sono passati da 26 mila a 135 mila caratteri [misurato, traccia
# degli hook], circa 60 mila token a ogni avvio [stimato]. Ridotti al loro indice pesano
# 3.096 token [misurato con `context_cost.py misura`, 2026-09-28]. Nessuno se n'era
# accorto, perché la crescita si vedeva solo nella traccia: per questo ora c'è un tetto.
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
# Sei controlli, in ordine di valore:
#
# | # | Controllo | Cosa intercetta |
# |---|---|---|
# | 1 | **Feature bandite** | un simbolo vietato tornato nell'albero. Lista letta da `invariants.md`, non duplicata |
# | 2 | **Identificatori** | un simbolo o percorso citato fra backtick in `docs/context/` che non esiste più |
# | 3 | **Evidenza** | un *verificato* senza data, o il lessico conversazionale entrato in un documento |
# | 4 | **Link e ancore** | un rimando o un'ancora che non risolve |
# | 5 | **Freschezza** | quanti commit hanno toccato il codice dopo il marcatore `context-verified-at` |
# | 6 | **Peso** | quanto testo l'hook di avvio inietta; avvisa se i blocchi `session-start` superano il tetto |
#
# Esce non-zero se trova errori. Le scelte di progetto che contano:
#
# - **Cio' che e' rilevabile si rileva a ogni esecuzione, non si scrive.** Dove sta il
#   codice lo dicono i file che git conosce, che gia' distingue le sorgenti da build, cache e
#   dipendenze. Una costante scritta al momento dell'installazione e' giusta quel giorno e
#   falsa appena il progetto cresce: un repo nato vuoto resterebbe sorvegliato su una
#   cartella che non esiste. Lint e hook usano lo **stesso** modulo per rilevarlo, o
#   finiscono per rispondere in modo diverso alla stessa domanda.
# - **Cio' che non e' rilevabile sta in un file seme** (`config.toml`: i divieti, il
#   lessico di prosa, le eccezioni), che parte **vuoto** con il formato e l'obbligo del
#   motivo scritti nei commenti, e che nessun aggiornamento sovrascrive. Un elenco vuoto e'
#   onesto; un elenco pieno di roba di un altro progetto silenzia i controlli veri.
# - **Assenza non e' errore.** `invariants.md` che non c'e' ancora, la sezione dei divieti
#   mancante, nessun `verificato`: in un progetto appena inizializzato sono lo stato
#   normale. Vanno segnalati come avvisi che dichiarano quale controllo e' inattivo, non
#   come errori — o il primo giro esce rosso e nessuno lo guarda piu'.
# - **Confronto per sottostringa** sugli identificatori. I documenti citano di proposito la
#   coda di un enum lungo (`INFO_ID_STREAM` per `USB_CONNECTION_PACKET_INFO_ID_STREAM`): è
#   la regola dell'altitudine, e il controllo deve tollerarla o diventa rumore.
# - **Tabelle di eccezioni con il motivo obbligatorio**: `expected_absent` (assente per
#   costruzione: un id ritirato, un modulo rimosso) ed `external_symbols` (esiste, ma in una
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
# dell'agente, che è la variabile che sta fallendo. Un hook parte comunque.
#
# Gli **script** degli hook sono versionati e **uguali per ogni agente**
# (`scripts/agent_hooks.py`); il loro **aggancio** no. Il comando che li invoca contiene
# il nome dell'interprete, che cambia da macchina a macchina, quindi sta nella
# configurazione locale di ciascun agente, ignorata da git, e lo scrive l'inizializzatore su
# ogni macchina. Non spostarlo nella configurazione versionata "perché valga ovunque":
# arriverebbe sbagliato su un'altra macchina, e se resta anche nel file locale gli hook
# girano due volte.
#
# Gli script usano solo cio' che gli agenti supportati hanno in comune: all'avvio, testo su
# stdout; a fine turno, uscita `0` con `{"decision": "block", "reason": "..."}` su stdout.
# **Non usare l'uscita `2` per bloccare**: Codex 0.154.0 la tratta come errore e chiude il
# turno comunque, mentre la decisione JSON blocca sia lì sia su Claude Code 2.1.274
# (provato il 2026-09-17, su Windows).
#
# **`SessionStart`** — inietta in contesto, a ogni avvio (`/clear` e compattazione compresi),
# le sezioni volatili: cosa è bloccato, cosa è rotto, il cruscotto dell'evidenza, e un avviso
# se il codice è andato avanti rispetto al marcatore di freschezza. Non «ricordati di
# leggere»: è già lì. Il suo stdout entra nel contesto, quindi ogni riga si paga in token a
# ogni avvio e in ogni chiamata successiva — inietta le due sezioni che contano, non tutto
# il file. Il testo lo costruisce `context_core.build_injection`, lo stesso per l'hook, il
# lint e la misura dei consumi: così i tre non possono dare numeri diversi. Oltre il tetto
# di `config.toml` l'hook inietta solo l'indice dei blocchi (titoli e prima riga di ogni
# voce) con un avviso, e chiede all'agente di leggere nel file **la sezione che gli serve**,
# non il file intero: su uno `status.md` di centinaia di KB, «rileggi il file» costa più
# dell'iniezione stessa.
#
# **`Stop`** — scatta **alla fine di ogni risposta**, non a fine sessione: è il punto che
# viene frainteso più spesso, ed è anche il motivo per cui funziona. Se il codice è cambiato
# e il documento di stato è intatto, chiede di non chiudere e il turno continua finché non è
# stato gestito. Non esiste nessun «momento finale» da intercettare, quindi chiudere il terminale
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
#   se ripete. Lascia un marcatore (in una directory non versionata, es. `.git/`) e taci; e
#   non bloccare un turno che l'agente ha gia' prolungato per un hook (`stop_hook_active`).
#
# ### 3. La misura dei consumi — quanto pesa davvero il contesto
#
# ```
# python scripts/context_cost.py            resoconto: niente chiamate al modello
# python scripts/context_cost.py misura     misura esatta del contesto fisso (~$0,40)
# ```
#
# Il resoconto legge ciò che gli agenti registrano — le trascrizioni di Claude Code e i
# `token_count` di Codex — e ne ricava, sessione per sessione, chiamate, contesto all'avvio e
# massimo, token scritti e letti in cache, costo a listino. Poi le letture dei documenti di
# contesto e l'andamento dell'iniezione nel tempo, dalla traccia degli hook.
#
# Ogni numero porta la sua fonte, ed è la regola da rispettare quando lo riporti:
# **[misurato]** è ciò che l'agente ha registrato o che la misura esatta ha trovato;
# **[stimato]** è un calcolo (caratteri divisi per un rapporto, token per un prezzo). Non
# dare mai un numero di token come fatto se lo strumento lo marca stimato.
#
# `misura` è l'unico modo di sapere quanti token pesano `AGENTS.md` e l'iniezione **senza**
# un'API di conteggio: lancia Claude Code headless in una copia usa e getta, una volta
# vuota, una con le istruzioni, una anche con l'iniezione, e sottrae i totali che Claude
# Code riporta. Tutto ciò che non è di questo impianto si elide. Rifalla dopo aver cambiato
# `AGENTS.md` o i blocchi `session-start`: il resoconto sa se la misura è ancora di quei
# contenuti e, se non lo è, torna a stimare e lo dice.
#
# Cosa hanno trovato le prime misure, per orientarsi: sulla macchina dove sono state fatte,
# con i suoi plugin, la base dell'harness vale circa 28 mila token e l'impianto ne aggiunge
# 3-4 mila [misurato, 2026-09-28], mentre il contesto medio per chiamata nelle sessioni
# lunghe va da 175 a 260 mila token [misurato, trascrizioni]. **Il costo lo decide la lunghezza delle sessioni**: una sessione
# per compito, `/clear` fra un compito e l'altro, sottoagenti per le letture pesanti.
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
#   `/context`, alla voce dei file di memoria caricati. **Non puoi provarlo dalla sessione in cui lo
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
# - [ ] Gli script degli hook esistono, sono versionati e fail-open, e il loro aggancio sta
#       **solo** nella configurazione locale della macchina, non in quella versionata.
# - [ ] Gli hook sono stati **provati** nei casi
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
# Lo stesso vale per i blocchi `session-start` di `status.md`: una voce chiusa esce dagli
# aperti nel commit che la chiude, e il controllo 6 del lint dice quanto pesa l'iniezione.
# Se supera il tetto, si accorcia il documento, non si alza il tetto.
#
# Infine, la regola che tiene in piedi il livello che esegue: **il lint va fatto girare prima
# di dichiarare concluso qualcosa**, e quando trova qualcosa si corregge il documento, non si
# allarga l'eccezione.
#
# ---- AGENT-CONTEXT-FILE: docs/context/config.toml ----
# # Configurazione del contesto per agenti.
# #
# # Questo file e' TUO. L'inizializzatore lo crea se manca e non lo sovrascrive mai,
# # nemmeno con --force: qui dentro c'e' la taratura fatta a mano, e aggiornare gli
# # script non deve cancellarla.
# #
# # Dove sta il codice NON si scrive qui. Il lint e gli hook lo rilevano a ogni
# # esecuzione dai file che git conosce, tracciati e nuovi non ignorati. Fuori restano
# # documenti e binari, le directory di build e dipendenze, le directory che iniziano con
# # un punto e i file dell'impianto stesso. Per vedere cosa viene rilevato:
# #     python scripts/docs_lint.py
# # Qui si correggono solo gli errori di quella rilevazione.
#
# [code]
# # Percorsi, relativi alla radice, da considerare codice anche se la rilevazione li
# # scarta: una directory che inizia con un punto, file senza estensione riconosciuta.
# include = []
# # Percorsi da NON considerare codice anche se la rilevazione li prende: codice
# # generato, copie di librerie esterne.
# exclude = []
#
# [context]
# # Il tetto, in caratteri, dei blocchi <!-- session-start --> di status.md che l'hook di
# # avvio inietta per intero a ogni sessione, /clear e compattazione. Oltre il tetto
# # inietta solo il loro indice (titoli e prima riga di ogni voce) e il lint avvisa. Quanto
# # pesa davvero in token lo misura: python scripts/context_cost.py
# max_injection_chars = 8000
#
# # Le quattro tabelle qui sotto partono VUOTE DI PROPOSITO. Si riempiono guardando i
# # falsi positivi del primo giro di lint. Ogni voce porta il motivo come valore: senza
# # motivo non si aggiunge niente, o in sei mesi queste liste sono una discarica che
# # silenzia anche i controlli veri.
#
# [lint.not_symbols]
# # Parole fra backtick nei documenti che sembrano identificatori ma sono prosa, unita' di
# # misura o nomi esterni. Il confronto ignora maiuscole e minuscole.
# # "parola" = "perche' non e' un simbolo"
#
# [lint.expected_absent]
# # Nomi citati nei documenti che NON devono esistere nel codice, per costruzione: un
# # identificatore ritirato, un modulo rimosso, il nome di un altro repository.
# # "NOME_RITIRATO" = "perche' non deve esistere"
#
# [lint.external_symbols]
# # Simboli che esistono, ma in una libreria o in un framework, non in questo albero.
# # Una chiave che finisce con "/" vale come prefisso di percorso.
# # "API_DELLA_LIBRERIA" = "di quale libreria, e perche' e' citata"
#
# [lint.received_docs]
# # Documenti ricevuti da terzi e conservati verbatim: il lint non ne controlla i link,
# # che puntano nel workspace di chi li ha scritti. Si indicano per nome di file.
# # "nome-file.md" = "da chi, e perche' e' conservato cosi'"
#
# ---- AGENT-CONTEXT-FILE: scripts/agent_hooks.py ----
# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-
# """
# agent_hooks — il livello che esegue invece di chiedere, uguale per ogni agente.
#
#     python scripts/agent_hooks.py session-start --agent <nome>
#     python scripts/agent_hooks.py stop          --agent <nome>
#
# Lo invoca l'agente stesso, attraverso il suo meccanismo di hook. L'aggancio e' l'unica
# parte specifica dell'agente (e della macchina), e lo scrive agent_context_init.py nella
# configurazione LOCALE di ciascun agente. Qui non c'e' niente di specifico di un agente:
# il protocollo usato e' quello che gli agenti supportati hanno in comune.
#
#   session-start  stampa su stdout le sezioni volatili di status.md, o solo il loro indice
#                  se superano il tetto di config.toml (il testo lo costruisce
#                  context_core.build_injection). Lo stdout di questo evento entra nel
#                  contesto dell'agente, NON a schermo: l'utente non vede niente ed e'
#                  normale.
#   stop           a fine turno, se il codice e' cambiato e status.md no, stampa su stdout
#                  {"decision": "block", "reason": ...} ed esce 0: l'agente non chiude e
#                  riceve il motivo. Blocca UNA SOLA VOLTA per sessione.
#
# Perche' JSON e non l'uscita 2: provato il 2026-09-17 su Windows, Codex 0.154.0 tratta
# l'uscita 2 di Stop come un errore e chiude comunque; la decisione JSON con uscita 0
# blocca sia su Codex 0.154.0 sia su Claude Code 2.1.274.
#
# FAIL-OPEN: qualunque errore interno esce 0 senza stampare. Un hook rotto deve degradare
# ad "assente", mai a "bloccante". Per questo esiste la traccia .git/agent-hooks.log: e'
# l'unico modo di sapere se gli hook girano.
# """
#
# import io
# import json
# import re
# import sys
# from datetime import datetime
# from pathlib import Path
#
# # Importare context_core non deve lasciare __pycache__ nel repository.
# sys.dont_write_bytecode = True
#
# AGENT = "?"
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
# def load_core():
#     try:
#         sys.path.insert(0, str(Path(__file__).resolve().parent))
#         import context_core
#         return context_core
#     except Exception:
#         return None
#
#
# core = load_core()
#
#
# def log(event: str, outcome: str) -> None:
#     """
#     Una riga per esecuzione, anche per gli esiti silenziosi: un hook fail-open rotto e
#     un hook assente sono altrimenti indistinguibili.
#     """
#     try:
#         if core is None:
#             return
#         root = core.repo_root()
#         g = core.git_dir(root) if root else None
#         if g is None:
#             return
#         line = (f"{datetime.now():%Y-%m-%d %H:%M:%S}  {AGENT:<7} {event:<13} "
#                 f"{outcome}\n")
#         with open(g / "agent-hooks.log", "a", encoding="utf-8") as fh:
#             fh.write(line)
#     except Exception:
#         pass
#
#
# def read_input() -> dict:
#     """Il JSON che l'agente passa su stdin. Malformato o assente vale come vuoto."""
#     try:
#         raw = sys.stdin.read()
#         data = json.loads(raw) if raw.strip() else {}
#         return data if isinstance(data, dict) else {}
#     except Exception:
#         return {}
#
#
# # ------------------------------------------------------------------------ session-start
#
# def session_start(data: dict) -> int:
#     if core is None:
#         log("SessionStart", "scripts/context_core.py non trovato: niente da iniettare")
#         return 0
#     root = core.repo_root()
#     if root is None:
#         return 0
#
#     inj = core.build_injection(root)
#     if inj is None:
#         log("SessionStart", f"nessun {core.STATUS_FILE}: niente da iniettare")
#         return 0
#
#     text = inj["text"]
#     print(text)
#     # Il formato di questa riga lo legge scripts/context_cost.py: "iniettati N caratteri".
#     ridotto = (f", RIDOTTO a indice: blocchi={inj['blocks_chars']} > tetto={inj['budget']}"
#                if inj["reduced"] else "")
#     log("SessionStart", f"iniettati {len(text)} caratteri "
#                         f"(fonte={data.get('source', '?')}, "
#                         f"assunto={inj['levels'].get('assunto', 0)}{ridotto})")
#     return 0
#
#
# # -------------------------------------------------------------------------------- stop
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
# def stop(data: dict) -> int:
#     if core is None:
#         log("Stop", "scripts/context_core.py non trovato: nessun controllo")
#         return 0
#     # L'agente ha gia' continuato una volta per un hook di fine turno: non si insiste.
#     if data.get("stop_hook_active") is True:
#         log("Stop", "ok (turno gia' prolungato da un hook)")
#         return 0
#     root = core.repo_root()
#     if root is None:
#         return 0
#     g = core.git_dir(root)
#     if g is None:
#         return 0
#
#     STATUS_FILE = core.STATUS_FILE
#     sid = str(data.get("session_id") or "ignota")
#     safe = re.sub(r"[^A-Za-z0-9_-]", "", sid) or "ignota"
#     flag = g / f"docs-status-nag-{safe}.flag"
#     if flag.exists():
#         log("Stop", "ok (gia' segnalato in questa sessione)")
#         return 0
#
#     if core.dirty(root, [STATUS_FILE]):
#         log("Stop", f"ok ({STATUS_FILE} gia' toccato)")
#         return 0
#
#     cfg, _ = core.load_config(root)
#     specs, labels = core.code_scope(root, cfg)
#     if not specs:
#         log("Stop", "ok (nessun codice nel repository, per ora)")
#         return 0
#     where = ", ".join(labels)
#
#     reasons = []
#     changed = core.dirty(root, specs)
#     if changed:
#         files = ", ".join(re.sub(r"^\s*\S+\s+", "", l) for l in changed.splitlines())
#         reasons.append(f"modifiche non committate: {files}")
#
#     status_path = root / STATUS_FILE
#     if status_path.is_file():
#         sha = core.read_marker(status_path.read_text(encoding="utf-8", errors="replace"))
#         if sha:
#             ok, since = core.commits_since(root, sha, specs)
#             if ok and since:
#                 reasons.append(f"{len(since)} commit sul codice ({where}) dopo {sha}, "
#                                f"il punto a cui {STATUS_FILE} dichiara di essere "
#                                f"riconciliato")
#
#     if not reasons:
#         log("Stop", "ok (codice invariato dal marcatore)")
#         return 0
#
#     flag.write_text("", encoding="utf-8")
#     log("Stop", "BLOCCATO: " + "; ".join(reasons))
#     print(json.dumps({"decision": "block",
#                       "reason": MESSAGE.format(status=STATUS_FILE,
#                                                reasons="\n  - ".join(reasons))},
#                      ensure_ascii=False))
#     return 0
#
#
# # -------------------------------------------------------------------------------- main
#
# EVENTS = {"session-start": ("SessionStart", session_start), "stop": ("Stop", stop)}
#
#
# def main(argv) -> int:
#     global AGENT
#     args = list(argv)
#     if "--agent" in args:
#         i = args.index("--agent")
#         AGENT = args[i + 1] if i + 1 < len(args) else "?"
#         del args[i:i + 2]
#     if not args or args[0] not in EVENTS:
#         log("?", f"evento sconosciuto: {args[:1]}")
#         return 0
#     name, fn = EVENTS[args[0]]
#     try:
#         return fn(read_input())
#     except Exception as exc:                      # fail-open, sempre
#         log(name, f"ERRORE INTERNO {type(exc).__name__} (fail-open, nessun blocco)")
#         return 0
#
#
# if __name__ == "__main__":
#     setup_stdout()
#     try:
#         code = main(sys.argv[1:])
#     except Exception:
#         code = 0
#     sys.exit(0 if code is None else code)
#
# ---- AGENT-CONTEXT-FILE: scripts/context_core.py ----
# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-
# """
# context_core — la parte comune al lint dei documenti e agli hook degli agenti.
#
# Risponde a tre domande, sempre nello stesso modo per chiunque le faccia:
#
#   - dove sta il codice di questo repository;
#   - cosa dice la configurazione scritta a mano (docs/context/config.toml);
#   - a che commit status.md dichiara di essere riconciliato, e cosa e' cambiato da allora.
#
# Dove sta il codice NON e' scritto da nessuna parte: si rileva a ogni esecuzione dai file
# che git conosce, tracciati e nuovi non ignorati. Una costante scritta una volta sola
# diventa falsa appena il progetto cresce o si riorganizza, e nessuno se ne accorge: un
# repository nato vuoto restava sorvegliato su una cartella `src` che non esisteva.
#
# Nessuna dipendenza fuori dalla libreria standard. Non stampa niente e non esce: decide
# chi lo importa cosa fare degli errori.
# """
#
# import re
# import subprocess
# import tomllib
# from pathlib import Path
#
# CONTEXT_DIR = "docs/context"
# STATUS_FILE = "docs/context/status.md"
# CONFIG_FILE = "docs/context/config.toml"
#
# # I livelli di evidenza, nella forma esatta in cui compaiono nei documenti.
# EVIDENCE_LEVELS = ("verificato", "dedotto", "assunto")
#
# # I file che questo impianto installa. Stanno nell'albero ma non sono codice del
# # progetto: modificarli non rende vecchio lo stato del lavoro, e contengono di proposito
# # i nomi che il lint cerca.
# MANAGED_FILES = {"scripts/docs_lint.py", "scripts/context_core.py", "scripts/agent_hooks.py",
#                  "scripts/context_cost.py", "scripts/agent_context_version.json"}
# # L'inizializzatore si copia dove capita, quindi si riconosce per nome.
# MANAGED_NAMES = {"agent_context_init.py"}
#
# # Estensioni che non sono codice: documenti, media, archivi, binari, dati.
# NON_SOURCE_SUFFIXES = {
#     ".md", ".rst", ".adoc", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
#     ".webp", ".bmp", ".tiff", ".mp3", ".mp4", ".wav", ".zip", ".gz", ".tar", ".7z",
#     ".bin", ".hex", ".elf", ".exe", ".dll", ".so", ".dylib", ".lock", ".log", ".csv",
#     ".pem", ".der", ".crt", ".key",
#     ".ttf", ".otf", ".woff", ".woff2", ".eot", ".wasm", ".jar", ".class",
#     ".o", ".a", ".obj", ".lib", ".pyc", ".pyo", ".db", ".sqlite", ".sqlite3",
#     # Testo libero: note, versioni, output salvati. I .txt che sono codice si
#     # riconoscono per nome, qui sotto.
#     ".txt",
# }
#
# # File che sono codice pur senza un'estensione riconoscibile come tale.
# SOURCE_NAMES = {
#     "CMakeLists.txt", "Makefile", "makefile", "GNUmakefile", "Dockerfile",
#     "Containerfile", "Kconfig", "Jenkinsfile", "Rakefile", "Gemfile", "Vagrantfile",
#     "Procfile", "requirements.txt", "constraints.txt",
# }
#
# # Directory che non contengono codice del progetto, per quanto piene di file.
# NON_SOURCE_DIRS = {
#     "docs", "doc", "build", "dist", "out", "target", "node_modules", "vendor",
#     "third_party", "external", "__pycache__", "venv", "site-packages",
# }
#
# MARKER_RE = re.compile(r"<!--\s*context-verified-at:\s*([0-9a-f]{7,40})\s*-->")
# # I marcatori devono stare DA SOLI sulla loro riga: senza le ancore di riga, la regex
# # cattura anche il paragrafo che spiega i marcatori citandoli in linea.
# BLOCK_RE = re.compile(
#     r"^[ \t]*<!--\s*session-start:\s*begin\s*-->[ \t]*$"
#     r"(.*?)"
#     r"^[ \t]*<!--\s*session-start:\s*end\s*-->[ \t]*$",
#     re.S | re.M)
#
#
# # ------------------------------------------------------------------------------ git
#
# def run_git(root, *args):
#     """(riuscito, stdout). Un git assente o rotto vale come comando fallito."""
#     try:
#         r = subprocess.run(["git", *args], capture_output=True, text=True,
#                            encoding="utf-8", errors="replace",
#                            cwd=str(root) if root else None)
#         return r.returncode == 0, r.stdout
#     except OSError:
#         return False, ""
#
#
# def repo_root(start=None):
#     ok, out = run_git(start, "rev-parse", "--show-toplevel")
#     return Path(out.strip()) if ok and out.strip() else None
#
#
# def git_dir(root):
#     ok, out = run_git(root, "rev-parse", "--git-dir")
#     if not ok or not out.strip():
#         return None
#     p = Path(out.strip())
#     return p if p.is_absolute() else (root / p)
#
#
# def head_sha(root):
#     """Lo sha corto di HEAD, o None se il repository non ha ancora un commit."""
#     ok, out = run_git(root, "rev-parse", "--short", "HEAD")
#     sha = out.strip()
#     return sha if ok and re.fullmatch(r"[0-9a-f]{7,40}", sha) else None
#
#
# # ---------------------------------------------------------------------- configurazione
#
# def load_config(root):
#     """
#     (configurazione, errore). Un file assente e' normale e vale come vuoto. Un file
#     malformato NON vale come vuoto in silenzio: l'errore torna a chi chiama, perche'
#     liste di eccezioni perse di colpo fanno sembrare rotti i documenti.
#     """
#     p = Path(root) / CONFIG_FILE
#     if not p.is_file():
#         return {}, None
#     try:
#         with open(p, "rb") as fh:
#             return tomllib.load(fh), None
#     except (OSError, tomllib.TOMLDecodeError) as exc:
#         return {}, f"{CONFIG_FILE} non e' TOML valido: {exc}"
#
#
# def config_table(cfg, *keys) -> dict:
#     """Una tabella annidata della configurazione, o {} se manca o ha la forma sbagliata."""
#     cur = cfg
#     for k in keys:
#         cur = cur.get(k) if isinstance(cur, dict) else None
#     return cur if isinstance(cur, dict) else {}
#
#
# def _prefixes(cfg, key):
#     vals = config_table(cfg, "code").get(key, [])
#     if not isinstance(vals, list):
#         return []
#     return [str(v).strip().replace("\\", "/").strip("/") for v in vals if str(v).strip()]
#
#
# def _under(rel, prefixes):
#     return any(rel == p or rel.startswith(p + "/") for p in prefixes)
#
#
# # ---------------------------------------------------------------------- dove sta il codice
#
# def known_files(root):
#     """
#     I file che git conosce: tracciati, e nuovi purche' non ignorati. I nuovi contano,
#     perche' una cartella appena creata e' gia' codice prima del primo `git add`.
#     """
#     ok, out = run_git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
#     if not ok:
#         return []
#     return sorted({f for f in out.split("\0") if f})
#
#
# def _is_managed(rel):
#     return rel in MANAGED_FILES or rel.rsplit("/", 1)[-1] in MANAGED_NAMES
#
#
# def _has_source_suffix(rel):
#     name = rel.rsplit("/", 1)[-1]
#     if name in SOURCE_NAMES or name.startswith("Kconfig."):
#         return True
#     suf = Path(name).suffix.lower()
#     return bool(suf) and suf not in NON_SOURCE_SUFFIXES
#
#
# def code_files(root, cfg):
#     """
#     Il codice del progetto: cio' che, se cambia, puo' rendere falsi i documenti.
#
#     Fuori: documenti e binari, directory di build e dipendenze, directory che iniziano
#     con un punto (configurazione di strumenti: .github, .vscode, .claude...), e i file
#     di questo impianto. `[code] include` e `[code] exclude` correggono la regola.
#     """
#     include, exclude = _prefixes(cfg, "include"), _prefixes(cfg, "exclude")
#     out = []
#     for rel in known_files(root):
#         if _under(rel, exclude):
#             continue
#         if _under(rel, include):
#             out.append(rel)
#             continue
#         dirs = rel.split("/")[:-1]
#         if any(d in NON_SOURCE_DIRS or d.startswith(".") for d in dirs):
#             continue
#         if _is_managed(rel) or not _has_source_suffix(rel):
#             continue
#         out.append(rel)
#     return out
#
#
# def tree_files(root, cfg):
#     """
#     Dove un simbolo citato nei documenti puo' legittimamente vivere. E' piu' largo del
#     codice: comprende le directory di configurazione degli strumenti e i file di questo
#     impianto, che i documenti citano anche loro.
#     """
#     exclude = _prefixes(cfg, "exclude")
#     out = []
#     for rel in known_files(root):
#         if _under(rel, exclude):
#             continue
#         dirs = rel.split("/")[:-1]
#         if any(d in NON_SOURCE_DIRS or d == ".git" for d in dirs):
#             continue
#         if _has_source_suffix(rel):
#             out.append(rel)
#     return out
#
#
# def code_scope(root, cfg):
#     """
#     (pathspec per git, etichette leggibili). Le pathspec servono a `git log` e
#     `git status` per chiedere "e' cambiato il codice?" senza elencare mille file.
#
#     Lista vuota = nessun codice ancora. Chi chiama deve saltare il controllo: una
#     pathspec vuota, per git, vuol dire TUTTO il repository.
#     """
#     include = _prefixes(cfg, "include")
#     tops = []
#     for rel in code_files(root, cfg):
#         # Un percorso incluso a mano si sorveglia per quello che e', non allargato alla
#         # sua directory di primo livello: `.github/workflows` non e' tutto `.github`.
#         top = next((p for p in include if _under(rel, [p])), None)
#         if top is None:
#             top = rel.split("/", 1)[0] if "/" in rel else rel
#         if top not in tops:
#             tops.append(top)
#     if not tops:
#         return [], []
#     specs = list(tops)
#     specs += [f":(exclude){m}" for m in sorted(MANAGED_FILES)]
#     specs += [f":(exclude,glob)**/{n}" for n in sorted(MANAGED_NAMES)]
#     specs += [f":(exclude){e}" for e in _prefixes(cfg, "exclude")]
#     specs += [f":(exclude,glob)**/*{s}" for s in sorted(NON_SOURCE_SUFFIXES)]
#     labels = [t + "/" if (Path(root) / t).is_dir() else t for t in tops]
#     return specs, labels
#
#
# def commits_since(root, sha, specs):
#     """(marcatore valido?, righe di log dei commit che hanno toccato il codice)."""
#     if not specs:
#         return True, []
#     ok, out = run_git(root, "log", "--oneline", f"{sha}..HEAD", "--", *specs)
#     return ok, [l for l in out.splitlines() if l.strip()]
#
#
# def dirty(root, specs) -> str:
#     """Modifiche non committate sotto le pathspec date (stringa vuota = pulito)."""
#     if not specs:
#         return ""
#     return run_git(root, "status", "--porcelain", "--", *specs)[1].strip()
#
#
# # ---------------------------------------------------------------------- documento di stato
#
# def read_marker(status_text):
#     m = MARKER_RE.search(status_text)
#     return m.group(1) if m else None
#
#
# def extract_marked(status_text):
#     """
#     Le sezioni da iniettare le dichiara il documento, con
#     <!-- session-start: begin --> ... <!-- session-start: end -->.
#     Cosi' chi le inietta non sa niente della numerazione delle sezioni.
#     """
#     return [m.group(1).strip() for m in BLOCK_RE.finditer(status_text) if m.group(1).strip()]
#
#
# def count_levels(root) -> dict:
#     counts = {lvl: 0 for lvl in EVIDENCE_LEVELS}
#     ctx = Path(root) / CONTEXT_DIR
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
# # ---------------------------------------------------------------------- l'iniezione all'avvio
#
# # Il tetto, in caratteri, dei blocchi session-start che l'hook inietta per intero. E' in
# # caratteri perche' l'hook non ha un tokenizer. Quanti token valgano davvero lo misura
# # scripts/context_cost.py; come ordine di grandezza, sui documenti in italiano di questo
# # impianto un token ha fatto da 1,9 a 2,3 caratteri (stima dalle sessioni, 2026-09-26).
# DEFAULT_INJECTION_BUDGET = 8000
# # Nell'indice, la prima riga di ogni voce si taglia qui: basta a riconoscerla.
# INDEX_LINE_MAX = 160
#
#
# def injection_budget(cfg) -> int:
#     """Il tetto da [context] max_injection_chars in config.toml, o quello di default."""
#     val = config_table(cfg, "context").get("max_injection_chars")
#     if isinstance(val, int) and not isinstance(val, bool) and val > 0:
#         return val
#     return DEFAULT_INJECTION_BUDGET
#
#
# def index_of(blocks) -> str:
#     """
#     L'indice dei blocchi: i titoli e la prima riga di ogni voce di primo livello. E' cio'
#     che si inietta quando i blocchi superano il tetto: l'agente vede cosa c'e' e dove, e
#     legge il dettaglio solo di cio' che gli serve.
#     """
#     out = []
#     for block in blocks:
#         for line in block.splitlines():
#             if re.match(r"^#{1,6}\s", line):
#                 out.append(line.rstrip())
#             elif re.match(r"^(?:[-*]|\d+\.)\s", line):
#                 text = line.rstrip()
#                 if len(text) > INDEX_LINE_MAX:
#                     text = text[:INDEX_LINE_MAX - 1].rstrip() + "…"
#                 out.append(text)
#         out.append("")
#     return "\n".join(out).strip()
#
#
# def build_injection(root, cfg=None):
#     """
#     Il testo che l'hook di avvio mette nel contesto dell'agente. Si costruisce qui, e non
#     nell'hook, perche' hook, lint e misura dei consumi ne vedano la stessa identica
#     versione. None se non c'e' status.md.
#
#     Torna un dizionario: text (il testo esatto), blocks_chars (quanto fanno i blocchi
#     session-start per intero), budget, reduced (True se i blocchi superano il tetto e al
#     loro posto va l'indice), levels (il cruscotto dell'evidenza).
#     """
#     root = Path(root)
#     status_path = root / STATUS_FILE
#     if not status_path.is_file():
#         return None
#     if cfg is None:
#         cfg, _ = load_config(root)
#     status = status_path.read_text(encoding="utf-8", errors="replace")
#     specs, labels = code_scope(root, cfg)
#     where = ", ".join(labels)
#     budget = injection_budget(cfg)
#
#     out = [
#         "=== Stato del progetto (iniettato da scripts/agent_hooks.py) ===",
#         f"Fonte: {STATUS_FILE}. Se agisci su qualcosa di qui sotto, leggi in quel file la "
#         f"sezione che ti serve, non il file intero.",
#         "",
#     ]
#
#     # --- Le sezioni che il documento stesso dichiara volatili ---
#     blocks = extract_marked(status)
#     blocks_chars = sum(len(b) for b in blocks)
#     reduced = blocks_chars > budget
#     if not blocks:
#         out.append(f"({STATUS_FILE} non ha blocchi <!-- session-start: begin/end -->: "
#                    f"nessuna sezione dichiarata volatile.)")
#     elif reduced:
#         out.append(f"ATTENZIONE: i blocchi session-start di {STATUS_FILE} fanno "
#                    f"{blocks_chars} caratteri, oltre il tetto di {budget}. Qui sotto c'e' "
#                    f"solo il loro indice: leggi nel file le voci che ti servono. Se lavori "
#                    f"su {STATUS_FILE}, riporta i blocchi sotto il tetto (vedi "
#                    f"docs/agent_docs_guide.md).")
#         out.append("")
#         out.append(index_of(blocks))
#     else:
#         out.append("\n\n".join(blocks))
#     out.append("")
#
#     # --- Cruscotto dei livelli di evidenza ---
#     levels = count_levels(root)
#     out.append("Evidenza nei documenti di contesto: " +
#                "  ".join(f"{k}={v}" for k, v in levels.items()))
#
#     # --- Freschezza: il documento e' invecchiato rispetto al codice? ---
#     sha = read_marker(status)
#     if sha:
#         ok, since = commits_since(root, sha, specs)
#         if ok and since:
#             out.append(f"ATTENZIONE: {len(since)} commit hanno toccato il codice ({where}) "
#                        f"dopo {sha}, il punto a cui {STATUS_FILE} dichiara di essere "
#                        f"riconciliato. Potrebbe dire cose non piu' vere.")
#     elif head_sha(root) is not None:
#         out.append(f"ATTENZIONE: {STATUS_FILE} non ha il marcatore context-verified-at: "
#                    f"la sua freschezza non e' misurabile.")
#
#     # --- Lavoro non registrato rimasto da una sessione precedente ---
#     if dirty(root, specs) and not dirty(root, [STATUS_FILE]):
#         out.append(f"ATTENZIONE: ci sono modifiche non committate al codice ({where}) e "
#                    f"{STATUS_FILE} e' intatto. Probabile lavoro di una sessione "
#                    f"precedente mai registrato: valuta se va annotato.")
#
#     out += ["", "Verifica che i documenti dicano ancora il vero: "
#                 "python scripts/docs_lint.py",
#             "=== fine stato del progetto ==="]
#     return {"text": "\n".join(out), "blocks_chars": blocks_chars, "budget": budget,
#             "reduced": reduced, "levels": levels}
#
# ---- AGENT-CONTEXT-FILE: scripts/context_cost.py ----
# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-
# """
# context_cost — quanto pesa il contesto di questo repository, misurato.
#
#     python scripts/context_cost.py                resoconto; non chiama nessun modello
#     python scripts/context_cost.py misura         misura ESATTA dei token che questo
#                                                   impianto aggiunge a ogni sessione
#     python scripts/context_cost.py --giorni 30    solo le sessioni degli ultimi 30 giorni
#     python scripts/context_cost.py --anche <dir>  conta anche le sessioni aperte in <dir>
#                                                   (il vecchio percorso di un repo spostato)
#
# Ogni numero dice da dove viene:
#
#   [misurato]  letto da cio' che l'agente registra: l'usage che l'API restituisce a ogni
#               chiamata (trascrizioni di Claude Code, token_count di Codex), oppure il
#               risultato di `misura`. E' il dato, non un calcolo.
#   [stimato]   calcolato: caratteri divisi per un rapporto caratteri/token, o token
#               moltiplicati per un prezzo di listino. Il rapporto viene dall'ultima
#               `misura` di questo repository, se c'e'; altrimenti e' un valore di
#               partenza, dichiarato.
#
# COME MISURA `misura`. Lancia Claude Code headless tre volte in una copia usa e getta:
# repository vuoto, poi con AGENTS.md e CLAUDE.md, poi anche con l'hook di avvio che
# inietta il testo che inietterebbe qui. Il totale dei token di input di ogni esecuzione
# lo riporta Claude Code; la differenza fra due esecuzioni e' il peso esatto dello strato
# aggiunto, con il tokenizer e l'harness veri. Tutto il resto (prompt di sistema, strumenti,
# istruzioni e plugin dell'utente) e' uguale nelle tre e si elide: la base viene misurata
# due volte e, se non torna identica, la misura si ferma invece di dare un numero sporco.
# Precisione: pochi token. Due misure dello stesso repository, il 2026-09-28, hanno dato
# 1.302 e 1.300 token per le stesse istruzioni: il percorso della copia usa e getta, che
# cambia a ogni misura, compare nell'intestazione che l'agente mette ai file. La misura
# comprende quelle intestazioni, perche' anche loro sono contesto pagato.
# Costa quattro chiamate brevi al modello (circa $0,40 con Opus 5.5, quasi tutto la prima
# scrittura in cache della base), e il costo esatto lo stampa alla fine.
# Il risultato va in .git/context-cost.json, legato al contenuto misurato: se i file
# cambiano, il resoconto lo dice e torna a stimare.
#
# PREZZI. I costi sono l'equivalente a listino API, anche per chi usa un abbonamento (in
# quel caso sono quota, non fattura). Il listino e' in PRICES qui sotto, con la sua fonte;
# un modello che non c'e' non riceve un costo inventato. Per Codex lo strumento riporta i
# token, non i costi.
# """
#
# import argparse
# import hashlib
# import io
# import json
# import os
# import re
# import shutil
# import subprocess
# import sys
# import tempfile
# from collections import defaultdict
# from datetime import datetime, timedelta, timezone
# from pathlib import Path
#
# if hasattr(sys.stdout, "buffer"):
#     sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
#
# sys.dont_write_bytecode = True
# sys.path.insert(0, str(Path(__file__).resolve().parent))
# import context_core as core  # noqa: E402
#
# # ------------------------------------------------------------------------- listino
#
# # $ per milione di token: (input, output, lettura dalla cache). La scrittura in cache
# # costa 1,25x l'input con durata 5 minuti e 2x con durata 1 ora; la lettura 0,1x l'input,
# # salvo dove il listino dice altro (Opus 5.5: $0,20; Fable 5.1: $0,25). Fonte: tabella
# # dei modelli Anthropic aggiornata al 2026-06-24, con Claude Opus 5.5 al lancio.
# PRICES = {
#     "claude-opus-5-5": (4.00, 20.00, 0.20),
#     "claude-opus-5": (5.00, 25.00, 0.50),
#     "claude-fable-5-1": (10.00, 50.00, 0.25),
#     "claude-fable-5": (10.00, 50.00, 1.00),
#     "claude-opus-4-8": (5.00, 25.00, 0.50),
#     "claude-opus-4-7": (5.00, 25.00, 0.50),
#     "claude-opus-4-6": (5.00, 25.00, 0.50),
#     "claude-sonnet-5": (2.00, 10.00, 0.20),
#     "claude-sonnet-4-6": (3.00, 15.00, 0.30),
#     "claude-haiku-4-5": (1.00, 5.00, 0.10),
# }
# WRITE_5M, WRITE_1H = 1.25, 2.0
# # I modelli per cui il costo calcolato qui e' stato confrontato con quello che Claude Code
# # calcola da se' (total_cost_usd di `claude -p`) su una sessione con scrittura e lettura
# # in cache, e coincideva alla settima cifra decimale: 2026-09-26 Opus 5.5, 2026-09-28 gli
# # altri tre. Per gli altri il resoconto dice che il prezzo non e' verificato.
# VERIFIED_PRICES = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"}
#
# # Rapporto caratteri/token usato solo finche' non c'e' una `misura` di questo repository.
# # Valore di partenza: nelle sessioni di tre repository di questo impianto (documenti in
# # italiano, markdown) e' stato 1,9-2,3 (stima dalle trascrizioni, 2026-09-26).
# DEFAULT_CHARS_PER_TOKEN = 2.1
#
# MEASURE_FILE = "context-cost.json"      # in .git/: e' un fatto della macchina, non del repo
# PROMPT = "Rispondi solo: OK"
#
#
# # ----------------------------------------------------------------------- utilita'
#
# def norm(p) -> str:
#     return os.path.normcase(os.path.normpath(str(p))).rstrip("\\/")
#
#
# def inside(path, roots) -> bool:
#     p = norm(path)
#     return any(p == r or p.startswith(r + os.sep) for r in roots)
#
#
# def parse_ts(s):
#     try:
#         return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
#     except (TypeError, ValueError):
#         return None
#
#
# def price_of(model):
#     if not model:
#         return None
#     if model in PRICES:
#         return PRICES[model]
#     # Un id con data in coda (claude-x-20260101) vale come il suo nome base.
#     base = re.sub(r"-\d{8}$", "", model)
#     return PRICES.get(base)
#
#
# def usd(x):
#     return "n/d" if x is None else f"${x:,.2f}"
#
#
# def num(x):
#     return f"{x:,}".replace(",", ".")
#
#
# def sha(text: str) -> str:
#     return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
#
#
# def iter_jsonl(path):
#     try:
#         with open(path, encoding="utf-8", errors="replace") as fh:
#             for line in fh:
#                 line = line.strip()
#                 if not line:
#                     continue
#                 try:
#                     d = json.loads(line)
#                 except ValueError:
#                     continue
#                 if isinstance(d, dict):
#                     yield d
#     except OSError:
#         return
#
#
# # ------------------------------------------------------------- il contesto fisso, ora
#
# def instruction_files(root: Path):
#     """
#     I file di istruzioni che l'agente carica da solo: CLAUDE.md, AGENTS.md e cio' che
#     importano con righe `@percorso`, seguiti ricorsivamente. Solo quelli dentro il repo.
#     """
#     seen, order = set(), []
#
#     def visit(p: Path):
#         try:
#             rp = p.resolve()
#         except OSError:
#             return
#         if rp in seen or not rp.is_file() or not inside(rp, [norm(root.resolve())]):
#             return
#         seen.add(rp)
#         order.append(rp)
#         for line in rp.read_text(encoding="utf-8", errors="replace").splitlines():
#             m = re.match(r"^\s*@(\S+)\s*$", line)
#             if m:
#                 visit(rp.parent / m.group(1))
#
#     for name in ("CLAUDE.md", "AGENTS.md"):
#         visit(root / name)
#     return order
#
#
# def current_fixed(root: Path):
#     files = instruction_files(root)
#     instr_text = "".join(p.read_text(encoding="utf-8", errors="replace") for p in files)
#     inj = core.build_injection(root)
#     return {
#         "instruction_files": [p.relative_to(root.resolve()).as_posix() for p in files],
#         "instructions_chars": len(instr_text),
#         "instructions_sha": sha(instr_text),
#         "injection_chars": len(inj["text"]) if inj else 0,
#         "injection_sha": sha(inj["text"]) if inj else sha(""),
#         "injection_reduced": bool(inj and inj["reduced"]),
#         "injection_text": inj["text"] if inj else "",
#     }
#
#
# def load_measure(root: Path):
#     g = core.git_dir(root)
#     p = g / MEASURE_FILE if g else None
#     if not p or not p.is_file():
#         return None
#     try:
#         return json.loads(p.read_text(encoding="utf-8"))
#     except (OSError, ValueError):
#         return None
#
#
# def chars_per_token(measure):
#     """Il rapporto dalla misura di questo repository, o quello di partenza."""
#     if measure:
#         c = measure.get("injection_chars", 0) + measure.get("instructions_chars", 0)
#         t = measure.get("injection_tokens", 0) + measure.get("instructions_tokens", 0)
#         if c > 0 and t > 0:
#             return c / t, "dall'ultima misura di questo repository"
#     return DEFAULT_CHARS_PER_TOKEN, "valore di partenza, nessuna misura ancora"
#
#
# # --------------------------------------------------------------- Claude Code: sessioni
#
# def claude_home() -> Path:
#     return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
#
#
# def claude_folder(path) -> str:
#     """Il nome della cartella in cui Claude Code tiene le trascrizioni di un percorso."""
#     return re.sub(r"[^A-Za-z0-9]", "-", str(path))
#
#
# def claude_files_for(roots, root_paths=(), other_cwds=None):
#     """
#     Le trascrizioni di questo repository: quelle la cui cartella di lavoro sta dentro uno
#     dei percorsi dati, e quelle nella cartella che Claude Code intesta al percorso del
#     repository. La seconda regola serve ai repository spostati: le sessioni vecchie
#     registrano il percorso di prima, ma stanno nella cartella di adesso (osservato il
#     2026-09-28 su progetto, spostato da C:\\vecchia a C:\\progetti\\vecchia).
#     other_cwds, se dato, raccoglie le cartelle di lavoro diverse da quella di adesso.
#     """
#     base = claude_home() / "projects"
#     if not base.is_dir():
#         return []
#     folders = {claude_folder(p).lower() for p in root_paths}
#     picked = []
#     for f in base.glob("*/*.jsonl"):
#         cwd = None
#         for i, d in enumerate(iter_jsonl(f)):
#             if d.get("cwd"):
#                 cwd = d["cwd"]
#                 break
#             if i > 200:
#                 break
#         by_cwd = bool(cwd and inside(cwd, roots))
#         if by_cwd or f.parent.name.lower() in folders:
#             if cwd and not by_cwd and other_cwds is not None:
#                 other_cwds.add(cwd)
#             picked.append(f)
#             # I sottoagenti stanno in <sessione>/subagents/, stessa cartella di lavoro.
#             picked += sorted((f.parent / f.stem / "subagents").glob("*.jsonl"))
#     return picked
#
#
# # Una lettura e' uno strumento di lettura, o un comando di shell che mostra un file. Un
# # `git diff` o un `grep` sul repo che nomina un documento non lo e'.
# READ_TOOLS = {"Read", "Grep", "NotebookRead"}
# SHOW_RE = re.compile(r"^\s*(?:rtk\s+)?(?:cat|head|tail|sed\s+-n|less|more|type|"
#                      r"Get-Content|gc|bat|read)\b", re.I)
#
#
# def is_read(name, inp):
#     """Il testo in cui cercare il documento letto, o None se non e' una lettura."""
#     if name in READ_TOOLS:
#         return " ".join(str(v) for v in inp.values())
#     if name in ("Bash", "PowerShell"):
#         cmd = str(inp.get("command", ""))
#         parts = re.split(r"&&|;|\|\||\n", cmd)
#         return " ".join(p for p in parts if SHOW_RE.match(p)) or None
#     return None
#
#
# CTX_RE = re.compile(r"(docs[/\\]context[/\\][^\s\"'`]+\.md|AGENTS\.md|CLAUDE\.md)")
#
#
# def claude_sessions(files, since):
#     """
#     Una voce per sessione. Le chiamate si contano per id del messaggio, su TUTTI i file
#     insieme: una sessione ripresa puo' ricopiare la storia in un file nuovo, e un
#     messaggio in streaming compare su piu' righe. Per ogni id vale l'ultimo usage.
#     """
#     calls = {}                      # id -> dati della chiamata
#     sessions = defaultdict(lambda: {"compactions": 0, "files": set(), "reads": []})
#     tool_uses, seen_results = {}, set()
#     for f in files:
#         for d in iter_jsonl(f):
#             sid = d.get("sessionId") or f.stem
#             s = sessions[sid]
#             s["files"].add(f.name)
#             t = d.get("type")
#             if t == "system" and d.get("subtype") == "compact_boundary":
#                 s["compactions"] += 1
#             if t == "assistant":
#                 m = d.get("message") or {}
#                 u = m.get("usage")
#                 mid = m.get("id") or d.get("requestId")
#                 if not mid or not isinstance(u, dict) or m.get("model") == "<synthetic>":
#                     continue
#                 ts = parse_ts(d.get("timestamp"))
#                 prev = calls.get(mid)
#                 # La sessione e l'ora sono quelle della prima comparsa; l'usage l'ultimo.
#                 calls[mid] = {"sid": prev["sid"] if prev else sid,
#                               "ts": prev["ts"] if prev else ts, "u": u,
#                               "model": m.get("model"),
#                               "side": bool(d.get("isSidechain"))}
#                 for b in m.get("content") or []:
#                     if isinstance(b, dict) and b.get("type") == "tool_use":
#                         tool_uses[b.get("id")] = (b.get("name"), b.get("input") or {})
#             elif t == "user":
#                 content = (d.get("message") or {}).get("content")
#                 for b in content if isinstance(content, list) else []:
#                     if not isinstance(b, dict) or b.get("type") != "tool_result":
#                         continue
#                     tid = b.get("tool_use_id")
#                     if tid in seen_results:
#                         continue
#                     name, inp = tool_uses.get(tid, (None, {}))
#                     target = is_read(name, inp)
#                     docs = sorted({x.replace("\\", "/")
#                                    for x in CTX_RE.findall(target)}) if target else []
#                     if docs:
#                         seen_results.add(tid)
#                         c = b.get("content")
#                         text = c if isinstance(c, str) else "".join(
#                             x.get("text", "") for x in c or [] if isinstance(x, dict))
#                         # Un comando che mostra piu' documenti: i caratteri si dividono
#                         # in parti uguali. Il totale e' esatto, la ripartizione no.
#                         for doc in docs:
#                             s["reads"].append((doc, len(text) / len(docs),
#                                                parse_ts(d.get("timestamp"))))
#
#     by_sid = defaultdict(list)
#     for c in calls.values():
#         by_sid[c["sid"]].append(c)
#     out = []
#     for sid, cs in by_sid.items():
#         cs.sort(key=lambda c: c["ts"] or datetime.min.replace(tzinfo=timezone.utc))
#         start = cs[0]["ts"]
#         if since and start and start < since:
#             continue
#         # read_rate: somma, chiamata per chiamata, del prezzo di lettura del suo modello;
#         # write_rate: prezzo di scrittura (1 ora) del modello della prima chiamata. Servono
#         # a dire quanto vale un blocco fisso di N token su QUESTE chiamate.
#         agg = {"in": 0, "w5": 0, "w1": 0, "r": 0, "out": 0, "cost": 0.0,
#                "cost_known": True, "read_rate": 0.0, "write_rate": 0.0}
#         models = set()
#         ctx_max, first_ctx = 0, None
#         for c in cs:
#             u = c["u"]
#             cw = u.get("cache_creation_input_tokens", 0) or 0
#             det = u.get("cache_creation") or {}
#             w1 = det.get("ephemeral_1h_input_tokens", 0) or 0
#             w5 = det.get("ephemeral_5m_input_tokens", cw - w1) or 0
#             if w1 + w5 != cw:          # dettaglio assente o incoerente: tutto a 5 minuti
#                 w1, w5 = 0, cw
#             i, r, o = (u.get("input_tokens", 0) or 0, u.get("cache_read_input_tokens", 0)
#                        or 0, u.get("output_tokens", 0) or 0)
#             agg["in"] += i; agg["w5"] += w5; agg["w1"] += w1; agg["r"] += r; agg["out"] += o
#             models.add(c["model"])
#             p = price_of(c["model"])
#             if p is None:
#                 agg["cost_known"] = False
#             else:
#                 pin, pout, pr = p
#                 agg["read_rate"] += pr
#                 if not agg["write_rate"]:
#                     agg["write_rate"] = pin * WRITE_1H
#                 agg["cost"] += (i * pin + w5 * pin * WRITE_5M + w1 * pin * WRITE_1H
#                                 + r * pr + o * pout) / 1e6
#             ctx = i + cw + r
#             if not c["side"]:
#                 ctx_max = max(ctx_max, ctx)
#                 if first_ctx is None:
#                     first_ctx = ctx
#         main = [c for c in cs if not c["side"]]
#         out.append({
#             "sid": sid, "start": start, "end": cs[-1]["ts"],
#             "calls": len(main), "sub_calls": len(cs) - len(main),
#             "first_ctx": first_ctx or 0, "ctx_max": ctx_max,
#             "compactions": sessions[sid]["compactions"],
#             "models": sorted(m for m in models if m), "reads": sessions[sid]["reads"],
#             **agg,
#         })
#     out.sort(key=lambda s: s["start"] or datetime.min.replace(tzinfo=timezone.utc))
#     return out
#
#
# # --------------------------------------------------------------------- Codex: sessioni
#
# def codex_home() -> Path:
#     return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
#
#
# def codex_sessions(roots, since):
#     base = codex_home() / "sessions"
#     if not base.is_dir():
#         return []
#     out = []
#     for f in base.rglob("rollout-*.jsonl"):
#         cwd, model, start = None, None, None
#         last_total, calls, ctx_max, first_ctx = None, 0, 0, None
#         for d in iter_jsonl(f):
#             p = d.get("payload") or {}
#             if d.get("type") == "session_meta":
#                 cwd = p.get("cwd")
#                 start = parse_ts(p.get("timestamp") or d.get("timestamp"))
#                 if cwd and not inside(cwd, roots):
#                     break
#             elif d.get("type") == "turn_context" and p.get("model"):
#                 model = p.get("model")
#             elif d.get("type") == "event_msg" and p.get("type") == "token_count":
#                 info = p.get("info") or {}
#                 total, last = info.get("total_token_usage"), info.get("last_token_usage")
#                 if not total or total == last_total:
#                     continue
#                 last_total = total
#                 calls += 1
#                 ctx = (last or {}).get("input_tokens", 0) or 0
#                 ctx_max = max(ctx_max, ctx)
#                 if first_ctx is None:
#                     first_ctx = ctx
#         if not cwd or not inside(cwd, roots) or not calls:
#             continue
#         if since and start and start < since:
#             continue
#         out.append({"file": f.name, "start": start, "model": model, "calls": calls,
#                     "first_ctx": first_ctx or 0, "ctx_max": ctx_max,
#                     "in": last_total.get("input_tokens", 0),
#                     "cached": last_total.get("cached_input_tokens", 0),
#                     "out": last_total.get("output_tokens", 0)})
#     out.sort(key=lambda s: s["start"] or datetime.min.replace(tzinfo=timezone.utc))
#     return out
#
#
# # ------------------------------------------------------------ traccia dell'iniezione
#
# LOG_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2}\s+(?:(\S+)\s+)?SessionStart"
#                     r"\s+iniettati (\d+) caratteri")
#
#
# def injection_trend(root: Path):
#     """Per giorno: iniezioni e caratteri massimi, dalle tracce degli hook (nuova e vecchia)."""
#     g = core.git_dir(root)
#     days = defaultdict(lambda: [0, 0])
#     for name in ("agent-hooks.log", "claude-hooks.log"):
#         p = g / name if g else None
#         if not p or not p.is_file():
#             continue
#         for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
#             m = LOG_RE.match(line)
#             if m:
#                 d = days[m.group(1)]
#                 d[0] += 1
#                 d[1] = max(d[1], int(m.group(3)))
#     return sorted(days.items())
#
#
# # ------------------------------------------------------------------------- resoconto
#
# def report(root: Path, extra, giorni, as_json):
#     roots = [norm(root.resolve())] + [norm(Path(e).resolve()) for e in extra]
#     since = (datetime.now(timezone.utc) - timedelta(days=giorni)) if giorni else None
#     fixed = current_fixed(root)
#     measure = load_measure(root)
#     cpt, cpt_src = chars_per_token(measure)
#     other_cwds = set()
#     sessions = claude_sessions(
#         claude_files_for(roots, [root.resolve()] + [Path(e).resolve() for e in extra],
#                          other_cwds), since)
#     cx = codex_sessions(roots, since)
#     trend = injection_trend(root)
#
#     if as_json:
#         def enc(o):
#             return o.isoformat() if isinstance(o, datetime) else str(o)
#         fixed.pop("injection_text", None)
#         print(json.dumps({"fixed": fixed, "measure": measure, "chars_per_token": cpt,
#                           "claude_sessions": sessions, "codex_sessions": cx,
#                           "injection_trend": trend}, default=enc, ensure_ascii=False,
#                          indent=1))
#         return 0
#
#     W = 78
#     print("=" * W)
#     print(f"context_cost — {root}")
#     print("[misurato] = registrato dall'agente o dalla misura esatta   "
#           "[stimato] = calcolato")
#     print("=" * W)
#
#     # 1. Contesto fisso, oggi
#     print("\n1. CONTESTO FISSO CHE QUESTO IMPIANTO AGGIUNGE A OGNI SESSIONE (oggi)")
#     fresh = bool(measure and measure.get("instructions_sha") == fixed["instructions_sha"]
#                  and measure.get("injection_sha") == fixed["injection_sha"])
#     rows = [("istruzioni (" + (", ".join(fixed["instruction_files"]) or "nessuna") + ")",
#              fixed["instructions_chars"], "instructions_tokens"),
#             ("iniezione dell'hook di avvio" + (" (RIDOTTA a indice: oltre il tetto)"
#                                                if fixed["injection_reduced"] else ""),
#              fixed["injection_chars"], "injection_tokens")]
#     tot_tok = 0
#     for label, chars, key in rows:
#         if fresh:
#             tok, tag = measure[key], "[misurato]"
#         else:
#             tok, tag = round(chars / cpt), "[stimato]"
#         tot_tok += tok
#         print(f"  {label}")
#         print(f"      {num(chars)} caratteri  ->  {num(tok)} token {tag}")
#     print(f"  totale: {num(tot_tok)} token, in ogni chiamata al modello della sessione")
#     if fresh:
#         print(f"  misura del {measure['date']} con Claude Code {measure.get('claude_version')}"
#               f", modello {measure.get('model')}; base dell'harness "
#               f"{num(measure['base_tokens'])} token [misurato]")
#     elif measure:
#         print(f"  L'ultima misura ({measure['date']}) e' di contenuti diversi da quelli di "
#               f"oggi: token stimati con il suo rapporto, {cpt:.2f} caratteri/token.")
#         print("  Per il valore esatto: python scripts/context_cost.py misura")
#     else:
#         print(f"  Token stimati a {cpt:.2f} caratteri/token ({cpt_src}).")
#         print("  Per il valore esatto: python scripts/context_cost.py misura")
#
#     # 2. Sessioni Claude Code
#     print("\n2. SESSIONI DI CLAUDE CODE (trascrizioni in "
#           f"{claude_home() / 'projects'})" + (f", ultimi {giorni} giorni" if giorni else ""))
#     if other_cwds:
#         print("  comprese sessioni aperte quando il repository stava altrove: "
#               + ", ".join(sorted(other_cwds)))
#     if not sessions:
#         print("  nessuna trascrizione con cartella di lavoro in questo repository")
#     else:
#         print("  inizio            chiam. sub  compatt.  avvio(tok) max(tok)   costo")
#         for s in sessions:
#             st = s["start"].astimezone().strftime("%Y-%m-%d %H:%M") if s["start"] else "?"
#             print(f"  {st:16s}  {s['calls']:6d} {s['sub_calls']:4d} {s['compactions']:9d}"
#                   f"  {num(s['first_ctx']):>10s} {num(s['ctx_max']):>9s}  "
#                   f"{usd(s['cost']) if s['cost_known'] else 'n/d':>8s}")
#         T = {k: sum(s[k] for s in sessions) for k in ("in", "w5", "w1", "r", "out", "cost",
#                                                     "calls", "sub_calls")}
#         known = all(s["cost_known"] for s in sessions)
#         print(f"  totale: {len(sessions)} sessioni, {num(T['calls'])} chiamate "
#               f"(+{num(T['sub_calls'])} di sottoagenti)")
#         print(f"    token [misurato]: input {num(T['in'])} · scritti in cache "
#               f"{num(T['w5'] + T['w1'])} (di cui 1 ora {num(T['w1'])}) · letti dalla cache "
#               f"{num(T['r'])} · output {num(T['out'])}")
#         print(f"    costo a listino API [stimato]: {usd(T['cost'])}"
#               + ("" if known else "  (esclusi i modelli senza prezzo: "
#                  + ", ".join(sorted({m for s in sessions if not s['cost_known']
#                                      for m in s['models']})) + ")"))
#         used = sorted({re.sub(r"-\d{8}$", "", m) for s in sessions for m in s["models"]
#                        if price_of(m)})
#         unverified = [m for m in used if m not in VERIFIED_PRICES]
#         print("      token misurati per prezzo di listino; listino confrontato con il "
#               "costo calcolato da Claude Code per: "
#               + ", ".join(m for m in used if m in VERIFIED_PRICES)
#               + (f"; NON verificato per: {', '.join(unverified)}" if unverified else ""))
#         allc = T["calls"] + T["sub_calls"]
#         if allc:
#             print(f"    contesto medio per chiamata [misurato]: "
#                   f"{num(round((T['in'] + T['w5'] + T['w1'] + T['r']) / allc))} token")
#         # Quanto del totale e' il contesto fisso di oggi, a parita' di chiamate.
#         if T["calls"]:
#             share = tot_tok * sum(s["read_rate"] + s["write_rate"] for s in sessions) / 1e6
#             print(f"    il contesto fisso di oggi ({num(tot_tok)} token) su queste chiamate "
#                   f"varrebbe ~{usd(share)} [stimato: una scrittura per sessione, poi una "
#                   f"lettura a chiamata, al prezzo del modello di ciascuna]")
#         reads = defaultdict(lambda: [0, 0])
#         for s in sessions:
#             for path, chars, _ in s["reads"]:
#                 reads[path][0] += 1
#                 reads[path][1] += chars
#         if reads:
#             print("  documenti di contesto letti dall'agente (per intero o in parte):")
#             for path, (n, chars) in sorted(reads.items(), key=lambda kv: -kv[1][1])[:10]:
#                 print(f"    {path:40s} {n:4d} letture  {num(round(chars)):>10s} caratteri"
#                       f"  ~{num(round(chars / cpt))} token [stimato]")
#
#     # 3. Codex
#     print("\n3. SESSIONI DI CODEX (" + str(codex_home() / "sessions") + ")")
#     if not cx:
#         print("  nessuna sessione con cartella di lavoro in questo repository")
#     else:
#         for s in cx:
#             st = s["start"].astimezone().strftime("%Y-%m-%d %H:%M") if s["start"] else "?"
#             print(f"  {st}  {s['model'] or '?':14s} {s['calls']:5d} chiamate  avvio "
#                   f"{num(s['first_ctx'])}  max {num(s['ctx_max'])} token [misurato]")
#         print(f"  totale token [misurato]: input {num(sum(s['in'] for s in cx))} (di cui "
#               f"in cache {num(sum(s['cached'] for s in cx))}) · output "
#               f"{num(sum(s['out'] for s in cx))}. Costi non calcolati: listino non noto "
#               f"allo strumento.")
#
#     # 4. Traccia
#     print("\n4. INIEZIONE DI AVVIO NEL TEMPO (traccia degli hook in .git/)")
#     if not trend:
#         print("  nessuna traccia")
#     else:
#         for day, (n, mx) in trend[-14:]:
#             print(f"  {day}  {n:3d} avvii   max {num(mx):>9s} caratteri [misurato]"
#                   f"  ~{num(round(mx / cpt))} token [stimato]")
#     print()
#     return 0
#
#
# # --------------------------------------------------------------------------- misura
#
# def run_claude(cwd: Path):
#     exe = shutil.which("claude") or "claude"
#     r = subprocess.run([exe, "-p", PROMPT, "--max-turns", "1", "--output-format",
#                         "json"], cwd=str(cwd), capture_output=True, text=True,
#                        encoding="utf-8", errors="replace", timeout=300)
#     try:
#         d = json.loads(r.stdout)
#     except ValueError:
#         raise RuntimeError(f"Claude Code non ha dato JSON (uscita {r.returncode}): "
#                            f"{(r.stderr or r.stdout)[-400:]}")
#     u = d.get("usage") or {}
#     total = sum(u.get(k, 0) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
#                                            "cache_read_input_tokens"))
#     model = next(iter(d.get("modelUsage") or {}), None)
#     return total, float(d.get("total_cost_usd") or 0.0), model
#
#
# def measure(root: Path):
#     if shutil.which("claude") is None:
#         print("claude non e' nel PATH: la misura usa Claude Code headless.")
#         return 1
#     fixed = current_fixed(root)
#     try:
#         ver = subprocess.run([shutil.which("claude"), "--version"], capture_output=True, text=True,
#                              timeout=60).stdout.strip()
#     except (OSError, subprocess.SubprocessError):
#         ver = "?"
#     print(f"Misura esatta per {root}")
#     print(f"Claude Code {ver}. Quattro chiamate brevi al modello, in una copia usa e getta.")
#     tmp = Path(tempfile.mkdtemp(prefix="context-cost-"))
#     spent = 0.0
#     try:
#         subprocess.run(["git", "init", "-q", "."], cwd=str(tmp), check=True)
#         base1, c, model = run_claude(tmp); spent += c
#         base2, c, _ = run_claude(tmp); spent += c
#         print(f"  base dell'harness: {num(base1)} e {num(base2)} token")
#         if base1 != base2:
#             print("  La base non e' stabile fra due esecuzioni identiche: una differenza "
#                   "non misurerebbe solo i file. Misura interrotta, niente salvato.")
#             return 1
#         for rel in fixed["instruction_files"]:
#             dst = tmp / rel
#             dst.parent.mkdir(parents=True, exist_ok=True)
#             shutil.copyfile(root / rel, dst)
#         with_instr, c, _ = run_claude(tmp); spent += c
#         # L'hook stampa il testo che l'hook vero inietterebbe OGGI in questo repository.
#         (tmp / "injection.txt").write_text(fixed["injection_text"], encoding="utf-8")
#         (tmp / "print_injection.py").write_text(
#             "import sys\nsys.stdout.reconfigure(encoding='utf-8')\n"
#             "sys.stdout.write(open(__file__.replace('print_injection.py','injection.txt'),"
#             "encoding='utf-8').read())\n", encoding="utf-8")
#         settings = {"hooks": {"SessionStart": [{"hooks": [{
#             "type": "command",
#             "command": f'{Path(sys.executable).as_posix()} '
#                        f'"{(tmp / "print_injection.py").as_posix()}"',
#             "timeout": 30}]}]}}
#         (tmp / ".claude").mkdir(exist_ok=True)
#         (tmp / ".claude" / "settings.local.json").write_text(json.dumps(settings),
#                                                              encoding="utf-8")
#         with_inj, c, _ = run_claude(tmp); spent += c
#     except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
#         print(f"  Misura fallita: {exc}")
#         return 1
#     finally:
#         shutil.rmtree(tmp, ignore_errors=True)
#
#     instr_tok = with_instr - base1
#     inj_tok = with_inj - with_instr
#     if fixed["injection_chars"] and inj_tok <= 0:
#         print("  L'iniezione non risulta nel contesto: l'hook della copia non e' partito. "
#               "Misura non salvata.")
#         return 1
#     result = {
#         "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "claude_version": ver,
#         "model": model, "base_tokens": base1,
#         "instruction_files": fixed["instruction_files"],
#         "instructions_chars": fixed["instructions_chars"],
#         "instructions_sha": fixed["instructions_sha"], "instructions_tokens": instr_tok,
#         "injection_chars": fixed["injection_chars"],
#         "injection_sha": fixed["injection_sha"], "injection_tokens": inj_tok,
#         "cost_usd": round(spent, 4),
#     }
#     g = core.git_dir(root)
#     if g:
#         (g / MEASURE_FILE).write_text(json.dumps(result, indent=1, ensure_ascii=False),
#                                       encoding="utf-8")
#     print(f"  istruzioni ({', '.join(fixed['instruction_files']) or 'nessuna'}): "
#           f"{num(instr_tok)} token [misurato]")
#     print(f"  iniezione dell'hook di avvio: {num(inj_tok)} token [misurato]")
#     print(f"  modello {model}; costo della misura ${spent:.4f} (calcolato da Claude Code)")
#     print(f"  salvata in .git/{MEASURE_FILE}")
#     return 0
#
#
# # ---------------------------------------------------------------------------- main
#
# def main(argv=None):
#     ap = argparse.ArgumentParser(description="Quanto pesa il contesto, misurato.")
#     ap.add_argument("comando", nargs="?", choices=["misura"],
#                     help="misura: misura esatta dei token fissi (chiama Claude Code)")
#     ap.add_argument("--giorni", type=int, default=0,
#                     help="solo le sessioni iniziate negli ultimi N giorni")
#     ap.add_argument("--anche", action="append", default=[], metavar="DIR",
#                     help="conta anche le sessioni aperte in questa cartella")
#     ap.add_argument("--json", action="store_true", help="uscita per programmi")
#     a = ap.parse_args(argv)
#     root = core.repo_root() or Path(__file__).resolve().parent.parent
#     if a.comando == "misura":
#         return measure(Path(root))
#     return report(Path(root), a.anche, a.giorni, a.json)
#
#
# if __name__ == "__main__":
#     sys.exit(main())
#
# ---- AGENT-CONTEXT-FILE: scripts/docs_lint.py ----
# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-
# """
# docs_lint — controlla che la documentazione per agenti dica ancora il vero.
#
# Non guarda il prodotto: guarda i documenti che lo descrivono.
#
# Sei controlli:
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
#   5. FRESCHEZZA       — quanti commit hanno toccato il codice dopo il punto in cui
#                         status.md dichiara di essere riconciliato.
#   6. PESO             — quanto testo l'hook di avvio mette nel contesto a ogni
#                         sessione. Avvisa se i blocchi session-start superano il tetto
#                         di config.toml: in quel caso l'hook inietta solo l'indice.
#
# Dove sta il codice non e' scritto qui: lo rileva scripts/context_core.py a ogni
# esecuzione. Le eccezioni scritte a mano stanno in docs/context/config.toml.
#
# Uso:   python scripts/docs_lint.py [--quiet]
# Esce 0 se non ci sono errori, 1 se ce n'e' almeno uno. I WARN non fanno fallire.
# """
#
# import io
# import re
# import sys
# from pathlib import Path
#
# if hasattr(sys.stdout, "buffer"):
#     sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
#
# # Importare context_core non deve lasciare __pycache__ nel repository.
# sys.dont_write_bytecode = True
# sys.path.insert(0, str(Path(__file__).resolve().parent))
# import context_core as core  # noqa: E402
#
# # --------------------------------------------------------------------------- setup
#
# ROOT = core.repo_root() or Path(__file__).resolve().parent.parent
# CONTEXT = ROOT / core.CONTEXT_DIR
# CONFIG, CONFIG_ERROR = core.load_config(ROOT)
#
# EXPECTED_ABSENT = core.config_table(CONFIG, "lint", "expected_absent")
# EXTERNAL_SYMBOLS = core.config_table(CONFIG, "lint", "external_symbols")
# RECEIVED_DOCS = core.config_table(CONFIG, "lint", "received_docs")
#
# # Parole che sembrano identificatori ma sono prosa. Qui c'e' solo il nucleo indipendente
# # dal progetto; il resto sta in [lint.not_symbols] della configurazione.
# NOT_SYMBOLS_CORE = {
#     "true", "false", "null", "none", "void", "main", "data", "text", "info",
#     "test", "build", "error", "warning", "debug", "http", "https", "json", "yaml",
#     "toml", "git", "origin", "HEAD", "grep", "python", "node", "docker",
#     "feat", "fix", "docs", "chore", "refactor", "style", "perf",
#     # Parole usate dallo scheletro di status.md: senza, il primo giro del lint
#     # segnala il file che l'inizializzatore ha appena scritto.
#     "esito", "chi", "prova", "corrente", "regola", "dove", "livello", "nota",
#     "head", "cronologia", "stato", "lavoro", "commit",
#     "verificato", "dedotto", "assunto",
# }
# # Il confronto avviene sul token gia' abbassato a minuscolo: una voce in maiuscolo non
# # combacerebbe mai, e il difetto resterebbe invisibile. Si normalizza qui, una volta.
# NOT_SYMBOLS = {w.lower() for w in NOT_SYMBOLS_CORE | set(
#     core.config_table(CONFIG, "lint", "not_symbols"))}
#
# # Directory da non attraversare quando si cerca un file citato per nome.
# SKIP_DIRS = core.NON_SOURCE_DIRS - {"docs", "doc"} | {".git"}
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
# def tracked_files():
#     """Solo i file versionati: un documento di appunti non tracciato non fa fallire."""
#     ok, out = core.run_git(ROOT, "ls-files")
#     if not ok:
#         return None
#     return {(ROOT / line).resolve() for line in out.splitlines() if line.strip()}
#
#
# CODE_BLOB = None
#
# def code_blob() -> str:
#     global CODE_BLOB
#     if CODE_BLOB is None:
#         CODE_BLOB = "\n".join(read(ROOT / rel) for rel in core.tree_files(ROOT, CONFIG))
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
# # ---------------------------------------------------------------- 0. configurazione
#
# def check_config(rep: Report):
#     if CONFIG_ERROR:
#         rep.error("CONFIG", CONFIG_ERROR + " — le eccezioni scritte li' sono ignorate")
#     files = core.code_files(ROOT, CONFIG)
#     _, labels = core.code_scope(ROOT, CONFIG)
#     if labels:
#         shown = ", ".join(labels[:12]) + (" …" if len(labels) > 12 else "")
#         rep.note(f"  codice rilevato: {len(files)} file in {shown}")
#     else:
#         rep.note("  codice rilevato: nessuno, per ora. I controlli sul codice restano "
#                  "inattivi finche' non ce n'e'.")
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
#     para = re.search(r"Nessun riferimento nel codice a:(.*?)(?:\n\s*\n|\n\||\Z)",
#                      m.group(1), re.S)
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
#     # Il codice del progetto, senza i file di questo impianto: il lint e l'inizializzatore
#     # contengono i nomi banditi per poterli cercare, e si accuserebbero da soli.
#     files = [ROOT / rel for rel in core.code_files(ROOT, CONFIG)]
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
# # Un elenco chiuso di estensioni, non "qualunque cosa dopo un punto": altrimenti
# # `sys.stdout` o `obj.field` diventerebbero percorsi inesistenti.
# PATH_RE = re.compile(
#     r"^[\w./\-]+\.(?:c|h|cc|cpp|hpp|cs|m|mm|swift|kt|java|py|rb|php|go|rs|js|jsx|ts|tsx"
#     r"|vue|svelte|sh|ps1|sql|html|css|scss|json|toml|yml|yaml|ini|cfg|conf|xml|md|rst"
#     r"|txt|cmake|dts|dtsi|overlay|pem|lock|env|gradle|csproj|sln)$")
# IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{3,}$")
#
#
# def path_exists_anywhere(rel: str) -> bool:
#     """
#     Un documento puo' citare un file per nome senza il percorso completo: `foo.md`
#     che sta in docs/, mentre chi lo cita e' in docs/context/. Cercarlo solo dalla
#     radice e solo accanto a chi lo cita produce un falso positivo, e i falsi positivi
#     sono il modo in cui un lint smette di essere letto. Regge anche i glob (`lib/*.h`).
#     """
#     if (ROOT / rel).exists():
#         return True
#     try:
#         for hit in ROOT.glob("**/" + rel):
#             if not any(part in SKIP_DIRS for part in hit.relative_to(ROOT).parts):
#                 return True
#     except (ValueError, OSError, IndexError, NotImplementedError):
#         pass
#     return False
#
#
# def _is_prose(tok: str) -> bool:
#     """Frammenti di comando, formule e frasi fra backtick non sono identificatori."""
#     if " " in tok or "=" in tok or "(" in tok or "×" in tok or "@" in tok:
#         return True
#     # Segnaposto in un template: topic, rotta HTTP, nome di file parametrico.
#     # `epic/{mac}/data` non e' un percorso che debba esistere sul disco.
#     if "{" in tok or "}" in tok or "<" in tok or ">" in tok:
#         return True
#     # Unita' di misura: due segmenti, il secondo cortissimo e alfabetico — `m/s`,
#     # `km/h`, `entry/s`. La soglia stretta sul secondo segmento evita di scambiare
#     # per unita' una cartella vera come `epic/data`.
#     seg = tok.split("/")
#     if len(seg) == 2 and seg[0].isalpha() and seg[1].isalpha() and len(seg[1]) <= 3:
#         return True
#     if tok.startswith(("-", ".", "~", "#", "/")):
#         return True
#     if tok.startswith("build/"):
#         return True
#     # `Acq_TryClaim/Release/Current`: scorciatoia di prosa, non un percorso.
#     if "/" in tok and not PATH_RE.match(tok):
#         if any(seg[:1].isupper() for seg in tok.split("/") if seg):
#             return True
#     return False
#
#
# def _is_external(tok: str, base: str) -> bool:
#     if base in EXTERNAL_SYMBOLS:
#         return True
#     return any(k.endswith("/") and tok.startswith(k) for k in EXTERNAL_SYMBOLS)
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
#         if (_is_prose(tok) or GITREF_RE.match(tok)
#                 or tok.lower() in NOT_SYMBOLS or base.lower() in NOT_SYMBOLS
#                 or _is_external(tok, base)
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
#             # di un nome lungo (`INFO_ID_STREAM` per PACKET_INFO_ID_STREAM). E' la
#             # regola dell'altitudine: il documento non ripete il prefisso.
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
# LEVELS = core.EVIDENCE_LEVELS
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
#         if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
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
#     # I file di ingresso degli agenti stanno nella radice e contengono quasi tutti i
#     # link: si prendono tutti i .md della radice, non un elenco di nomi da aggiornare.
#     targets = sorted(ROOT.glob("*.md"))
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
#         # Un documento ricevuto non e' nostro da riparare: vedi [lint.received_docs].
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
# def check_freshness(rep: Report):
#     status = CONTEXT / "status.md"
#     text = read(status)
#     if not text:
#         rep.error("FRESCHEZZA", "docs/context/status.md non esiste o non e' leggibile")
#         return
#     sha = core.read_marker(text)
#     if not sha:
#         if core.head_sha(ROOT) is None:
#             # Nessun commit ancora: non c'e' uno sha a cui ancorarsi, ed e' normale.
#             rep.warn("FRESCHEZZA", "il repository non ha ancora un commit: la freschezza "
#                                    "si misura dal primo. Dopo il commit rilancia "
#                                    "agent_context_init.py, che aggiunge il marcatore")
#             return
#         rep.error("FRESCHEZZA",
#                   "status.md non ha il marcatore <!-- context-verified-at: <sha> -->: "
#                   "senza, la freschezza non e' misurabile")
#         return
#     specs, labels = core.code_scope(ROOT, CONFIG)
#     if not specs:
#         rep.note(f"  status.md riconciliato a {sha}; nessun codice da sorvegliare, per ora")
#         return
#     ok, lines = core.commits_since(ROOT, sha, specs)
#     if not ok:
#         rep.warn("FRESCHEZZA", f"commit {sha} non trovato: il marcatore punta al vuoto")
#         return
#     where = ", ".join(labels[:8]) + (" …" if len(labels) > 8 else "")
#     if lines:
#         rep.warn("FRESCHEZZA",
#                  f"{len(lines)} commit hanno toccato il codice ({where}) dopo {sha}, "
#                  f"a cui status.md dichiara di essere riconciliato:\n      " +
#                  "\n      ".join(lines[:8]))
#     else:
#         rep.note(f"  status.md riconciliato a {sha}: nessun commit sul codice da allora")
#
#
# # ------------------------------------------------------------------------- main
#
# # ---------------------------------------------------------------- 6. peso all'avvio
#
# def check_weight(rep: Report):
#     """
#     Cosa entra nel contesto dell'agente a ogni avvio per opera di questo impianto. Solo
#     caratteri: il lint non ha un tokenizer, i token veri li misura context_cost.py.
#     """
#     inj = core.build_injection(ROOT, CONFIG)
#     if inj is None:
#         rep.note("  nessun status.md: l'hook di avvio non inietta niente")
#     else:
#         rep.note(f"  iniezione di avvio: {len(inj['text'])} caratteri  —  blocchi "
#                  f"session-start: {inj['blocks_chars']} su un tetto di {inj['budget']}")
#         if inj["reduced"]:
#             rep.warn("PESO", f"i blocchi session-start di {core.STATUS_FILE} fanno "
#                              f"{inj['blocks_chars']} caratteri, oltre il tetto di "
#                              f"{inj['budget']}: l'hook inietta solo il loro indice. "
#                              f"Riportali sotto il tetto: vedi la guida, «status.md "
#                              f"invecchia male».")
#     for name in ("AGENTS.md", "CLAUDE.md"):
#         p = ROOT / name
#         if p.is_file():
#             rep.note(f"  {name}: {len(read(p))} caratteri, caricati a ogni sessione "
#                      f"(piu' cio' che importa)")
#     rep.note("  i token veri: python scripts/context_cost.py")
#
#
# CHECKS = [
#     ("0. CONFIGURAZIONE  — cosa viene considerato codice", check_config),
#     ("1. FEATURE BANDITE — simboli che non devono tornare", check_banned),
#     ("2. IDENTIFICATORI  — cio' che i doc citano esiste ancora", check_identifiers),
#     ("3. EVIDENZA        — verificato/dedotto/assunto", check_evidence),
#     ("4. LINK E ANCORE   — i rimandi risolvono", check_links),
#     ("5. FRESCHEZZA      — status.md rispetto al codice", check_freshness),
#     ("6. PESO            — cosa entra nel contesto a ogni avvio", check_weight),
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
