#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
context_cost — quanto pesa il contesto di questo repository, misurato.

    python scripts/context_cost.py                resoconto; non chiama nessun modello
    python scripts/context_cost.py misura         misura ESATTA dei token che questo
                                                  impianto aggiunge a ogni sessione
    python scripts/context_cost.py --giorni 30    solo le sessioni degli ultimi 30 giorni
    python scripts/context_cost.py --anche <dir>  conta anche le sessioni aperte in <dir>
                                                  (il vecchio percorso di un repo spostato)

Ogni numero dice da dove viene:

  [misurato]  letto da cio' che l'agente registra: l'usage che l'API restituisce a ogni
              chiamata (trascrizioni di Claude Code, token_count di Codex), oppure il
              risultato di `misura`. E' il dato, non un calcolo.
  [stimato]   calcolato: caratteri divisi per un rapporto caratteri/token, o token
              moltiplicati per un prezzo di listino. Il rapporto viene dall'ultima
              `misura` di questo repository, se c'e'; altrimenti e' un valore di
              partenza, dichiarato.

COME MISURA `misura`. Lancia Claude Code headless tre volte in una copia usa e getta:
repository vuoto, poi con AGENTS.md e CLAUDE.md, poi anche con l'hook di avvio che
inietta il testo che inietterebbe qui. Il totale dei token di input di ogni esecuzione
lo riporta Claude Code; la differenza fra due esecuzioni e' il peso esatto dello strato
aggiunto, con il tokenizer e l'harness veri. Tutto il resto (prompt di sistema, strumenti,
istruzioni e plugin dell'utente) e' uguale nelle tre e si elide: la base viene misurata
due volte e, se non torna identica, la misura si ferma invece di dare un numero sporco.
Precisione: pochi token. Due misure dello stesso repository, il 2026-09-28, hanno dato
1.302 e 1.300 token per le stesse istruzioni: il percorso della copia usa e getta, che
cambia a ogni misura, compare nell'intestazione che l'agente mette ai file. La misura
comprende quelle intestazioni, perche' anche loro sono contesto pagato.
Costa quattro chiamate brevi al modello (circa $0,40 con Opus 5.5, quasi tutto la prima
scrittura in cache della base), e il costo esatto lo stampa alla fine.
Il risultato va in .git/context-cost.json, legato al contenuto misurato: se i file
cambiano, il resoconto lo dice e torna a stimare.

PREZZI. I costi sono l'equivalente a listino API, anche per chi usa un abbonamento (in
quel caso sono quota, non fattura). Il listino e' in PRICES qui sotto, con la sua fonte;
un modello che non c'e' non riceve un costo inventato. Per Codex lo strumento riporta i
token, non i costi.
"""

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import context_core as core  # noqa: E402

# ------------------------------------------------------------------------- listino

# $ per milione di token: (input, output, lettura dalla cache). La scrittura in cache
# costa 1,25x l'input con durata 5 minuti e 2x con durata 1 ora; la lettura 0,1x l'input,
# salvo dove il listino dice altro (Opus 5.5: $0,20; Fable 5.1: $0,25). Fonte: tabella
# dei modelli Anthropic aggiornata al 2026-06-24, con Claude Opus 5.5 al lancio.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-fable-5-1": (10.00, 50.00, 0.25),
    "claude-fable-5": (10.00, 50.00, 1.00),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
    "claude-opus-4-7": (5.00, 25.00, 0.50),
    "claude-opus-4-6": (5.00, 25.00, 0.50),
    "claude-sonnet-5": (2.00, 10.00, 0.20),
    "claude-sonnet-4-6": (3.00, 15.00, 0.30),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
}
WRITE_5M, WRITE_1H = 1.25, 2.0
# I modelli per cui il costo calcolato qui e' stato confrontato con quello che Claude Code
# calcola da se' (total_cost_usd di `claude -p`) su una sessione con scrittura e lettura
# in cache, e coincideva alla settima cifra decimale: 2026-09-26 Opus 5.5, 2026-09-28 gli
# altri tre. Per gli altri il resoconto dice che il prezzo non e' verificato.
VERIFIED_PRICES = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"}

# Rapporto caratteri/token usato solo finche' non c'e' una `misura` di questo repository.
# Valore di partenza: nelle sessioni di tre repository di questo impianto (documenti in
# italiano, markdown) e' stato 1,9-2,3 (stima dalle trascrizioni, 2026-09-26).
DEFAULT_CHARS_PER_TOKEN = 2.1

MEASURE_FILE = "context-cost.json"      # in .git/: e' un fatto della macchina, non del repo
PROMPT = "Rispondi solo: OK"


# ----------------------------------------------------------------------- utilita'

def norm(p) -> str:
    return os.path.normcase(os.path.normpath(str(p))).rstrip("\\/")


def inside(path, roots) -> bool:
    p = norm(path)
    return any(p == r or p.startswith(r + os.sep) for r in roots)


def parse_ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def price_of(model):
    if not model:
        return None
    if model in PRICES:
        return PRICES[model]
    # Un id con data in coda (claude-x-20260101) vale come il suo nome base.
    base = re.sub(r"-\d{8}$", "", model)
    return PRICES.get(base)


def usd(x):
    return "n/d" if x is None else f"${x:,.2f}"


def num(x):
    return f"{x:,}".replace(",", ".")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def iter_jsonl(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    yield d
    except OSError:
        return


# ------------------------------------------------------------- il contesto fisso, ora

def instruction_files(root: Path):
    """
    I file di istruzioni che l'agente carica da solo: CLAUDE.md, AGENTS.md e cio' che
    importano con righe `@percorso`, seguiti ricorsivamente. Solo quelli dentro il repo.
    """
    seen, order = set(), []

    def visit(p: Path):
        try:
            rp = p.resolve()
        except OSError:
            return
        if rp in seen or not rp.is_file() or not inside(rp, [norm(root.resolve())]):
            return
        seen.add(rp)
        order.append(rp)
        for line in rp.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^\s*@(\S+)\s*$", line)
            if m:
                visit(rp.parent / m.group(1))

    for name in ("CLAUDE.md", "AGENTS.md"):
        visit(root / name)
    return order


def current_fixed(root: Path):
    files = instruction_files(root)
    instr_text = "".join(p.read_text(encoding="utf-8", errors="replace") for p in files)
    inj = core.build_injection(root)
    return {
        "instruction_files": [p.relative_to(root.resolve()).as_posix() for p in files],
        "instructions_chars": len(instr_text),
        "instructions_sha": sha(instr_text),
        "injection_chars": len(inj["text"]) if inj else 0,
        "injection_sha": sha(inj["text"]) if inj else sha(""),
        "injection_reduced": bool(inj and inj["reduced"]),
        "injection_text": inj["text"] if inj else "",
    }


def load_measure(root: Path):
    g = core.git_dir(root)
    p = g / MEASURE_FILE if g else None
    if not p or not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def chars_per_token(measure):
    """Il rapporto dalla misura di questo repository, o quello di partenza."""
    if measure:
        c = measure.get("injection_chars", 0) + measure.get("instructions_chars", 0)
        t = measure.get("injection_tokens", 0) + measure.get("instructions_tokens", 0)
        if c > 0 and t > 0:
            return c / t, "dall'ultima misura di questo repository"
    return DEFAULT_CHARS_PER_TOKEN, "valore di partenza, nessuna misura ancora"


# --------------------------------------------------------------- Claude Code: sessioni

def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def claude_folder(path) -> str:
    """Il nome della cartella in cui Claude Code tiene le trascrizioni di un percorso."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def claude_files_for(roots, root_paths=(), other_cwds=None):
    """
    Le trascrizioni di questo repository: quelle la cui cartella di lavoro sta dentro uno
    dei percorsi dati, e quelle nella cartella che Claude Code intesta al percorso del
    repository. La seconda regola serve ai repository spostati: le sessioni vecchie
    registrano il percorso di prima, ma stanno nella cartella di adesso (osservato il
    2026-09-28 su progetto, spostato da C:\\vecchia a C:\\progetti\\vecchia).
    other_cwds, se dato, raccoglie le cartelle di lavoro diverse da quella di adesso.
    """
    base = claude_home() / "projects"
    if not base.is_dir():
        return []
    folders = {claude_folder(p).lower() for p in root_paths}
    picked = []
    for f in base.glob("*/*.jsonl"):
        cwd = None
        for i, d in enumerate(iter_jsonl(f)):
            if d.get("cwd"):
                cwd = d["cwd"]
                break
            if i > 200:
                break
        by_cwd = bool(cwd and inside(cwd, roots))
        if by_cwd or f.parent.name.lower() in folders:
            if cwd and not by_cwd and other_cwds is not None:
                other_cwds.add(cwd)
            picked.append(f)
            # I sottoagenti stanno in <sessione>/subagents/, stessa cartella di lavoro.
            picked += sorted((f.parent / f.stem / "subagents").glob("*.jsonl"))
    return picked


# Una lettura e' uno strumento di lettura, o un comando di shell che mostra un file. Un
# `git diff` o un `grep` sul repo che nomina un documento non lo e'.
READ_TOOLS = {"Read", "Grep", "NotebookRead"}
SHOW_RE = re.compile(r"^\s*(?:rtk\s+)?(?:cat|head|tail|sed\s+-n|less|more|type|"
                     r"Get-Content|gc|bat|read)\b", re.I)


def is_read(name, inp):
    """Il testo in cui cercare il documento letto, o None se non e' una lettura."""
    if name in READ_TOOLS:
        return " ".join(str(v) for v in inp.values())
    if name in ("Bash", "PowerShell"):
        cmd = str(inp.get("command", ""))
        parts = re.split(r"&&|;|\|\||\n", cmd)
        return " ".join(p for p in parts if SHOW_RE.match(p)) or None
    return None


CTX_RE = re.compile(r"(docs[/\\]context[/\\][^\s\"'`]+\.md|AGENTS\.md|CLAUDE\.md)")


def claude_sessions(files, since):
    """
    Una voce per sessione. Le chiamate si contano per id del messaggio, su TUTTI i file
    insieme: una sessione ripresa puo' ricopiare la storia in un file nuovo, e un
    messaggio in streaming compare su piu' righe. Per ogni id vale l'ultimo usage.
    """
    calls = {}                      # id -> dati della chiamata
    sessions = defaultdict(lambda: {"compactions": 0, "files": set(), "reads": []})
    tool_uses, seen_results = {}, set()
    for f in files:
        for d in iter_jsonl(f):
            sid = d.get("sessionId") or f.stem
            s = sessions[sid]
            s["files"].add(f.name)
            t = d.get("type")
            if t == "system" and d.get("subtype") == "compact_boundary":
                s["compactions"] += 1
            if t == "assistant":
                m = d.get("message") or {}
                u = m.get("usage")
                mid = m.get("id") or d.get("requestId")
                if not mid or not isinstance(u, dict) or m.get("model") == "<synthetic>":
                    continue
                ts = parse_ts(d.get("timestamp"))
                prev = calls.get(mid)
                # La sessione e l'ora sono quelle della prima comparsa; l'usage l'ultimo.
                calls[mid] = {"sid": prev["sid"] if prev else sid,
                              "ts": prev["ts"] if prev else ts, "u": u,
                              "model": m.get("model"),
                              "side": bool(d.get("isSidechain"))}
                for b in m.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        tool_uses[b.get("id")] = (b.get("name"), b.get("input") or {})
            elif t == "user":
                content = (d.get("message") or {}).get("content")
                for b in content if isinstance(content, list) else []:
                    if not isinstance(b, dict) or b.get("type") != "tool_result":
                        continue
                    tid = b.get("tool_use_id")
                    if tid in seen_results:
                        continue
                    name, inp = tool_uses.get(tid, (None, {}))
                    target = is_read(name, inp)
                    docs = sorted({x.replace("\\", "/")
                                   for x in CTX_RE.findall(target)}) if target else []
                    if docs:
                        seen_results.add(tid)
                        c = b.get("content")
                        text = c if isinstance(c, str) else "".join(
                            x.get("text", "") for x in c or [] if isinstance(x, dict))
                        # Un comando che mostra piu' documenti: i caratteri si dividono
                        # in parti uguali. Il totale e' esatto, la ripartizione no.
                        for doc in docs:
                            s["reads"].append((doc, len(text) / len(docs),
                                               parse_ts(d.get("timestamp"))))

    by_sid = defaultdict(list)
    for c in calls.values():
        by_sid[c["sid"]].append(c)
    out = []
    for sid, cs in by_sid.items():
        cs.sort(key=lambda c: c["ts"] or datetime.min.replace(tzinfo=timezone.utc))
        start = cs[0]["ts"]
        if since and start and start < since:
            continue
        # read_rate: somma, chiamata per chiamata, del prezzo di lettura del suo modello;
        # write_rate: prezzo di scrittura (1 ora) del modello della prima chiamata. Servono
        # a dire quanto vale un blocco fisso di N token su QUESTE chiamate.
        agg = {"in": 0, "w5": 0, "w1": 0, "r": 0, "out": 0, "cost": 0.0,
               "cost_known": True, "read_rate": 0.0, "write_rate": 0.0}
        models = set()
        ctx_max, first_ctx = 0, None
        for c in cs:
            u = c["u"]
            cw = u.get("cache_creation_input_tokens", 0) or 0
            det = u.get("cache_creation") or {}
            w1 = det.get("ephemeral_1h_input_tokens", 0) or 0
            w5 = det.get("ephemeral_5m_input_tokens", cw - w1) or 0
            if w1 + w5 != cw:          # dettaglio assente o incoerente: tutto a 5 minuti
                w1, w5 = 0, cw
            i, r, o = (u.get("input_tokens", 0) or 0, u.get("cache_read_input_tokens", 0)
                       or 0, u.get("output_tokens", 0) or 0)
            agg["in"] += i; agg["w5"] += w5; agg["w1"] += w1; agg["r"] += r; agg["out"] += o
            models.add(c["model"])
            p = price_of(c["model"])
            if p is None:
                agg["cost_known"] = False
            else:
                pin, pout, pr = p
                agg["read_rate"] += pr
                if not agg["write_rate"]:
                    agg["write_rate"] = pin * WRITE_1H
                agg["cost"] += (i * pin + w5 * pin * WRITE_5M + w1 * pin * WRITE_1H
                                + r * pr + o * pout) / 1e6
            ctx = i + cw + r
            if not c["side"]:
                ctx_max = max(ctx_max, ctx)
                if first_ctx is None:
                    first_ctx = ctx
        main = [c for c in cs if not c["side"]]
        out.append({
            "sid": sid, "start": start, "end": cs[-1]["ts"],
            "calls": len(main), "sub_calls": len(cs) - len(main),
            "first_ctx": first_ctx or 0, "ctx_max": ctx_max,
            "compactions": sessions[sid]["compactions"],
            "models": sorted(m for m in models if m), "reads": sessions[sid]["reads"],
            **agg,
        })
    out.sort(key=lambda s: s["start"] or datetime.min.replace(tzinfo=timezone.utc))
    return out


# --------------------------------------------------------------------- Codex: sessioni

def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def codex_sessions(roots, since):
    base = codex_home() / "sessions"
    if not base.is_dir():
        return []
    out = []
    for f in base.rglob("rollout-*.jsonl"):
        cwd, model, start = None, None, None
        last_total, calls, ctx_max, first_ctx = None, 0, 0, None
        for d in iter_jsonl(f):
            p = d.get("payload") or {}
            if d.get("type") == "session_meta":
                cwd = p.get("cwd")
                start = parse_ts(p.get("timestamp") or d.get("timestamp"))
                if cwd and not inside(cwd, roots):
                    break
            elif d.get("type") == "turn_context" and p.get("model"):
                model = p.get("model")
            elif d.get("type") == "event_msg" and p.get("type") == "token_count":
                info = p.get("info") or {}
                total, last = info.get("total_token_usage"), info.get("last_token_usage")
                if not total or total == last_total:
                    continue
                last_total = total
                calls += 1
                ctx = (last or {}).get("input_tokens", 0) or 0
                ctx_max = max(ctx_max, ctx)
                if first_ctx is None:
                    first_ctx = ctx
        if not cwd or not inside(cwd, roots) or not calls:
            continue
        if since and start and start < since:
            continue
        out.append({"file": f.name, "start": start, "model": model, "calls": calls,
                    "first_ctx": first_ctx or 0, "ctx_max": ctx_max,
                    "in": last_total.get("input_tokens", 0),
                    "cached": last_total.get("cached_input_tokens", 0),
                    "out": last_total.get("output_tokens", 0)})
    out.sort(key=lambda s: s["start"] or datetime.min.replace(tzinfo=timezone.utc))
    return out


# ------------------------------------------------------------ traccia dell'iniezione

LOG_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2}\s+(?:(\S+)\s+)?SessionStart"
                    r"\s+iniettati (\d+) caratteri")


def injection_trend(root: Path):
    """Per giorno: iniezioni e caratteri massimi, dalle tracce degli hook (nuova e vecchia)."""
    g = core.git_dir(root)
    days = defaultdict(lambda: [0, 0])
    for name in ("agent-hooks.log", "claude-hooks.log"):
        p = g / name if g else None
        if not p or not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = LOG_RE.match(line)
            if m:
                d = days[m.group(1)]
                d[0] += 1
                d[1] = max(d[1], int(m.group(3)))
    return sorted(days.items())


# ------------------------------------------------------------------------- resoconto

def report(root: Path, extra, giorni, as_json):
    roots = [norm(root.resolve())] + [norm(Path(e).resolve()) for e in extra]
    since = (datetime.now(timezone.utc) - timedelta(days=giorni)) if giorni else None
    fixed = current_fixed(root)
    measure = load_measure(root)
    cpt, cpt_src = chars_per_token(measure)
    other_cwds = set()
    sessions = claude_sessions(
        claude_files_for(roots, [root.resolve()] + [Path(e).resolve() for e in extra],
                         other_cwds), since)
    cx = codex_sessions(roots, since)
    trend = injection_trend(root)

    if as_json:
        def enc(o):
            return o.isoformat() if isinstance(o, datetime) else str(o)
        fixed.pop("injection_text", None)
        print(json.dumps({"fixed": fixed, "measure": measure, "chars_per_token": cpt,
                          "claude_sessions": sessions, "codex_sessions": cx,
                          "injection_trend": trend}, default=enc, ensure_ascii=False,
                         indent=1))
        return 0

    W = 78
    print("=" * W)
    print(f"context_cost — {root}")
    print("[misurato] = registrato dall'agente o dalla misura esatta   "
          "[stimato] = calcolato")
    print("=" * W)

    # 1. Contesto fisso, oggi
    print("\n1. CONTESTO FISSO CHE QUESTO IMPIANTO AGGIUNGE A OGNI SESSIONE (oggi)")
    fresh = bool(measure and measure.get("instructions_sha") == fixed["instructions_sha"]
                 and measure.get("injection_sha") == fixed["injection_sha"])
    rows = [("istruzioni (" + (", ".join(fixed["instruction_files"]) or "nessuna") + ")",
             fixed["instructions_chars"], "instructions_tokens"),
            ("iniezione dell'hook di avvio" + (" (RIDOTTA a indice: oltre il tetto)"
                                               if fixed["injection_reduced"] else ""),
             fixed["injection_chars"], "injection_tokens")]
    tot_tok = 0
    for label, chars, key in rows:
        if fresh:
            tok, tag = measure[key], "[misurato]"
        else:
            tok, tag = round(chars / cpt), "[stimato]"
        tot_tok += tok
        print(f"  {label}")
        print(f"      {num(chars)} caratteri  ->  {num(tok)} token {tag}")
    print(f"  totale: {num(tot_tok)} token, in ogni chiamata al modello della sessione")
    if fresh:
        print(f"  misura del {measure['date']} con Claude Code {measure.get('claude_version')}"
              f", modello {measure.get('model')}; base dell'harness "
              f"{num(measure['base_tokens'])} token [misurato]")
    elif measure:
        print(f"  L'ultima misura ({measure['date']}) e' di contenuti diversi da quelli di "
              f"oggi: token stimati con il suo rapporto, {cpt:.2f} caratteri/token.")
        print("  Per il valore esatto: python scripts/context_cost.py misura")
    else:
        print(f"  Token stimati a {cpt:.2f} caratteri/token ({cpt_src}).")
        print("  Per il valore esatto: python scripts/context_cost.py misura")

    # 2. Sessioni Claude Code
    print("\n2. SESSIONI DI CLAUDE CODE (trascrizioni in "
          f"{claude_home() / 'projects'})" + (f", ultimi {giorni} giorni" if giorni else ""))
    if other_cwds:
        print("  comprese sessioni aperte quando il repository stava altrove: "
              + ", ".join(sorted(other_cwds)))
    if not sessions:
        print("  nessuna trascrizione con cartella di lavoro in questo repository")
    else:
        print("  inizio            chiam. sub  compatt.  avvio(tok) max(tok)   costo")
        for s in sessions:
            st = s["start"].astimezone().strftime("%Y-%m-%d %H:%M") if s["start"] else "?"
            print(f"  {st:16s}  {s['calls']:6d} {s['sub_calls']:4d} {s['compactions']:9d}"
                  f"  {num(s['first_ctx']):>10s} {num(s['ctx_max']):>9s}  "
                  f"{usd(s['cost']) if s['cost_known'] else 'n/d':>8s}")
        T = {k: sum(s[k] for s in sessions) for k in ("in", "w5", "w1", "r", "out", "cost",
                                                    "calls", "sub_calls")}
        known = all(s["cost_known"] for s in sessions)
        print(f"  totale: {len(sessions)} sessioni, {num(T['calls'])} chiamate "
              f"(+{num(T['sub_calls'])} di sottoagenti)")
        print(f"    token [misurato]: input {num(T['in'])} · scritti in cache "
              f"{num(T['w5'] + T['w1'])} (di cui 1 ora {num(T['w1'])}) · letti dalla cache "
              f"{num(T['r'])} · output {num(T['out'])}")
        print(f"    costo a listino API [stimato]: {usd(T['cost'])}"
              + ("" if known else "  (esclusi i modelli senza prezzo: "
                 + ", ".join(sorted({m for s in sessions if not s['cost_known']
                                     for m in s['models']})) + ")"))
        used = sorted({re.sub(r"-\d{8}$", "", m) for s in sessions for m in s["models"]
                       if price_of(m)})
        unverified = [m for m in used if m not in VERIFIED_PRICES]
        print("      token misurati per prezzo di listino; listino confrontato con il "
              "costo calcolato da Claude Code per: "
              + ", ".join(m for m in used if m in VERIFIED_PRICES)
              + (f"; NON verificato per: {', '.join(unverified)}" if unverified else ""))
        allc = T["calls"] + T["sub_calls"]
        if allc:
            print(f"    contesto medio per chiamata [misurato]: "
                  f"{num(round((T['in'] + T['w5'] + T['w1'] + T['r']) / allc))} token")
        # Quanto del totale e' il contesto fisso di oggi, a parita' di chiamate.
        if T["calls"]:
            share = tot_tok * sum(s["read_rate"] + s["write_rate"] for s in sessions) / 1e6
            print(f"    il contesto fisso di oggi ({num(tot_tok)} token) su queste chiamate "
                  f"varrebbe ~{usd(share)} [stimato: una scrittura per sessione, poi una "
                  f"lettura a chiamata, al prezzo del modello di ciascuna]")
        reads = defaultdict(lambda: [0, 0])
        for s in sessions:
            for path, chars, _ in s["reads"]:
                reads[path][0] += 1
                reads[path][1] += chars
        if reads:
            print("  documenti di contesto letti dall'agente (per intero o in parte):")
            for path, (n, chars) in sorted(reads.items(), key=lambda kv: -kv[1][1])[:10]:
                print(f"    {path:40s} {n:4d} letture  {num(round(chars)):>10s} caratteri"
                      f"  ~{num(round(chars / cpt))} token [stimato]")

    # 3. Codex
    print("\n3. SESSIONI DI CODEX (" + str(codex_home() / "sessions") + ")")
    if not cx:
        print("  nessuna sessione con cartella di lavoro in questo repository")
    else:
        for s in cx:
            st = s["start"].astimezone().strftime("%Y-%m-%d %H:%M") if s["start"] else "?"
            print(f"  {st}  {s['model'] or '?':14s} {s['calls']:5d} chiamate  avvio "
                  f"{num(s['first_ctx'])}  max {num(s['ctx_max'])} token [misurato]")
        print(f"  totale token [misurato]: input {num(sum(s['in'] for s in cx))} (di cui "
              f"in cache {num(sum(s['cached'] for s in cx))}) · output "
              f"{num(sum(s['out'] for s in cx))}. Costi non calcolati: listino non noto "
              f"allo strumento.")

    # 4. Traccia
    print("\n4. INIEZIONE DI AVVIO NEL TEMPO (traccia degli hook in .git/)")
    if not trend:
        print("  nessuna traccia")
    else:
        for day, (n, mx) in trend[-14:]:
            print(f"  {day}  {n:3d} avvii   max {num(mx):>9s} caratteri [misurato]"
                  f"  ~{num(round(mx / cpt))} token [stimato]")
    print()
    return 0


# --------------------------------------------------------------------------- misura

def run_claude(cwd: Path):
    exe = shutil.which("claude") or "claude"
    r = subprocess.run([exe, "-p", PROMPT, "--max-turns", "1", "--output-format",
                        "json"], cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError(f"Claude Code non ha dato JSON (uscita {r.returncode}): "
                           f"{(r.stderr or r.stdout)[-400:]}")
    u = d.get("usage") or {}
    total = sum(u.get(k, 0) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                           "cache_read_input_tokens"))
    model = next(iter(d.get("modelUsage") or {}), None)
    return total, float(d.get("total_cost_usd") or 0.0), model


def measure(root: Path):
    if shutil.which("claude") is None:
        print("claude non e' nel PATH: la misura usa Claude Code headless.")
        return 1
    fixed = current_fixed(root)
    try:
        ver = subprocess.run([shutil.which("claude"), "--version"], capture_output=True, text=True,
                             timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        ver = "?"
    print(f"Misura esatta per {root}")
    print(f"Claude Code {ver}. Quattro chiamate brevi al modello, in una copia usa e getta.")
    tmp = Path(tempfile.mkdtemp(prefix="context-cost-"))
    spent = 0.0
    try:
        subprocess.run(["git", "init", "-q", "."], cwd=str(tmp), check=True)
        base1, c, model = run_claude(tmp); spent += c
        base2, c, _ = run_claude(tmp); spent += c
        print(f"  base dell'harness: {num(base1)} e {num(base2)} token")
        if base1 != base2:
            print("  La base non e' stabile fra due esecuzioni identiche: una differenza "
                  "non misurerebbe solo i file. Misura interrotta, niente salvato.")
            return 1
        for rel in fixed["instruction_files"]:
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / rel, dst)
        with_instr, c, _ = run_claude(tmp); spent += c
        # L'hook stampa il testo che l'hook vero inietterebbe OGGI in questo repository.
        (tmp / "injection.txt").write_text(fixed["injection_text"], encoding="utf-8")
        (tmp / "print_injection.py").write_text(
            "import sys\nsys.stdout.reconfigure(encoding='utf-8')\n"
            "sys.stdout.write(open(__file__.replace('print_injection.py','injection.txt'),"
            "encoding='utf-8').read())\n", encoding="utf-8")
        settings = {"hooks": {"SessionStart": [{"hooks": [{
            "type": "command",
            "command": f'{Path(sys.executable).as_posix()} '
                       f'"{(tmp / "print_injection.py").as_posix()}"',
            "timeout": 30}]}]}}
        (tmp / ".claude").mkdir(exist_ok=True)
        (tmp / ".claude" / "settings.local.json").write_text(json.dumps(settings),
                                                             encoding="utf-8")
        with_inj, c, _ = run_claude(tmp); spent += c
    except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
        print(f"  Misura fallita: {exc}")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    instr_tok = with_instr - base1
    inj_tok = with_inj - with_instr
    if fixed["injection_chars"] and inj_tok <= 0:
        print("  L'iniezione non risulta nel contesto: l'hook della copia non e' partito. "
              "Misura non salvata.")
        return 1
    result = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "claude_version": ver,
        "model": model, "base_tokens": base1,
        "instruction_files": fixed["instruction_files"],
        "instructions_chars": fixed["instructions_chars"],
        "instructions_sha": fixed["instructions_sha"], "instructions_tokens": instr_tok,
        "injection_chars": fixed["injection_chars"],
        "injection_sha": fixed["injection_sha"], "injection_tokens": inj_tok,
        "cost_usd": round(spent, 4),
    }
    g = core.git_dir(root)
    if g:
        (g / MEASURE_FILE).write_text(json.dumps(result, indent=1, ensure_ascii=False),
                                      encoding="utf-8")
    print(f"  istruzioni ({', '.join(fixed['instruction_files']) or 'nessuna'}): "
          f"{num(instr_tok)} token [misurato]")
    print(f"  iniezione dell'hook di avvio: {num(inj_tok)} token [misurato]")
    print(f"  modello {model}; costo della misura ${spent:.4f} (calcolato da Claude Code)")
    print(f"  salvata in .git/{MEASURE_FILE}")
    return 0


# ---------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description="Quanto pesa il contesto, misurato.")
    ap.add_argument("comando", nargs="?", choices=["misura"],
                    help="misura: misura esatta dei token fissi (chiama Claude Code)")
    ap.add_argument("--giorni", type=int, default=0,
                    help="solo le sessioni iniziate negli ultimi N giorni")
    ap.add_argument("--anche", action="append", default=[], metavar="DIR",
                    help="conta anche le sessioni aperte in questa cartella")
    ap.add_argument("--json", action="store_true", help="uscita per programmi")
    a = ap.parse_args(argv)
    root = core.repo_root() or Path(__file__).resolve().parent.parent
    if a.comando == "misura":
        return measure(Path(root))
    return report(Path(root), a.anche, a.giorni, a.json)


if __name__ == "__main__":
    sys.exit(main())
