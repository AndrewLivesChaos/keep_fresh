#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selftest — prova il plugin keep-fresh su repository finti, dall'inizio.

    python plugins/keep-fresh/tests/selftest.py

Esce 0 e stampa "self-test: OK (N passi)" solo se nessun passo fallisce; altrimenti
elenca i passi falliti ed esce 1. Non tocca niente fuori dalle cartelle temporanee che
crea. Gli script si eseguono da plugins/keep-fresh/scripts/, come li esegue un agente
che ha il plugin installato.
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

PLUGIN = Path(__file__).resolve().parents[1]
REPO = PLUGIN.parents[1]
SCRIPTS = PLUGIN / "scripts"
HOOKS_SCRIPT = SCRIPTS / "agent_hooks.py"
LINT_SCRIPT = SCRIPTS / "docs_lint.py"
COST_SCRIPT = SCRIPTS / "context_cost.py"
HANDOFF_SCRIPT = SCRIPTS / "handoff.py"
CONFIG_FILE = ".keep-fresh/config.toml"
STATUS_FILE = "docs/keep-fresh/context/status.md"

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
           GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.autocrlf",
           GIT_CONFIG_VALUE_0="false", CLAUDE_PLUGIN_ROOT=str(PLUGIN),
           PYTHONDONTWRITEBYTECODE="1")

failures = []
passed = 0
_tmpdirs = []


def step(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
    else:
        failures.append(f"{name}" + (f"\n      {detail}" if detail else ""))


def run(*args, cwd, stdin=None, env=None):
    return subprocess.run([str(a) for a in args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          env=env or ENV, input=stdin)


def tmpdir(prefix="kf-selftest-") -> Path:
    p = Path(tempfile.mkdtemp(prefix=prefix))
    _tmpdirs.append(p)
    return p


def git_repo(with_config=True) -> Path:
    """Un repository git vuoto; con with_config ha .keep-fresh/config.toml dal modello."""
    root = tmpdir()
    run("git", "init", "-q", ".", cwd=root)
    if with_config:
        (root / ".keep-fresh").mkdir()
        shutil.copyfile(PLUGIN / "templates" / "config.toml",
                        root / ".keep-fresh" / "config.toml")
    return root


def hook_log(root: Path) -> str:
    p = root / ".git" / "agent-hooks.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def new_project() -> Path:
    """
    Un progetto keep-fresh appena inizializzato: config.toml, scheletro di status.md con
    il marcatore di freschezza, due commit. Lo prepara kf_init, come per l'utente.
    """
    root = git_repo(with_config=False)
    run(sys.executable, SCRIPTS / "kf_init.py", cwd=root)
    run("git", "add", "-A", cwd=root)
    run("git", "commit", "-q", "-m", "init", cwd=root)
    run(sys.executable, SCRIPTS / "kf_init.py", cwd=root)
    run("git", "add", "-A", cwd=root)
    run("git", "commit", "-q", "-m", "marcatore", cwd=root)
    return root


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


# ----------------------------------------------------------------------------- manifesti

def test_manifests():
    claude = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    codex = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text("utf-8"))
    step("manifesti: la versione e' la stessa per Claude Code e Codex",
         claude.get("version") == codex.get("version")
         and re.fullmatch(r"\d+\.\d+\.\d+", str(claude.get("version"))) is not None,
         f"claude={claude.get('version')!r} codex={codex.get('version')!r}")

    entries = []
    for rel in (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"):
        entries += json.loads((REPO / rel).read_text("utf-8")).get("plugins", [])
    step("manifesti: nessuna version nelle voci dei marketplace",
         entries and all("version" not in e for e in entries), str(entries))

    if shutil.which("claude") is None:
        print("  (saltato: claude plugin validate, claude non e' sul PATH)")
        return
    for target in (REPO, PLUGIN):
        r = run("claude", "plugin", "validate", target, cwd=REPO)
        step(f"claude plugin validate passa su {target.name}", r.returncode == 0,
             (r.stdout + r.stderr)[-600:])


def test_launcher():
    root = git_repo()
    sub = root / "a" / "b"
    sub.mkdir(parents=True)
    bash = shutil.which("bash")
    if bash is None:
        print("  (saltato: run-hook.cmd, bash non e' sul PATH)")
        return
    r = run(bash, PLUGIN / "hooks" / "run-hook.cmd", "session-start", "--agent", "prova",
            cwd=sub, stdin="{}")
    step("run-hook.cmd lancia agent_hooks da una sottocartella",
         r.returncode == 0 and "prova" in hook_log(root),
         f"exit={r.returncode} log={hook_log(root)!r} err={r.stderr[-300:]}")


# ------------------------------------------------------------------- script

def test_scripts():
    """
    I passi dello smoke test di agent_context_init.py che provano gli script: Stop,
    SessionStart, tetto dell'iniezione, misura dei costi, avvisi del prompt, handoff.
    Stesso repository dall'inizio alla fine, come allora: i passi dipendono dall'ordine.
    """
    tmp = new_project()
    env = ENV

    def run(*args, stdin=None):
        return subprocess.run([str(a) for a in args], cwd=str(tmp), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", env=env,
                              input=stdin)

    def lint(name):
        r = run(sys.executable, LINT_SCRIPT)
        out = r.stdout + r.stderr
        step(f"{name}: il lint esce 0", r.returncode == 0, _lint_lines(out))
        step(f"{name}: nessun errore interno del lint", "[INTERNO]" not in out,
             _lint_lines(out))
        return out

    def stop_hook(stdin):
        return run(sys.executable, HOOKS_SCRIPT, "stop", "--agent", "prova", stdin=stdin)

    def snap():
        out = {}
        for q in tmp.rglob("*"):
            if q.is_file():
                try:
                    st = q.stat()
                    out[q.relative_to(tmp).as_posix()] = (st.st_size, st.st_mtime_ns)
                except OSError:
                    pass
        return out

    def cambiati(prima):
        dopo = snap()
        return sorted(k for k in set(prima) | set(dopo) if prima.get(k) != dopo.get(k))

    lint("progetto nuovo")
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
    r = run(sys.executable, HOOKS_SCRIPT, "session-start", "--agent", "prova",
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
    r = run(sys.executable, HOOKS_SCRIPT, "session-start", "--agent", "prova",
            stdin='{"source":"startup"}')
    step("oltre il tetto SessionStart inietta solo l'indice",
         r.returncode == 0 and "solo il loro indice" in r.stdout,
         f"exit {r.returncode}: {r.stdout[-400:]}")
    r = run(sys.executable, LINT_SCRIPT)
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
        r = subprocess.run([sys.executable, COST_SCRIPT, "--json"],
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

    # L'avviso di ripresa: ferma una volta dopo una pausa piu' lunga della cache con
    # un contesto grande, poi lascia passare; mai un comando /, mai una pausa corta o
    # un contesto piccolo. Trascrizioni finte, di Claude Code e di Codex.
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    def transcript(name, hours_ago, ctx, codex=False):
        ts = (_dt.now(_tz.utc) - _td(hours=hours_ago)).isoformat().replace("+00:00", "Z")
        if codex:
            rows = [{"timestamp": ts, "type": "turn_context",
                     "payload": {"model": "gpt-prova"}},
                    {"timestamp": ts, "type": "event_msg", "payload": {
                        "type": "token_count", "info": {
                            "last_token_usage": {"input_tokens": ctx},
                            "total_token_usage": {"input_tokens": ctx}}}}]
        else:
            rows = [{"timestamp": ts, "type": "assistant", "message": {
                "id": "m", "model": "claude-opus-5-5", "content": [], "usage": {
                    "input_tokens": 2, "cache_creation_input_tokens": 1000,
                    "cache_creation": {"ephemeral_1h_input_tokens": 1000},
                    "cache_read_input_tokens": ctx - 1002, "output_tokens": 5}}}]
        p = tmp / ".git" / name
        p.write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")
        return p

    def prompt_hook(tp, text="continua", sid="p1"):
        return run(sys.executable, HOOKS_SCRIPT, "prompt", "--agent", "prova",
                   stdin=json.dumps({"session_id": sid, "transcript_path": str(tp),
                                     "prompt": text}))

    def blocked(r):
        try:
            return json.loads(r.stdout).get("decision") == "block"
        except ValueError:
            return False

    # Questi passi provano la sola ripresa: l'avviso dell'handoff ha la sua soglia a
    # 150.000 e con questi contesti scatterebbe anche lui. Si spegne finche' dura il blocco.
    cfg_attuale = cfg_p.read_text(encoding="utf-8")
    step("la taratura installata porta le chiavi dell'handoff, commentate",
         "# handoff_warn_tokens = 150000" in cfg_attuale
         and "# handoff_ore = 48" in cfg_attuale
         and "# handoff_prune_giorni = 30" in cfg_attuale, cfg_attuale[-600:])
    cfg_p.write_text(cfg_attuale.replace("# handoff_warn_tokens = 150000",
                                         "handoff_warn_tokens = 0"), encoding="utf-8")
    big = transcript("t-big.jsonl", 3, 200_000)
    r = prompt_hook(big, "/clear")
    step("prompt: un comando / passa sempre", r.returncode == 0 and not r.stdout.strip(),
         r.stdout[-300:])
    r = prompt_hook(big)
    step("prompt: pausa di 3 h e contesto di 200 mila token ferma il messaggio",
         r.returncode == 0 and blocked(r) and "$" in r.stdout, r.stdout[-400:])
    r = prompt_hook(big)
    step("prompt: reinviato, il messaggio passa",
         r.returncode == 0 and not r.stdout.strip(), r.stdout[-300:])
    r = prompt_hook(transcript("t-recent.jsonl", 0.5, 200_000), sid="p2")
    step("prompt: una pausa piu' corta della cache non ferma",
         r.returncode == 0 and not r.stdout.strip(), r.stdout[-300:])
    r = prompt_hook(transcript("t-small.jsonl", 3, 20_000), sid="p3")
    step("prompt: un contesto piccolo non ferma",
         r.returncode == 0 and not r.stdout.strip(), r.stdout[-300:])
    r = prompt_hook(transcript("t-codex.jsonl", 3, 200_000, codex=True), sid="p4")
    step("prompt: la trascrizione di Codex si legge e ferma",
         r.returncode == 0 and blocked(r), r.stdout[-400:])
    r = prompt_hook(tmp / ".git" / "non-esiste.jsonl", sid="p5")
    step("prompt: trascrizione assente, passa senza errori",
         r.returncode == 0 and not r.stdout.strip(), r.stderr[-300:])
    cfg_p.write_text(cfg_attuale, encoding="utf-8")

    # L'avviso dell'handoff: a soglia, una volta per sessione, insieme a quello di
    # ripresa se scattano insieme; spento a 0.
    r = prompt_hook(transcript("t-hand.jsonl", 0.2, 200_000), sid="h1")
    step("prompt: oltre handoff_warn_tokens ferma e indica /keep-fresh:handoff",
         r.returncode == 0 and blocked(r) and "/keep-fresh:handoff" in r.stdout
         and "200.000" in r.stdout and "Pausa" not in r.stdout, r.stdout[-500:])
    r = prompt_hook(tmp / ".git" / "t-hand.jsonl", sid="h1")
    step("prompt: reinviato, nella stessa sessione, passa",
         r.returncode == 0 and not r.stdout.strip(), r.stdout[-300:])
    r = prompt_hook(tmp / ".git" / "t-hand.jsonl", sid="h2")
    step("prompt: una sessione nuova viene avvisata di nuovo",
         r.returncode == 0 and blocked(r), r.stdout[-300:])
    r = prompt_hook(tmp / ".git" / "t-hand.jsonl", "/keep-fresh:handoff", sid="h3")
    step("prompt: /keep-fresh:handoff passa sempre, anche sopra la soglia",
         r.returncode == 0 and not r.stdout.strip(), r.stdout[-300:])
    notifica = ("<task-notification>\n<task-id>abc</task-id>\n<status>completed</status>\n"
                "<result>fatto</result>\n</task-notification>")
    r = prompt_hook(tmp / ".git" / "t-hand.jsonl", notifica, sid="h8")
    step("prompt: il risultato di un sotto-agente (<task-notification>) passa sempre",
         r.returncode == 0 and not r.stdout.strip(), r.stdout[-300:])
    r = prompt_hook(tmp / ".git" / "t-hand.jsonl", sid="h8")
    step("prompt: la notifica lasciata passare non consuma l'avviso dell'utente",
         r.returncode == 0 and blocked(r), r.stdout[-300:])
    r = prompt_hook(tmp / ".git" / "t-hand.jsonl", "<b>grassetto</b> continua", sid="h9")
    step("prompt: un testo che inizia con un tag senza trattino si ferma come gli altri",
         r.returncode == 0 and blocked(r), r.stdout[-300:])
    r = prompt_hook(transcript("t-hand-small.jsonl", 0.2, 100_000), sid="h4")
    step("prompt: sotto la soglia dell'handoff non ferma",
         r.returncode == 0 and not r.stdout.strip(), r.stdout[-300:])
    r = prompt_hook(transcript("t-hand-both.jsonl", 3, 200_000), sid="h5")
    step("prompt: pausa lunga e contesto grande: un solo messaggio che dice entrambe",
         r.returncode == 0 and blocked(r) and "Pausa" in r.stdout
         and "/keep-fresh:handoff" in r.stdout, r.stdout[-600:])
    r = prompt_hook(tmp / ".git" / "t-hand-both.jsonl", sid="h5")
    step("prompt: reinviato, passa: entrambi i marcatori sono stati scritti",
         r.returncode == 0 and not r.stdout.strip(), r.stdout[-300:])
    cfg_p.write_text(cfg_attuale.replace("# handoff_warn_tokens = 150000",
                                         "handoff_warn_tokens = 0"), encoding="utf-8")
    r = prompt_hook(tmp / ".git" / "t-hand.jsonl", sid="h6")
    step("prompt: handoff_warn_tokens = 0 spegne l'avviso",
         r.returncode == 0 and not r.stdout.strip(), r.stdout[-300:])
    cfg_p.write_text(cfg_attuale.replace("# handoff_warn_tokens = 150000",
                                         "handoff_warn_tokens = 300000"), encoding="utf-8")
    r = prompt_hook(tmp / ".git" / "t-hand.jsonl", sid="h7")
    step("prompt: una soglia piu' alta di quella che c'e' in config si rispetta",
         r.returncode == 0 and not r.stdout.strip(), r.stdout[-300:])
    cfg_p.write_text(cfg_attuale, encoding="utf-8")

    # Senza session_id l'avviso dell'handoff non puo' essere "una volta in assoluto":
    # il marcatore si lega alla trascrizione, che e' per sessione.
    ta = transcript("t-nosid-a.jsonl", 0.2, 200_000)
    tb = transcript("t-nosid-b.jsonl", 0.2, 200_000)
    ra1 = prompt_hook(ta, sid="")
    ra2 = prompt_hook(ta, sid="")
    rb1 = prompt_hook(tb, sid="")
    step("prompt: senza session_id l'avviso dell'handoff e' una volta per trascrizione",
         blocked(ra1) and not ra2.stdout.strip() and blocked(rb1),
         f"{ra1.stdout[-200:]}|{ra2.stdout[-200:]}|{rb1.stdout[-200:]}")

    # Gli handoff: la coda in .git/keep-fresh-handoff/, un file ciascuno. Ogni blocco
    # riparte da una cartella vuota, cosi' non dipendono l'uno dall'altro.
    hdir = tmp / ".git" / "keep-fresh-handoff"

    def hand(*args):
        return run(sys.executable, HANDOFF_SCRIPT, *args)

    def reset_handoff():
        shutil.rmtree(hdir, ignore_errors=True)

    def handoffs():
        return sorted(hdir.glob("*.md")) if hdir.is_dir() else []

    def riempi(path, corpo="## Prossimo passo\nfinire il test\n"):
        t = path.read_text(encoding="utf-8")
        path.write_text(re.sub(r"<!-- handoff-vuoto:.*?-->", lambda _: corpo, t),
                        encoding="utf-8", newline="\n")

    def retrodata(path, ore):
        t = path.read_text(encoding="utf-8")
        quando = (_dt.now(_tz.utc) - _td(hours=ore)).astimezone().isoformat(
            timespec="seconds")
        path.write_text(re.sub(r"^creato: .*$", lambda _: f"creato: {quando}", t,
                               count=1, flags=re.M), encoding="utf-8", newline="\n")

    reset_handoff()
    r = hand("list")
    step("handoff: senza handoff, list dice 0 aperti ed esce 0",
         r.returncode == 0 and "Handoff aperti: 0" in r.stdout,
         f"exit {r.returncode}: {r.stdout[-300:]}{r.stderr[-300:]}")
    r = hand("new", "--title", "Migrazione layout: manca il test su macOS")
    fs = handoffs()
    step("handoff: new crea il file e ne stampa il percorso",
         r.returncode == 0 and len(fs) == 1 and fs[0].name in r.stdout
         and fs[0].name.endswith("-migrazione-layout-manca-il-test-su-macos.md"),
         f"{r.stdout[-300:]}{r.stderr[-300:]} {[f.name for f in fs]}")
    meta = fs[0].read_text(encoding="utf-8") if fs else ""
    step("handoff: i metadati hanno titolo, data, branch, HEAD e stato aperto",
         all(k in meta for k in ("titolo: Migrazione layout: manca il test su macOS",
                                 "creato: ", "branch: ", "head: ", "stato: aperto")),
         meta[:300])
    r = hand("list")
    step("handoff: list lo mostra numerato e lo segna vuoto finche' il corpo non e' scritto",
         r.returncode == 0 and "Handoff aperti: 1" in r.stdout and " 1. " in r.stdout
         and "Migrazione layout" in r.stdout and "(vuoto)" in r.stdout, r.stdout[-300:])
    step("handoff: sullo stesso branch e con lo stesso HEAD non ci sono altre etichette",
         "altro branch" not in r.stdout and "HEAD non" not in r.stdout, r.stdout[-300:])
    if fs:
        riempi(fs[0])
    r = hand("list")
    step("handoff: scritto il corpo, il segno vuoto sparisce",
         "Handoff aperti: 1" in r.stdout and "vuoto" not in r.stdout, r.stdout[-300:])

    reset_handoff()
    hand("new", "--title", "Verifica perché già fatta")
    hand("new", "--title", "riga uno\nriga due")
    r = hand("new", "--title", "   ")
    names = [f.name for f in handoffs()]
    step("handoff: gli accenti escono dal nome del file e il titolo resta una riga sola",
         any(n.endswith("-verifica-perche-gia-fatta.md") for n in names)
         and any("titolo: riga uno riga due" in f.read_text(encoding="utf-8")
                 for f in handoffs()), f"{names}")
    step("handoff: un titolo vuoto e' rifiutato e non crea niente",
         r.returncode == 1 and len(names) == 2,
         f"exit {r.returncode}: {r.stdout}{r.stderr} {names}")
    hand("new", "--title", "Doppio")
    hand("new", "--title", "Doppio")
    step("handoff: lo stesso titolo nello stesso minuto non sovrascrive",
         len([f for f in handoffs() if "doppio" in f.name]) == 2,
         f"{[f.name for f in handoffs()]}")

    reset_handoff()
    hand("new", "--title", "Primo")
    for vecchio in handoffs()[:1]:
        riempi(vecchio)
        retrodata(vecchio, 72)
    r = hand("list")
    step("handoff: oltre handoff_ore (48) non compare fra gli aperti",
         r.returncode == 0 and "Handoff aperti: 0" in r.stdout and "Primo" not in r.stdout,
         r.stdout[-300:])
    r = hand("list", "--all")
    step("handoff: list --all lo mostra come scaduto",
         "scaduto" in r.stdout and "Primo" in r.stdout, r.stdout[-300:])
    hdir.mkdir(exist_ok=True)
    (hdir / "rotto.md").write_text("niente intestazione\n", encoding="utf-8")
    hand("new", "--title", "Buono")
    r = hand("list")
    step("handoff: un file illeggibile e' segnalato e ignorato, gli altri restano",
         r.returncode == 0 and "rotto.md" in r.stdout and "Handoff aperti: 1" in r.stdout
         and "Buono" in r.stdout, f"exit {r.returncode}: {r.stdout[-400:]}{r.stderr[-300:]}")

    vuoto = Path(tempfile.mkdtemp(prefix="agent-context-vuoto-"))
    try:
        subprocess.run(["git", "init", "-q", "."], cwd=str(vuoto), env=env, check=True)
        r = subprocess.run([sys.executable, str(HANDOFF_SCRIPT), "new", "--title",
                            "Primo giorno"], cwd=str(vuoto), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=env)
        vf = list((vuoto / ".git" / "keep-fresh-handoff").glob("*.md"))
        step("handoff: in un repository senza commit new funziona e scrive head: -",
             r.returncode == 0 and len(vf) == 1
             and "head: -" in vf[0].read_text(encoding="utf-8"),
             f"exit {r.returncode}: {r.stdout[-300:]}{r.stderr[-300:]}")
    finally:
        shutil.rmtree(vuoto, ignore_errors=True)
    reset_handoff()

    # resume, discard, prune. I titoli distinti permettono di sceglierli per parola;
    # la numerazione si prova dopo aver messo Alfa piu' indietro nel tempo, perche'
    # l'ordine di due file creati nello stesso secondo non sarebbe deterministico.
    reset_handoff()
    hand("new", "--title", "Alfa: lavoro sul layout")
    hand("new", "--title", "Beta: lavoro sugli hook")
    alfa = next((f for f in handoffs() if "alfa" in f.name), hdir / "assente.md")
    beta = next((f for f in handoffs() if "beta" in f.name), hdir / "assente.md")
    if alfa.exists() and beta.exists():
        riempi(alfa, "## Prossimo passo\ntesto-di-alfa\n")
        riempi(beta, "## Prossimo passo\ntesto-di-beta\n")
        retrodata(alfa, 5)
    r = hand("resume")
    step("handoff: resume senza argomento e con due aperti elenca e non consuma",
         r.returncode == 1 and "Piu' di un handoff" in r.stdout
         and "Alfa" in r.stdout and "Beta" in r.stdout
         and alfa.exists() and "stato: aperto" in alfa.read_text(encoding="utf-8")
         and beta.exists() and "stato: aperto" in beta.read_text(encoding="utf-8"),
         f"exit {r.returncode}: {r.stdout[-400:]}{r.stderr[-300:]}")
    r = hand("resume", "lavoro")
    step("handoff: una parola che sta in due titoli elenca e non consuma",
         r.returncode == 1 and "Alfa" in r.stdout and "Beta" in r.stdout
         and alfa.exists() and "stato: aperto" in alfa.read_text(encoding="utf-8"),
         f"exit {r.returncode}: {r.stdout[-400:]}{r.stderr[-300:]}")
    r = hand("resume", "beta")
    step("handoff: resume per parola stampa il corpo e passa a ripreso",
         r.returncode == 0 and "testo-di-beta" in r.stdout
         and "testo-di-alfa" not in r.stdout
         and beta.exists() and "stato: ripreso" in beta.read_text(encoding="utf-8"),
         f"exit {r.returncode}: {r.stdout[-400:]}{r.stderr[-300:]}")
    r = hand("resume", "beta")
    step("handoff: un handoff ripreso non si riprende da solo una seconda volta",
         r.returncode == 1 and "Nessun handoff aperto" in r.stdout, r.stdout[-300:])
    r = hand("list")
    step("handoff: dopo resume resta solo l'altro", "Handoff aperti: 1" in r.stdout
         and "Alfa" in r.stdout and "Beta" not in r.stdout, r.stdout[-300:])
    r = hand("resume")
    step("handoff: con un solo aperto resume senza argomento lo prende",
         r.returncode == 0 and "testo-di-alfa" in r.stdout, r.stdout[-300:])

    reset_handoff()
    hand("new", "--title", "Gamma uno")
    hand("new", "--title", "Delta due")
    gamma = next((f for f in handoffs() if "gamma" in f.name), hdir / "assente.md")
    delta = next((f for f in handoffs() if "delta" in f.name), hdir / "assente.md")
    if gamma.exists() and delta.exists():
        riempi(gamma, "testo-di-gamma\n")
        riempi(delta, "testo-di-delta\n")
        retrodata(gamma, 5)
    r = hand("resume", "2")
    step("handoff: resume N prende il numero dell'elenco (il piu' recente e' 1)",
         r.returncode == 0 and "testo-di-gamma" in r.stdout, r.stdout[-300:])
    r = hand("resume", "9")
    step("handoff: un numero fuori elenco e' un errore che non consuma niente",
         r.returncode == 1 and delta.exists()
         and "stato: aperto" in delta.read_text(encoding="utf-8"), r.stdout[-300:])
    r = hand("discard", "delta")
    step("handoff: discard segna scartato e lo toglie dall'elenco",
         r.returncode == 0 and delta.exists()
         and "stato: scartato" in delta.read_text(encoding="utf-8")
         and "Handoff aperti: 0" in hand("list").stdout, r.stdout[-300:])

    reset_handoff()
    hand("new", "--title", "Senza corpo")
    r = hand("resume")
    step("handoff: resume di un corpo mai scritto avverte",
         r.returncode == 0 and "corpo non e' stato scritto" in r.stdout, r.stdout[-300:])

    # La pulizia conta dall'ultima modifica del file. Un aperto e non scaduto non si
    # tocca mai, per vecchia che sia la sua ultima modifica.
    reset_handoff()
    for t in ("Chiuso vecchio", "Chiuso recente", "Aperto vivo", "Scaduto vecchio"):
        hand("new", "--title", t)
    f_cv = next((f for f in handoffs() if "chiuso-vecchio" in f.name), hdir / "assente.md")
    f_cr = next((f for f in handoffs() if "chiuso-recente" in f.name), hdir / "assente.md")
    f_av = next((f for f in handoffs() if "aperto-vivo" in f.name), hdir / "assente.md")
    f_sv = next((f for f in handoffs() if "scaduto-vecchio" in f.name), hdir / "assente.md")
    if all(f.exists() for f in (f_cv, f_cr, f_av, f_sv)):
        hand("discard", "chiuso vecchio")
        hand("discard", "chiuso recente")
        retrodata(f_sv, 24 * 60)
        quaranta = (_dt.now() - _td(days=40)).timestamp()
        for f in (f_cv, f_av, f_sv):
            os.utime(f, (quaranta, quaranta))
    r = hand("prune")
    left = {f.name for f in handoffs()}
    step("handoff: prune toglie i chiusi e gli scaduti vecchi, non gli altri",
         r.returncode == 0 and f_cv.name not in left and f_sv.name not in left
         and f_cr.name in left and f_av.name in left, f"{r.stdout[-300:]} {left}")

    # Un handoff di un altro branch, o con un HEAD che non e' nel tuo storico, non si
    # riprende senza saperlo: resume dice perche' ed esce 1 senza consumarlo.
    base = run("git", "symbolic-ref", "--short", "HEAD").stdout.strip()
    reset_handoff()
    hand("new", "--title", "Su base")
    su_base = next(iter(handoffs()), hdir / "assente.md")
    if su_base.exists():
        riempi(su_base, "testo-su-base\n")
    run("git", "checkout", "-q", "-b", "altro")
    r = hand("list")
    step("handoff: list segna l'handoff di un altro branch",
         "altro branch" in r.stdout and "HEAD non" not in r.stdout, r.stdout[-300:])
    r = hand("resume", "base")
    step("handoff: resume su un altro branch avverte, esce 1 e non consuma",
         r.returncode == 1 and "ATTENZIONE" in r.stdout and "altro branch" in r.stdout
         and "testo-su-base" not in r.stdout and su_base.exists()
         and "stato: aperto" in su_base.read_text(encoding="utf-8"), r.stdout[-400:])
    r = hand("resume", "base", "--comunque")
    step("handoff: resume --comunque lo riprende lo stesso",
         r.returncode == 0 and "testo-su-base" in r.stdout and su_base.exists()
         and "stato: ripreso" in su_base.read_text(encoding="utf-8"), r.stdout[-400:])
    run("git", "commit", "-q", "--allow-empty", "-m", "commit su altro")
    hand("new", "--title", "Su altro")
    run("git", "checkout", "-q", base)
    r = hand("list")
    step("handoff: un HEAD che non e' nel tuo storico viene segnalato",
         "HEAD non nel tuo storico" in r.stdout and "altro branch" in r.stdout,
         r.stdout[-300:])
    run("git", "branch", "-q", "-D", "altro")
    reset_handoff()
    hand("new", "--title", "Stesso branch")
    run("git", "commit", "-q", "--allow-empty", "-m", "commit avanti")
    r = hand("list")
    step("handoff: sullo stesso branch un HEAD piu' avanti non e' una discordanza",
         "Stesso branch" in r.stdout and "altro branch" not in r.stdout
         and "HEAD non" not in r.stdout, r.stdout[-300:])
    reset_handoff()

    # L'indice all'avvio: poche righe, solo se c'e' qualcosa, mai quando il contesto
    # c'e' gia' (resume, compact).
    def avvio(source=None):
        data = {} if source is None else {"source": source}
        return run(sys.executable, HOOKS_SCRIPT, "session-start", "--agent", "prova",
                   stdin=json.dumps(data))

    reset_handoff()
    r = avvio("startup")
    step("handoff: senza handoff l'avvio non aggiunge niente",
         r.returncode == 0 and "Handoff aperti" not in r.stdout
         and "Stato del progetto" in r.stdout, r.stdout[-300:])
    hand("new", "--title", "Uno")
    for f in handoffs()[:1]:
        riempi(f)
    for src in ("startup", "clear", None, "boh"):
        r = avvio(src)
        step(f"handoff: all'avvio con source={src!r} l'indice c'e', dopo lo stato",
             r.returncode == 0 and "Handoff aperti" in r.stdout and "Uno" in r.stdout
             and "Stato del progetto" in r.stdout
             and r.stdout.index("Stato del progetto") < r.stdout.index("Handoff aperti"),
             f"exit {r.returncode}: {r.stdout[-400:]}")
    for src in ("resume", "compact"):
        r = avvio(src)
        step(f"handoff: con source={src!r} l'indice non c'e'",
             r.returncode == 0 and "Handoff aperti" not in r.stdout, r.stdout[-300:])
    agent_log = (tmp / ".git" / "agent-hooks.log").read_text(encoding="utf-8")
    step("handoff: la traccia degli hook registra l'indice, e la riga dell'iniezione resta com'era",
         "handoff: indice di 1 voce" in agent_log
         and re.search(r"SessionStart\s+iniettati \d+ caratteri", agent_log),
         agent_log[-500:])

    reset_handoff()
    for i in range(7):
        hand("new", "--title", f"Voce {i}")
    r = avvio("startup")
    numerate = [l for l in r.stdout.splitlines() if re.match(r"\s*\d+\. ", l)]
    step("handoff: l'indice mostra al massimo 5 righe e dice quanti altri",
         len(numerate) == 5 and "+2 altri" in r.stdout and "--elenco" in r.stdout,
         f"{len(numerate)} righe: {r.stdout[-500:]}")

    reset_handoff()
    hand("new", "--title", "Sano")
    hdir.mkdir(exist_ok=True)
    (hdir / "rotto.md").write_text("---\ntitolo\n---\n", encoding="utf-8")
    r = avvio("startup")
    step("handoff: un file rotto non ferma l'avvio e non nasconde gli altri",
         r.returncode == 0 and "Sano" in r.stdout and "Stato del progetto" in r.stdout,
         f"exit {r.returncode}: {r.stdout[-300:]}{r.stderr[-300:]}")

    reset_handoff()
    hand("new", "--title", "Chiuso da tempo")
    hand("new", "--title", "Ancora aperto")
    vecchio = next((f for f in handoffs() if "chiuso-da-tempo" in f.name),
                   hdir / "assente.md")
    if vecchio.exists():
        hand("discard", "chiuso da tempo")
        quaranta = (_dt.now() - _td(days=40)).timestamp()
        os.utime(vecchio, (quaranta, quaranta))
    avvio("startup")
    step("handoff: l'avvio pulisce i chiusi da piu' di 30 giorni e lascia gli altri",
         not vecchio.exists() and len(handoffs()) == 1, f"{[f.name for f in handoffs()]}")
    reset_handoff()

    # Il comando che resume suggerisce per --comunque deve funzionare sempre: i titoli
    # possono avere virgolette, essere solo cifre o stare dentro un altro titolo.
    base = run("git", "symbolic-ref", "--short", "HEAD").stdout.strip()
    reset_handoff()
    titoli = ("Fix", "Fix test", "42", 'Disse "ciao"')
    for t in titoli:
        hand("new", "--title", t)
    for f in handoffs():
        riempi(f, f"testo-{f.stem}\n")
    run("git", "checkout", "-q", "-b", "altro2")
    for t in titoli:
        r = hand("resume", "1")
        m = re.search(r"resume (\S+) --comunque", r.stdout)
        r2 = hand("resume", m.group(1), "--comunque") if m else r
        step(f"handoff: il comando suggerito per --comunque funziona (titolo {t!r})",
             r.returncode == 1 and bool(m) and r2.returncode == 0
             and f"testo-{m.group(1)}" in r2.stdout,
             f"{r.stdout[-300:]}|{r2.stdout[-200:]}{r2.stderr[-200:]}")
    r = hand("list", "--all")
    step("handoff: i quattro suggeriti sono stati ripresi, ciascuno una volta",
         r.stdout.count("ripreso") == 4, r.stdout[-400:])
    run("git", "checkout", "-q", base)
    run("git", "branch", "-q", "-D", "altro2")
    reset_handoff()

    # set_state tocca la riga di stato dell'intestazione, anche se rientrata, e non una
    # riga uguale nel corpo.
    hand("new", "--title", "Ritoccato a mano")
    for f in handoffs()[:1]:
        t = f.read_text(encoding="utf-8")
        t = t.replace("stato: aperto\n---\n", "  stato: aperto\n---\n", 1)
        f.write_text(t + "\nstato: finto\n", encoding="utf-8", newline="\n")
    r = hand("resume")
    testo = next(iter(handoffs()), hdir / "assente.md").read_text(encoding="utf-8")
    step("handoff: resume cambia lo stato nell'intestazione, non una riga uguale nel corpo",
         r.returncode == 0
         and re.search(r"^[ \t]*stato: ripreso$", testo.split("\n---\n")[0], re.M)
         and "\nstato: finto" in testo, f"exit {r.returncode}: {r.stdout[-200:]} {testo[:300]}")
    reset_handoff()

    # Un handoff ritoccato dalla shell di Windows: Set-Content -Encoding utf8 mette il
    # BOM, Out-File di PowerShell 5.1 scrive UTF-16. Non devono sparire in silenzio.
    reset_handoff()
    hand("new", "--title", "Con BOM")
    hand("new", "--title", "Come PowerShell")
    f_bom = next((f for f in handoffs() if "con-bom" in f.name), hdir / "assente.md")
    f_ps = next((f for f in handoffs() if "come-powershell" in f.name),
                hdir / "assente.md")
    if f_bom.exists() and f_ps.exists():
        f_bom.write_bytes(b"\xef\xbb\xbf" + f_bom.read_bytes())
        f_ps.write_bytes(f_ps.read_text(encoding="utf-8").encode("utf-16"))
    r = hand("list")
    step("handoff: un file con BOM UTF-8 o in UTF-16 resta nell'elenco, non e' segnato rotto",
         "Handoff aperti: 2" in r.stdout and "ignorato" not in r.stdout
         and "Con BOM" in r.stdout and "Come PowerShell" in r.stdout,
         f"{r.stdout[-500:]}{r.stderr[-300:]}")
    r1 = hand("resume", "bom")
    r2 = hand("resume", "powershell")
    r3 = hand("list", "--all")
    step("handoff: resume su BOM e UTF-16 funziona e li segna ripresi",
         r1.returncode == 0 and r2.returncode == 0
         and r3.stdout.count("ripreso") == 2 and "ignorato" not in r3.stdout,
         f"{r1.stdout[-200:]}{r1.stderr[-200:]}{r2.stderr[-200:]}{r3.stdout[-300:]}")
    reset_handoff()

    step("nessun __pycache__ lasciato nel repository",
         not any(tmp.rglob("__pycache__")))


# ------------------------------------------------- silenzio fuori da keep-fresh, passo ceduto

def fake_transcript(where: Path, hours_ago: float, ctx: int) -> Path:
    """Una trascrizione di Claude Code con l'ultimo messaggio di `hours_ago` ore fa."""
    from datetime import datetime, timedelta, timezone
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    row = {"timestamp": ts.replace("+00:00", "Z"), "type": "assistant", "message": {
        "id": "m", "model": "claude-opus-5-5", "content": [], "usage": {
            "input_tokens": 2, "cache_creation_input_tokens": 1000,
            "cache_creation": {"ephemeral_1h_input_tokens": 1000},
            "cache_read_input_tokens": ctx - 1002, "output_tokens": 5}}}
    p = where / "t.jsonl"
    p.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return p


def all_hooks(cwd: Path, tp: Path):
    """I tre eventi, con un turno che avrebbe motivo di bloccare e un contesto grande."""
    out = []
    for ev, stdin in (("session-start", '{"source":"startup"}'),
                      ("stop", '{"session_id":"q1"}'),
                      ("prompt", json.dumps({"session_id": "q1", "transcript_path": str(tp),
                                             "prompt": "continua"}))):
        out.append(run(sys.executable, HOOKS_SCRIPT, ev, "--agent", "prova",
                       cwd=cwd, stdin=stdin))
    return out


def test_quiet_and_yield():
    tp = fake_transcript(tmpdir(), 3, 200_000)

    root = git_repo(with_config=False)
    (root / "core.py").write_text("x = 1\n", encoding="utf-8")
    rs = all_hooks(root, tp)
    step("fuori da keep-fresh: nessun hook stampa o scrive",
         all(r.returncode == 0 and not r.stdout.strip() for r in rs)
         and not (root / ".git" / "agent-hooks.log").exists(),
         " | ".join(r.stdout[-150:] for r in rs))

    plain = tmpdir()
    rs = all_hooks(plain, tp)
    step("fuori da un repository: nessun hook stampa o scrive",
         all(r.returncode == 0 and not r.stdout.strip() for r in rs)
         and not any(plain.iterdir()), " | ".join(r.stdout[-150:] for r in rs))

    root = new_project()
    old = root / ".keep-fresh" / "scripts"
    old.mkdir()
    (old / "agent_hooks.py").write_text("# il vecchio impianto\n", encoding="utf-8")
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.local.json").write_text(json.dumps({"hooks": {"Stop": [
        {"hooks": [{"type": "command", "command": "python .keep-fresh/scripts/agent_hooks.py stop"}]}
    ]}}), encoding="utf-8")
    (root / "core.py").write_text("x = 1\n", encoding="utf-8")
    r = run(sys.executable, HOOKS_SCRIPT, "stop", "--agent", "claude", cwd=root,
            stdin='{"session_id":"y1"}')
    step("vecchio impianto presente: l'hook del plugin cede il passo",
         r.returncode == 0 and not r.stdout.strip()
         and "ceduto al vecchio impianto" in hook_log(root), f"{r.stdout[-300:]} | {hook_log(root)}")


def test_injection_names_lint():
    root = new_project()
    r = run(sys.executable, HOOKS_SCRIPT, "session-start", "--agent", "prova", cwd=root,
            stdin='{"source":"startup"}')
    m = re.search(r'"([^"]*docs_lint\.py)"', r.stdout)
    step("l'iniezione indica il lint con un percorso che esiste",
         m is not None and Path(m.group(1)).is_file() and str(SCRIPTS) in r.stdout,
         r.stdout[-300:])


# ------------------------------------------------------------------------------ kf_init

INIT_SCRIPT = SCRIPTS / "kf_init.py"


def snapshot(root: Path) -> dict:
    """Percorso, dimensione e data di ogni file, .git compreso: per provare la sola lettura."""
    out = {}
    for q in root.rglob("*"):
        if q.is_file():
            st = q.stat()
            out[q.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns)
    return out


def changed(before: dict, root: Path) -> list:
    after = snapshot(root)
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def fake_home(installed: dict) -> dict:
    """
    Una cartella home finta con le configurazioni di Claude Code date: {nome cartella:
    versione installata o None}. Ritorna l'ambiente da usare.
    """
    home = tmpdir("kf-home-")
    for name, version in installed.items():
        cfg = home / name
        (cfg / "plugins").mkdir(parents=True)
        plugins = {} if version is None else {
            "keep-fresh@keep-fresh": [{"scope": "user", "version": version}]}
        (cfg / "plugins" / "installed_plugins.json").write_text(
            json.dumps({"version": 2, "plugins": plugins}), encoding="utf-8")
        enabled = {} if version is None else {"keep-fresh@keep-fresh": True}
        (cfg / "settings.json").write_text(json.dumps({"enabledPlugins": enabled}),
                                           encoding="utf-8")
    env = dict(ENV, HOME=str(home), USERPROFILE=str(home))
    for k in ("CODEX_HOME", "CLAUDE_CONFIG_DIR"):
        env.pop(k, None)
    return env


def test_kf_init():
    root = git_repo(with_config=False)
    r = run(sys.executable, INIT_SCRIPT, cwd=root)
    step("repo vuoto: l'inizializzatore esce 0", r.returncode == 0, r.stderr[-600:])
    step("init non scrive script ne' agganci",
         (root / CONFIG_FILE).is_file() and (root / STATUS_FILE).is_file()
         and not any((root / p).exists() for p in (
             ".keep-fresh/scripts", ".keep-fresh/guide.md", ".keep-fresh/version.json",
             ".claude/settings.local.json", ".codex/hooks.json")),
         str(sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                    if ".git" not in p.parts)))
    guide = PLUGIN / "guide.md"
    step("il prompt indica la guida nel plugin",
         str(guide) in r.stdout and guide.is_file(), r.stdout[-600:])

    run("git", "add", "-A", cwd=root)
    run("git", "commit", "-q", "-m", "init", cwd=root)
    run(sys.executable, INIT_SCRIPT, cwd=root)
    status_text = (root / STATUS_FILE).read_text(encoding="utf-8")
    step("dopo il primo commit: marcatore aggiunto allo scheletro",
         "context-verified-at:" in status_text, status_text[:300])
    run("git", "add", "-A", cwd=root)
    run("git", "commit", "-q", "-m", "marcatore", cwd=root)
    r = run(sys.executable, LINT_SCRIPT, cwd=root)
    step("progetto inizializzato: il lint esce 0", r.returncode == 0, _lint_lines(r.stdout))

    (root / CONFIG_FILE).write_text("# mia taratura\n", encoding="utf-8")
    (root / STATUS_FILE).write_text("# mio stato\n", encoding="utf-8")
    run(sys.executable, INIT_SCRIPT, cwd=root)
    step("init rilanciato non tocca config.toml ne' status.md scritti a mano",
         (root / CONFIG_FILE).read_text(encoding="utf-8") == "# mia taratura\n"
         and (root / STATUS_FILE).read_text(encoding="utf-8") == "# mio stato\n")
    run("git", "checkout", "-q", "--", ".", cwd=root)

    env = fake_home({".claude": "1.0.0", ".claude-x": None})
    run(sys.executable, HANDOFF_SCRIPT, "new", "--title", "Per lo stato", cwd=root)
    hdir = root / ".git" / "keep-fresh-handoff"
    (hdir / "rotto.md").write_text("niente intestazione\n", encoding="utf-8")
    before = snapshot(root)
    r = run(sys.executable, INIT_SCRIPT, "--status", cwd=root, env=env)
    step("--status riporta gli handoff aperti",
         "Handoff aperti: 1" in r.stdout, r.stdout[-700:])
    step("--status mette i file illeggibili fra le cose da sistemare",
         r.stdout.count("rotto.md") >= 2 and "da sistemare" in r.stdout, r.stdout[-900:])
    step("--status e' di sola lettura: nessun file cambia, .git compreso",
         not changed(before, root), str(changed(before, root)))
    lines = r.stdout.splitlines()
    claude_line = next((l for l in lines if l.rstrip().endswith(os.sep + ".claude")), "")
    other_line = next((l for l in lines if l.rstrip().endswith(".claude-x")), "")
    step("--status dice dove il plugin e' installato",
         "1.0.0" in claude_line and "non installato" in other_line, r.stdout[-900:])
    shutil.rmtree(hdir)

    (root / "tools").mkdir()
    (root / "tools" / "agent_context_init.py").write_text("# copia\n", encoding="utf-8")
    run("git", "add", "-A", cwd=root)
    r = run(sys.executable, INIT_SCRIPT, "--status", cwd=root, env=env)
    step("la copia vecchia dell'inizializzatore viene segnalata",
         "tools/agent_context_init.py" in r.stdout, r.stdout[-600:])

    old = root / ".keep-fresh" / "scripts"
    old.mkdir()
    (old / "agent_hooks.py").write_text("# vecchio\n", encoding="utf-8")
    r = run(sys.executable, INIT_SCRIPT, "--status", cwd=root, env=env)
    step("--status con il vecchio impianto: lo dice e indica /keep-fresh:migrate, esce 1",
         r.returncode == 1 and "/keep-fresh:migrate" in r.stdout, r.stdout[-600:])


# ------------------------------------------------------------------------------ migrate

MIGRATE_SCRIPT = SCRIPTS / "migrate.py"
OLD_BOOT = ("python -c \"import runpy,subprocess,sys;r=subprocess.run(['git','rev-parse',"
            "'--show-toplevel'],capture_output=True,text=True).stdout.strip();r and "
            "runpy.run_path(r+'/.keep-fresh/scripts/agent_hooks.py',run_name='__main__')\"")
DOC_OLD = """# Agenti

Prima di chiudere: `python .keep-fresh/scripts/docs_lint.py`.
Gli handoff: `python .keep-fresh/scripts/handoff.py list`, oppure /keep-fresh handoff.
Il blocco del prompt sta in `.keep-fresh/scripts/agent_hooks.py:205-249`.
"""


def old_project(parent: Path, rel: str) -> Path:
    """Un progetto col vecchio impianto, tutto committato, come lo lasciava agent_context_init."""
    root = parent / rel
    root.mkdir(parents=True)
    run("git", "init", "-q", ".", cwd=root)
    kf = root / ".keep-fresh"
    (kf / "scripts").mkdir(parents=True)
    shutil.copyfile(PLUGIN / "templates" / "config.toml", kf / "config.toml")
    (kf / "scripts" / "agent_hooks.py").write_text("# vecchio\n", encoding="utf-8")
    (kf / "guide.md").write_text("# guida vecchia\n", encoding="utf-8")
    (kf / "version.json").write_text("{}\n", encoding="utf-8")
    ev = [("SessionStart", "session-start"), ("Stop", "stop"), ("UserPromptSubmit", "prompt")]
    ours = lambda agent: {e: [{"hooks": [{"type": "command", "timeout": 20,
                                          "command": f"{OLD_BOOT} {a} --agent {agent}"}]}]
                          for e, a in ev}
    claude = {"permissions": {"allow": ["Bash(git:*)"]},
              "hooks": dict(ours("claude"), PreToolUse=[{"matcher": "Bash", "hooks": [
                  {"type": "command", "command": "python altro.py"}]}])}
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.local.json").write_text(json.dumps(claude, indent=2),
                                                          encoding="utf-8")
    (root / ".codex").mkdir()
    (root / ".codex" / "hooks.json").write_text(json.dumps({"hooks": ours("codex")}, indent=2),
                                                encoding="utf-8")
    (root / ".gitignore").write_text("build/\n.claude/settings.local.json\n.codex/hooks.json\n",
                                     encoding="utf-8")
    (root / "AGENTS.md").write_text(DOC_OLD, encoding="utf-8")
    st = root / STATUS_FILE
    st.parent.mkdir(parents=True)
    st.write_text("# Stato\n\nLint: `python .keep-fresh/scripts/docs_lint.py`\n", encoding="utf-8")
    (root / "core.py").write_text("x = 1\n", encoding="utf-8")
    run("git", "add", "-A", "-f", cwd=root)
    run("git", "rm", "-q", "--cached", ".claude/settings.local.json", ".codex/hooks.json",
        cwd=root)
    run("git", "commit", "-q", "-m", "progetto", cwd=root)
    hd = root / ".git" / "keep-fresh-handoff"
    hd.mkdir()
    (hd / "20261020-1140-prova.md").write_text("cita .keep-fresh/scripts/handoff.py\n",
                                               encoding="utf-8")
    return root


def migrate(root: Path, *args):
    return run(sys.executable, MIGRATE_SCRIPT, "--root", root, *args, cwd=root,
               env=fake_home({".claude": "1.0.0"}))


def test_migrate():
    sys.path.insert(0, str(SCRIPTS))
    import migrate as mig

    base = tmpdir("kf-projects-")
    a = old_project(base, "alfa")
    b = old_project(base, "clienti/progetto/beta")
    (base / "qualunque").mkdir()
    fake_kf = base / "keep_fresh" / "plugins" / "keep-fresh" / ".claude-plugin"
    fake_kf.mkdir(parents=True)
    (fake_kf / "plugin.json").write_text("{}", encoding="utf-8")
    (base / "keep_fresh" / ".keep-fresh").mkdir()
    (base / "keep_fresh" / ".keep-fresh" / "config.toml").write_text("", encoding="utf-8")
    found = sorted(p.relative_to(base).as_posix() for p in mig.find_projects(base))
    step("migrate: trova i progetti e salta il repo di keep-fresh",
         found == ["alfa", "clienti/progetto/beta"], str(found))

    before = snapshot(base)
    r = migrate(base)
    step("migrate a vuoto non scrive niente", not changed(before, base),
         str(changed(before, base)[:8]))
    step("migrate a vuoto elenca rimozioni, agganci e riscritture",
         r.returncode == 0 and "togli .keep-fresh/scripts" in r.stdout
         and "tolti 3 hook di keep-fresh" in r.stdout and "/keep-fresh:lint" in r.stdout,
         r.stdout[-900:])

    r = migrate(base, "--apply")
    step("migrate --apply: via script, guida e versione; config e status restano",
         r.returncode == 0
         and not any((a / p).exists() for p in (".keep-fresh/scripts", ".keep-fresh/guide.md",
                                                 ".keep-fresh/version.json"))
         and (a / CONFIG_FILE).is_file() and (a / STATUS_FILE).is_file(), r.stdout[-600:])
    claude = json.loads((a / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    gi = (a / ".gitignore").read_text(encoding="utf-8")
    step("migrate --apply: l'hook altrui resta, il file codex vuoto sparisce, "
         ".gitignore perde solo la riga codex",
         list(claude.get("hooks", {})) == ["PreToolUse"] and "permissions" in claude
         and not (a / ".codex" / "hooks.json").exists()
         and ".claude/settings.local.json" in gi and ".codex/hooks.json" not in gi
         and "build/" in gi, f"{claude} | {gi!r}")
    doc = (a / "AGENTS.md").read_text(encoding="utf-8")
    step("migrate --apply: i documenti usano i comandi della skill",
         all(s in doc for s in ("`/keep-fresh:lint`", "`/keep-fresh:handoff --elenco`",
                                "/keep-fresh:handoff.", "`keep-fresh:scripts/agent_hooks.py`"))
         and ".keep-fresh/scripts" not in doc, doc)
    step("migrate --apply: l'handoff in .git resta intatto",
         (a / ".git" / "keep-fresh-handoff" / "20261020-1140-prova.md").read_text(
             encoding="utf-8") == "cita .keep-fresh/scripts/handoff.py\n")

    run("git", "add", "-A", cwd=a)
    run("git", "commit", "-q", "-m", "migrazione", cwd=a)
    run("git", "add", "-A", cwd=b)
    run("git", "commit", "-q", "-m", "migrazione", cwd=b)
    before = snapshot(base)
    r = migrate(base, "--apply")
    step("migrate rilanciato: gia' migrato, niente cambia",
         r.stdout.count("gia' migrato") == 2 and not changed(before, base), r.stdout[-500:])

    rs = run(sys.executable, HOOKS_SCRIPT, "stop", "--agent", "prova", cwd=a,
             stdin='{"session_id":"m1"}')
    step("migrate: dopo la migrazione Stop non vede codice cambiato",
         rs.returncode == 0 and not rs.stdout.strip(), rs.stdout[-300:])

    base2 = tmpdir("kf-projects-")
    c = old_project(base2, "sporco")
    (c / "AGENTS.md").write_text(DOC_OLD + "\nmodifica mia\n", encoding="utf-8")
    d = old_project(base2, "rotto")
    (d / ".codex" / "hooks.json").write_text("{ non e' json", encoding="utf-8")
    before = snapshot(base2)
    r = migrate(base2, "--apply")
    step("migrate: un progetto con modifiche non committate in AGENTS.md si salta e lo dice",
         "saltato" in r.stdout and "AGENTS.md" in r.stdout
         and (c / ".keep-fresh" / "scripts").exists(), r.stdout[-600:])
    step("migrate: un file di aggancio con JSON rotto fa saltare il progetto e lo dice",
         ".codex/hooks.json" in r.stdout and (d / ".keep-fresh" / "scripts").exists()
         and not changed(before, base2), r.stdout[-600:])

    new, _ = mig.rewrite_text("usa /keep-fresh:handoff e /keep-fresh:init")
    step("rewrite_text: \"/keep-fresh:handoff\" resta com'e'",
         new == "usa /keep-fresh:handoff e /keep-fresh:init", new)


# -------------------------------------------------------------------------------- skill

USER_SKILLS = ("init", "status", "handoff", "resume", "migrate")
MODEL_SKILLS = ("lint", "cost")


def frontmatter(text: str) -> dict:
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        k, sep, v = line.partition(":")
        if sep:
            out[k.strip()] = v.strip()
    return out


def test_skills():
    skills = {}
    for name in USER_SKILLS + MODEL_SKILLS:
        p = PLUGIN / "skills" / name / "SKILL.md"
        skills[name] = p.read_text(encoding="utf-8") if p.is_file() else ""
    fm = {n: frontmatter(t) for n, t in skills.items()}
    step("skill: ci sono le sette, ognuna con name e description",
         all(fm[n].get("name") == n and fm[n].get("description") for n in fm),
         str({n: sorted(f) for n, f in fm.items()}))
    step("skill: init, status, handoff, resume, migrate non sono invocabili dal modello; "
         "lint e cost si'",
         all(fm[n].get("disable-model-invocation") == "true" for n in USER_SKILLS)
         and all("disable-model-invocation" not in fm[n] for n in MODEL_SKILLS),
         str({n: fm[n].get("disable-model-invocation") for n in fm}))
    cited = {m for t in skills.values() for m in re.findall(r"scripts>?/(\w+\.py)", t)}
    missing = sorted(c for c in cited if not (SCRIPTS / c).is_file())
    step("skill: ogni script citato esiste nel plugin", cited and not missing,
         f"citati={sorted(cited)} mancanti={missing}")
    texts = [(PLUGIN / "guide.md").read_text(encoding="utf-8"),
             (PLUGIN / "templates" / "config.toml").read_text(encoding="utf-8")]
    step("guida e taratura non citano .keep-fresh/scripts",
         not any(".keep-fresh/scripts" in t for t in texts))


# ------------------------------------------------------------------- vecchio impianto

# I file che nominano .keep-fresh/scripts di proposito: lo riconoscono per migrarlo o per
# cedergli il passo, lo descrivono come passato, o lo provano. Ovunque altrove sarebbe un
# rimando al vecchio posto del codice.
OLD_PATH_ALLOWED = (
    "docs/superpowers/", "README.md", "README.en.md",
    "plugins/keep-fresh/scripts/migrate.py", "plugins/keep-fresh/scripts/context_core.py",
    "plugins/keep-fresh/scripts/kf_init.py", "plugins/keep-fresh/scripts/agent_hooks.py",
    "plugins/keep-fresh/tests/selftest.py",
    "plugins/keep-fresh/skills/init/SKILL.md", "plugins/keep-fresh/skills/migrate/SKILL.md",
)


def test_no_old_code_location():
    r = run("git", "grep", "-l", "-F", ".keep-fresh/scripts", cwd=REPO)
    hits = [f for f in r.stdout.splitlines() if not f.startswith(OLD_PATH_ALLOWED)]
    step("nessun file del repo cita .keep-fresh/scripts come posto del codice", not hits,
         str(hits))


# ---------------------------------------------------------------- revisione finale

def test_review_fixes():
    sys.path.insert(0, str(SCRIPTS))
    import migrate as mig

    # 1. Il lint risolve i file del plugin citati nei documenti di un progetto migrato.
    root = new_project()
    st = root / STATUS_FILE
    st.write_text(st.read_text(encoding="utf-8")
                  + "\nVedi `keep-fresh:scripts/agent_hooks.py` e `docs_lint.py`.\n",
                  encoding="utf-8")
    r = run(sys.executable, LINT_SCRIPT, cwd=root)
    step("lint: i file del plugin citati nei documenti esistono",
         "agent_hooks.py" not in r.stdout and "docs_lint.py` non esiste" not in r.stdout,
         _lint_lines(r.stdout))

    st.write_text(st.read_text(encoding="utf-8")
                  + "\nGli hook in `scripts/agent_hooks.py` usano `tomllib` e `build_injection`.\n",
                  encoding="utf-8")
    r = run(sys.executable, LINT_SCRIPT, cwd=root)
    step("lint: percorsi e simboli del plugin citati senza prefisso esistono",
         "scripts/agent_hooks.py` non esiste" not in r.stdout and "`tomllib`" not in r.stdout
         and "`build_injection`" not in r.stdout, _lint_lines(r.stdout))

    # 2. La nota sull'interprete accanto a un comando riscritto cade con il comando.
    new, _ = mig.rewrite_text("Lint: `python .keep-fresh/scripts/docs_lint.py` "
                              "(`python3` su macOS/Linux).\n"
                              "python .keep-fresh/scripts/docs_lint.py      # python3 su macOS/Linux\n")
    step("rewrite_text: la nota (python3 su macOS/Linux) cade con il comando",
         new == "Lint: `/keep-fresh:lint`.\n/keep-fresh:lint\n", repr(new))

    # 3, 9. Avviso per le istruzioni che non valgono piu'; file dell'utente non tracciati.
    base = tmpdir("kf-projects-")
    p = old_project(base, "forza")
    (p / "AGENTS.md").write_text(DOC_OLD + "Aggiorna con `python agent_context_init.py --force`.\n",
                                 encoding="utf-8")
    run("git", "commit", "-q", "-am", "doc", cwd=p)
    plan = mig.plan_project(p)
    step("migrate: avvisa per le righe che citano l'inizializzatore o --force",
         any("--force" in w or "agent_context_init" in w for w in plan.warnings),
         str(plan.warnings))
    (p / ".keep-fresh" / "scripts" / "mio.py").write_text("x = 1\n", encoding="utf-8")
    plan = mig.plan_project(p)
    step("migrate: un file non tracciato in .keep-fresh/scripts fa saltare il progetto",
         plan.skip_reason is not None and "mio.py" in plan.skip_reason, str(plan.skip_reason))

    # 5. Una scrittura che fallisce non lascia il progetto a meta' e non ferma gli altri.
    base = tmpdir("kf-projects-")
    a = old_project(base, "a-bloccato")
    b = old_project(base, "b-libero")
    locked = a / ".codex" / "hooks.json"
    os.chmod(locked, stat.S_IREAD)
    try:
        r = migrate(base, "--apply")
    finally:
        os.chmod(locked, stat.S_IWRITE | stat.S_IREAD)
    step("migrate: una scrittura fallita lascia gli script, lo dice, e passa al prossimo",
         "fallito" in r.stdout and (a / ".keep-fresh" / "scripts").exists()
         and not (b / ".keep-fresh" / "scripts").exists(), r.stdout[-700:])

    # 6. Il plugin cede il passo solo all'agente che ha ancora il vecchio aggancio.
    p = old_project(tmpdir("kf-projects-"), "soloCodex")
    (p / ".claude" / "settings.local.json").unlink()
    (p / "core.py").write_text("x = 2\n", encoding="utf-8")
    rc = run(sys.executable, HOOKS_SCRIPT, "stop", "--agent", "claude", cwd=p,
             stdin='{"session_id":"z1"}')
    rx = run(sys.executable, HOOKS_SCRIPT, "stop", "--agent", "codex", cwd=p,
             stdin='{"session_id":"z2"}')
    step("vecchio aggancio solo per Codex: in Claude Code il plugin lavora, in Codex cede",
         _blocks(rc, "") and not rx.stdout.strip()
         and "ceduto al vecchio impianto" in hook_log(p), f"{rc.stdout[-200:]} | {hook_log(p)}")

    # La riga di .claude/settings.local.json resta in .gitignore anche se il file sparisce:
    # Claude Code lo ricrea (permessi approvati) e non deve finire in un commit.
    p = old_project(tmpdir("kf-projects-"), "gi")
    shutil.copyfile(p / ".codex" / "hooks.json", p / ".claude" / "settings.local.json")
    plan = mig.plan_project(p)
    step("migrate: la riga .claude/settings.local.json resta in .gitignore",
         ".claude/settings.local.json" not in plan.gitignore_lines
         and ".codex/hooks.json" in plan.gitignore_lines, str(plan.gitignore_lines))

    # Senza --root migrate non indovina dove stanno i progetti: lo chiede.
    r = run(sys.executable, MIGRATE_SCRIPT, cwd=tmpdir())
    step("migrate senza --root: si ferma e chiede la cartella", r.returncode == 2
         and "--root" in (r.stdout + r.stderr), (r.stdout + r.stderr)[-300:])

    # 7. Il lanciatore e' eseguibile per git: su macOS/Linux si lancia per percorso.
    r = run("git", "ls-files", "-s", "plugins/keep-fresh/hooks/run-hook.cmd", cwd=REPO)
    step("run-hook.cmd e' eseguibile (100755) nel repo", r.stdout.startswith("100755"),
         r.stdout)

    # 11. Il lint non rimanda all'inizializzatore che non esiste piu'.
    root = git_repo(with_config=False)
    run(sys.executable, INIT_SCRIPT, cwd=root)
    r = run(sys.executable, LINT_SCRIPT, cwd=root)
    step("lint senza commit: rimanda a /keep-fresh:init",
         "/keep-fresh:init" in r.stdout and "agent_context_init" not in r.stdout,
         _lint_lines(r.stdout))


# --------------------------------------------------------------------------------- main

TESTS = [test_manifests, test_launcher, test_scripts, test_quiet_and_yield, test_injection_names_lint, test_kf_init, test_migrate, test_skills, test_no_old_code_location, test_review_fixes]


def main() -> int:
    try:
        for t in TESTS:
            try:
                t()
            except Exception as exc:
                step(f"{t.__name__}: nessuna eccezione", False,
                     f"{type(exc).__name__}: {exc}")
    finally:
        for p in _tmpdirs:
            shutil.rmtree(p, ignore_errors=True)
    if failures:
        print(f"self-test: {len(failures)} passi falliti, {passed} passati")
        for f in failures:
            print(f"  FALLITO: {f}")
        return 1
    print(f"self-test: OK ({passed} passi)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
