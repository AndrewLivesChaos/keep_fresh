#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kf_init — prepara un repository per keep-fresh, e ne dice lo stato.

    <python> <plugin>/scripts/kf_init.py [--dry-run]   inizializza il repository corrente
    <python> <plugin>/scripts/kf_init.py --status      stato, in sola lettura; esce 1 se
                                                       c'e' qualcosa da sistemare

Nel progetto scrive solo due SEMI, mai sovrascritti: .keep-fresh/config.toml (la taratura)
e lo scheletro di docs/keep-fresh/context/status.md. Il codice (lint, hook, handoff) sta
nel plugin e non viene copiato: un aggiornamento del plugin vale per tutti i progetti.
Gli hook li aggancia il plugin stesso, non questo script.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import context_core as core  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[1]
GUIDE = PLUGIN / "guide.md"
CONFIG_TEMPLATE = PLUGIN / "templates" / "config.toml"
PLUGIN_ID = "keep-fresh@keep-fresh"
CONFIG_FILE = core.CONFIG_FILE
STATUS_FILE = core.STATUS_FILE
PY = core.PY

STATUS_SKELETON = """# Stato del lavoro
{marker}
**Ultimo aggiornamento: {today}.**

> Il marcatore `context-verified-at` qui sopra e' il commit fino al quale questo
> documento e' stato **riconciliato con il codice**. Chi lo riconcilia lo riporta a
> `HEAD`. Il lint di keep-fresh (`/keep-fresh:lint`) dice quanti commit hanno toccato il
> codice da allora: e' l'unica misura oggettiva di quanto questo file sia invecchiato.
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

PROMPT = """Leggi {guide} ed eseguilo su questo repository.
Sono istruzioni operative, non la descrizione di un altro progetto.

Prima di scrivere, chiedimi quello che non e' deducibile dal repo: stato del lavoro,
decisioni prese fuori dal codice, verifiche fatte a mano.

Il lint, gli hook e gli handoff stanno nel plugin keep-fresh: NON vanno scritti ne' copiati
nel progetto. Dove sta il codice lo rilevano da soli a ogni esecuzione. La taratura a mano
sta in .keep-fresh/config.toml: le liste di eccezioni del lint partono vuote di proposito,
e si riempiono guardando i falsi positivi del primo giro, con il motivo scritto per ogni
voce. Il contesto che scrivi tu sta in docs/keep-fresh/context/.

Fai girare il lint (`/keep-fresh:lint`, oppure `{lint}`) e mostrami l'output vero prima di
dichiarare concluso. Al primo giro sara' rumoroso: correggi prima i CONTROLLI, poi i
documenti. Una segnalazione che descrive un difetto vero — un riferimento a una rinomina
mai fatta, un simbolo sparito — non va messa a tacere: va registrata come lavoro aperto.

A lavoro finito i file di keep-fresh (.keep-fresh/config.toml, docs/keep-fresh/, AGENTS.md,
CLAUDE.md) devono essere versionati, non lasciati untracked. Segui la regola su commit e
push che ti ho dato, e non fare push."""


# ----------------------------------------------------------------------------- utili

def git(root, *args) -> str:
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=str(root),
                           env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
        return r.stdout.strip() if r.returncode == 0 else ""
    except OSError:
        return ""


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
    sha = core.head_sha(root)
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


def initial_commit(root: Path) -> str | None:
    """Un commit vuoto, per avere uno sha. None, dicendo perche', se git lo rifiuta."""
    r = subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "Initial commit"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=str(root))
    sha = core.head_sha(root) if r.returncode == 0 else None
    if sha:
        print(f'  creato   commit vuoto "Initial commit" ({sha})\n')
    else:
        motivo = (r.stderr or r.stdout).strip().splitlines()
        print('  NON fatto il commit vuoto "Initial commit": git ha risposto\n'
              f"           {motivo[-1] if motivo else f'exit {r.returncode}'}\n"
              "  status.md nasce senza marcatore: dopo il primo commit rilancia "
              "/keep-fresh:init.\n")
    return sha


def put_seed(root: Path, rel: str, content: str, dry: bool) -> str:
    """Un seme si scrive solo se manca: da li' in poi contiene lavoro, ed e' dell'utente."""
    p = root / rel
    if p.exists():
        return f"  TUO      {rel}  (esiste: mai sovrascritto)"
    if not dry:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
    return f"  creato   {rel}"


# ------------------------------------------------------------------- installazioni

@dataclass
class Install:
    agent: str               # "claude" o "codex"
    config_dir: Path
    installed: bool
    enabled: bool | None     # None: non si sa
    version: str | None


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _claude_install(cfg: Path) -> Install:
    data = _read_json(cfg / "plugins" / "installed_plugins.json") or {}
    plugins = data.get("plugins") if isinstance(data, dict) else None
    entries = plugins.get(PLUGIN_ID) if isinstance(plugins, dict) else None
    version = None
    if isinstance(entries, list) and entries and isinstance(entries[0], dict):
        version = entries[0].get("version")
    settings = _read_json(cfg / "settings.json") or {}
    enabled_map = settings.get("enabledPlugins") if isinstance(settings, dict) else None
    enabled = enabled_map.get(PLUGIN_ID) if isinstance(enabled_map, dict) else None
    # Senza voce in enabledPlugins un plugin installato parte attivo.
    if version is not None and enabled is None:
        enabled = True
    return Install("claude", cfg, version is not None, enabled, version)


def _codex_install(home: Path) -> Install:
    try:
        with open(home / "config.toml", "rb") as fh:
            cfg = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        cfg = {}
    entry = cfg.get("plugins", {}).get(PLUGIN_ID) if isinstance(cfg.get("plugins"), dict) else None
    cache = home / "plugins" / "cache"
    versions = sorted(p.name for p in cache.glob(f"*/keep-fresh/*") if p.is_dir()) \
        if cache.is_dir() else []
    installed = isinstance(entry, dict)
    enabled = entry.get("enabled") if installed else None
    return Install("codex", home, installed, enabled, versions[-1] if versions else None)


def plugin_installs() -> list:
    """
    Dove e' installato il plugin su questa macchina: una voce per ogni configurazione di
    Claude Code (le cartelle ~/.claude*, e CLAUDE_CONFIG_DIR se punta altrove) e una per
    Codex se c'e'. Sola lettura.
    """
    home = Path.home()
    dirs = sorted(p for p in home.glob(".claude*")
                  if p.is_dir() and ((p / "settings.json").is_file() or (p / "plugins").is_dir()))
    extra = os.environ.get("CLAUDE_CONFIG_DIR")
    if extra and Path(extra).is_dir() and Path(extra).resolve() not in {d.resolve() for d in dirs}:
        dirs.append(Path(extra))
    out = [_claude_install(d) for d in dirs]
    codex = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    if codex.is_dir():
        out.append(_codex_install(codex))
    return out


def describe_install(i: Install) -> tuple:
    """(flag, testo) per una riga di stato."""
    label = "Claude Code" if i.agent == "claude" else "Codex"
    if not i.installed:
        return "!!", f"{label:<12}non installato in {i.config_dir}"
    if i.enabled is False:
        return "!!", f"{label:<12}{i.version or '?'} DISATTIVATO in {i.config_dir}"
    return "OK", f"{label:<12}{i.version or '?'} in {i.config_dir}"


# ------------------------------------------------------------------------ diagnosi

def stale_copies(root: Path) -> list:
    """
    Copie del vecchio inizializzatore nel repository. Servivano a riagganciare gli hook
    su un clone; con il plugin non servono piu', ma toglierle e' una scelta del progetto.
    """
    elenco = git(root, "ls-files", "--cached", "--others", "--exclude-standard",
                 "--", "*agent_context_init.py")
    return [f"{rel} e' una copia del vecchio inizializzatore: con il plugin non serve piu'.\n"
            f"     Toglierla o tenerla e' una scelta del progetto: chiedi prima."
            for rel in filter(None, elenco.splitlines())]


def diagnose(root: Path) -> list:
    """Cosa non funziona ancora nel progetto: taratura, stato, marcatore, vecchio impianto."""
    problemi = []
    if core.old_install(root):
        problemi.append("c'e' ancora il vecchio impianto (.keep-fresh/scripts/): finche' resta, "
                        "gli hook del plugin\n     cedono il passo a quella copia. Migra con "
                        "/keep-fresh:migrate.")
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
            if core.head_sha(root) is None:
                problemi.append(
                    "il repository non ha ancora un commit, quindi status.md non ha il\n"
                    "     marcatore di freschezza. Fai il primo commit e rilancia "
                    "/keep-fresh:init:\n     lo aggiunge da solo.")
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
    problemi += stale_copies(root)
    return problemi


# -------------------------------------------------------------------------- status

HOOK_LOG_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\s+(\S+)\s+(\S+)\s+(.*)$")


def _ago(when: str) -> str:
    from datetime import datetime
    try:
        delta = datetime.now() - datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""
    s = int(delta.total_seconds())
    if s < 3600:
        return f"{max(s // 60, 0)} min fa"
    if s < 86400:
        return f"{s // 3600} h fa"
    return f"{s // 86400} giorni fa"


def hook_runs(root: Path) -> dict:
    """
    Dalla traccia .git/agent-hooks.log: per ogni agente, l'ultima riga di ogni evento.
    Sola lettura. Un hook fail-open che smette di girare non da' errori: l'unico segno
    e' che l'ultima riga diventa vecchia.
    """
    g = core.git_dir(root)
    if g is None:
        return {}
    try:
        lines = (g / "agent-hooks.log").read_text(encoding="utf-8",
                                                  errors="replace").splitlines()
    except OSError:
        return {}
    last = {}
    for line in lines:
        m = HOOK_LOG_RE.match(line)
        if m:
            when, agent, event, outcome = m.groups()
            last.setdefault(agent, {})[event] = (when, outcome)
    return last


def status(root: Path) -> int:
    """
    Lo stato di keep-fresh in questo repository, in sola lettura: non scrive niente, nemmeno
    i compilati di Python ne' l'indice di git. Esce 0 se non c'e' niente da sistemare, 1
    altrimenti.
    """
    print(f"keep-fresh: stato di {root}")
    print("(sola lettura: non scrive niente)\n")

    def riga(flag, label, text):
        print(f"  [{flag}]  {label:<18}{text}")

    problemi = []
    print("Progetto")
    if not core.uses_keep_fresh(root):
        riga("!!", "keep-fresh", f"non usato: manca {CONFIG_FILE}")
        print("\nkeep-fresh non e' installato in questo repository. Per installarlo: "
              "/keep-fresh:init")
        return 1
    riga("OK", "taratura", CONFIG_FILE)
    if core.old_install(root):
        riga("!!", "vecchio impianto", ".keep-fresh/scripts/ c'e' ancora: /keep-fresh:migrate")

    print("\nPlugin")
    installs = plugin_installs()
    for i in installs:
        flag, text = describe_install(i)
        print(f"  [{flag}]  {text}")
    if not installs:
        print("  [!!]  nessuna configurazione di Claude Code o di Codex trovata")
    if not any(i.installed and i.enabled is not False for i in installs):
        problemi.append("il plugin keep-fresh non e' installato e attivo in nessuna "
                        "configurazione:\n     gli hook non partono. Vedi il README del "
                        "plugin per installarlo.")

    print("\nHook (dalla traccia .git/agent-hooks.log)")
    runs = hook_runs(root)
    if not runs:
        print(f"{'':<8}nessuna esecuzione in traccia: se ci hai lavorato, gli hook non partono")
    for agent, mine in sorted(runs.items()):
        ultima = max(mine.values(), key=lambda v: v[0])[0]
        riga("OK", agent, f"ultima esecuzione: {ultima} ({_ago(ultima)})")
        stop = mine.get("Stop")
        if stop:
            print(f"{'':<26}ultimo Stop: {stop[0]}  {stop[1][:70]}")

    print("\nHandoff")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_OPTIONAL_LOCKS="0")
    r = subprocess.run([sys.executable, str(Path(__file__).with_name("handoff.py")), "list"],
                       cwd=str(root), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    righe = r.stdout.splitlines()
    prima_riga = (righe or [""])[0]
    rotti = [l.strip() for l in righe[1:] if l.lstrip().startswith("! ")]
    if r.returncode == 0 and prima_riga:
        riga("!!" if rotti else "OK", "handoff", f"{prima_riga} (.git/keep-fresh-handoff/)")
        for l in righe[1:9]:
            print(f"{'':<26}{l.strip()}")
        if rotti:
            problemi.append(f"{len(rotti)} handoff illeggibili in .git/keep-fresh-handoff/ "
                            f"(ignorati, non compaiono nell'indice): {'; '.join(rotti)}")
    else:
        riga("!!", "handoff", "handoff.py list non risponde")
        problemi.append(f"`{core.script_cmd('handoff.py', 'list')}` esce con errore: "
                        f"lancialo a mano per vedere perche'.")

    print("\nQualita'")
    r = subprocess.run([sys.executable, str(Path(__file__).with_name("docs_lint.py"))],
                       cwd=str(root), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    out = r.stdout
    n_err = int((re.search(r"^ERRORI: (\d+)", out, re.M) or [0, 0])[1])
    n_warn = int((re.search(r"^AVVISI: (\d+)", out, re.M) or [0, 0])[1])
    if r.returncode == 0:
        riga("OK", "lint", f"nessun errore, {n_warn} avvisi")
    else:
        riga("!!", "lint", f"{n_err or '?'} errori, {n_warn} avvisi (exit {r.returncode})")
        problemi.append("il lint esce con errore: /keep-fresh:lint dice quali.")
    for tag, msg in re.findall(r"^\s+\[([A-Z]+)\] (.*)$", out, re.M)[:6]:
        print(f"{'':<26}[{tag}] {msg[:88]}")

    for p in diagnose(root):
        if p not in problemi:
            problemi.append(p)

    print()
    if not problemi:
        print("Esito: tutto a posto.")
        return 0
    print(f"Esito: {len(problemi)} cosa/e da sistemare:")
    for n, p in enumerate(problemi, 1):
        print(f"  {n}. {p}")
    return 1


# ---------------------------------------------------------------------------- init

def init(root: Path, dry: bool) -> int:
    print(f"Repository : {root}")
    print(f"Plugin     : {PLUGIN}")
    if dry:
        print("MODALITA' DRY-RUN: non viene scritto niente.")
    print()

    if core.old_install(root):
        print("Questo repository ha ancora il vecchio impianto (.keep-fresh/scripts/).\n"
              "Non lo tocco da qui: per portarlo sul plugin c'e' /keep-fresh:migrate.\n")

    status_existed = (root / STATUS_FILE).exists()
    sha = core.head_sha(root)
    if sha is None:
        # Il marcatore di freschezza vuole uno sha. Il commit e' vuoto: i file che ci sono
        # gia' sono dell'utente, e cosa versionare lo decide lui.
        print("Il repository non ha ancora nessun commit: per dare a status.md il marcatore\n"
              "di freschezza serve uno sha.")
        if dry:
            print('  farei   un commit vuoto "Initial commit" (nessun file dentro)\n')
        else:
            sha = initial_commit(root)
    # In un repo senza commit non c'e' uno sha da scrivere: meglio nessun marcatore, che il
    # giro dopo il primo commit aggiunge, di un marcatore finto.
    marker = f"\n<!-- context-verified-at: {sha} -->\n" if sha else "\n"
    print(put_seed(root, CONFIG_FILE, CONFIG_TEMPLATE.read_text(encoding="utf-8"), dry))
    print(put_seed(root, STATUS_FILE,
                   STATUS_SKELETON.format(marker=marker, today=date.today().isoformat()), dry))
    if status_existed:
        fatto = add_marker(root, dry)
        if fatto:
            print(f"  status:  {fatto}")

    cfg, _ = core.load_config(root)
    files = core.code_files(root, cfg)
    _, labels = core.code_scope(root, cfg)
    print("\nCodice rilevato adesso (lint e hook lo rilevano di nuovo a ogni esecuzione):")
    print(f"  {len(files)} file in {', '.join(labels[:12])}" + (" …" if len(labels) > 12 else "")
          if labels else "  nessuno, per ora. Va bene: quando il codice arriva, viene visto.")

    if dry:
        return 0
    problemi = diagnose(root)
    print("\n" + "=" * 74)
    print("Fatta la meccanica. Il contesto lo deve ancora scrivere l'agente.")
    print("=" * 74)
    print("\nIl prompt per l'agente:\n")
    print("-" * 74)
    print(PROMPT.format(guide=GUIDE, lint=core.script_cmd("docs_lint.py")))
    if problemi:
        print("\nInoltre restano aperti questi punti, sistemali:")
        for n, msg in enumerate(problemi, 1):
            print(f"  {n}. {msg}")
    print("-" * 74)
    print("\nGli hook li aggancia il plugin: partono alla prossima sessione in questo "
          "repository.\nPer vedere se girano: /keep-fresh:status (legge .git/agent-hooks.log).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Prepara un repository per keep-fresh.")
    ap.add_argument("--dry-run", action="store_true", help="dice cosa farebbe")
    ap.add_argument("--status", action="store_true",
                    help="stato in sola lettura; esce 1 se c'e' qualcosa da sistemare")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = core.repo_root()
    if root is None:
        print("Non sei dentro un repository git. Fai prima `git init`.", file=sys.stderr)
        return 1
    return status(root) if args.status else init(root, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
