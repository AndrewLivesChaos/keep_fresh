# keep-fresh

Plugin per agenti di programmazione (Claude Code e Codex) che prepara un repository git
perché gli agenti ci lavorino con un contesto che non marcisce: documenti di contesto, un
lint che controlla che dicano ancora il vero, e hook che mettono lo stato del lavoro
davanti all'agente e gli impediscono di chiudere un turno se il codice è cambiato e lo
stato no.

Il plugin fa solo la meccanica. Il contesto lo scrive l'agente, seguendo la guida del
plugin. Il codice sta **solo nel plugin**: un fix rilasciato arriva a tutti i progetti con
un aggiornamento del plugin, senza toccarli.

> **Stato delle verifiche.** Provato su **Windows 11** con **Python 3.14**: il self-test del
> plugin su repository finti; gli hook del plugin in sessioni vere di **Claude Code
> 2.1.308** (`claude -p --plugin-dir`) e **Codex 0.154.0** (`codex exec`, con un plugin di
> prova e `--dangerously-bypass-hook-trust`). Non provato: macOS, Linux, l'approvazione degli
> hook in una sessione interattiva di Codex.

## Installare

Il repository `AndrewLivesChaos/keep_fresh` è il marketplace. Si installa dal ramo `master`.

**Claude Code**, una volta per configurazione:

```powershell
claude plugin marketplace add AndrewLivesChaos/keep_fresh
claude plugin install keep-fresh@keep-fresh
```

Per una seconda configurazione (per esempio `~/.claude-lavoro`) gli stessi due comandi con
`CLAUDE_CONFIG_DIR` puntato a quella cartella: le configurazioni restano isolate, ognuna con
la sua copia.

**Codex:**

```powershell
codex plugin marketplace add AndrewLivesChaos/keep_fresh
codex plugin add keep-fresh@keep-fresh
```

Poi, dentro Codex, `/hooks` e approva i tre hook di keep-fresh. **Senza approvazione Codex li
salta senza avvisare** (provato con `codex exec`, Windows, 0.154.0). Secondo la
documentazione l'approvazione vale per la definizione dell'hook: va rifatta solo se il file
di hook del plugin cambia, non a ogni aggiornamento degli script.

Il repository è privato: Claude Code e Codex lo clonano con le credenziali git della
macchina (la chiave SSH, se caricata senza prompt).

## I comandi

| Comando | Cosa fa |
|---|---|
| `/keep-fresh:init` | prepara il repository corrente: prova a vuoto, conferma, poi scrive i due semi |
| `/keep-fresh:status` | stato in sola lettura: plugin, hook, handoff, lint, cosa sistemare |
| `/keep-fresh:handoff` | l'agente scrive dove sei arrivato, per riprendere in una sessione nuova (`--elenco`, `--scarta n`) |
| `/keep-fresh:resume` | riprende un handoff (`n`, una parola del titolo, `--comunque`) |
| `/keep-fresh:migrate` | porta sul plugin, in un colpo, i progetti col vecchio impianto |
| `/keep-fresh:lint` | il lint dei documenti; lo usa anche l'agente da solo |
| `/keep-fresh:cost` | quanto pesa il contesto (`misura`, `--giorni N`) |

In Codex le skill si invocano con `$keep-fresh:<nome>`.

## Cosa scrive nel progetto

Solo due **semi**, scritti se mancano e mai sovrascritti:

| Percorso | Cos'è |
|---|---|
| `.keep-fresh/config.toml` | la taratura fatta a mano |
| `docs/keep-fresh/context/status.md` | lo scheletro dello stato del lavoro |

Il resto del contesto (`AGENTS.md`, `CLAUDE.md`, gli altri file di `docs/keep-fresh/context/`)
lo scrive l'agente seguendo la guida. Gli hook non si agganciano nel progetto: li porta il
plugin, e dove manca `.keep-fresh/config.toml` non fanno niente. Fuori dal repository, in
`.git/`, gli hook tengono la loro traccia (`agent-hooks.log`) e gli handoff
(`keep-fresh-handoff/`).

Anche in una cartella vuota appena creata con `git init` funziona. Manca solo il marcatore
di freschezza di `status.md`, perché non c'è ancora uno sha: dopo il primo commit si
rilancia `/keep-fresh:init`, che lo aggiunge se lo scheletro è intatto.

## La taratura: `.keep-fresh/config.toml`

Il lint rileva il codice da solo e lo dice nel controllo 0. Se sbaglia, si corregge in
`[code]`: `include` per percorsi che deve considerare codice (una directory che inizia con
un punto, file senza estensione riconosciuta), `exclude` per quelli che non deve
considerare (codice generato, librerie copiate).

Le quattro tabelle `[lint.*]` partono **vuote di proposito**: sono lavoro di dominio, e si
riempiono guardando i falsi positivi del primo giro di lint, con il motivo scritto accanto
a ogni voce.

`[context] max_injection_chars` è il tetto, in caratteri, di ciò che l'hook di avvio
inietta per intero dai blocchi `session-start` di `status.md` (8000 di partenza; se la
chiave manca vale lo stesso). Oltre il tetto l'hook inietta solo l'indice dei blocchi,
titoli e prima riga di ogni voce, e il lint avvisa nel controllo 6. Il rimedio è
accorciare i blocchi, non alzare il tetto.

## Quanto pesa il contesto: `/keep-fresh:cost`

```
/keep-fresh:cost                 resoconto, non chiama nessun modello
/keep-fresh:cost misura          misura esatta dei token fissi (circa $0,40)
/keep-fresh:cost --giorni 30
```

Il resoconto legge le trascrizioni di Claude Code e i `token_count` di Codex delle sessioni
aperte in questo repository, anche in una sua sottocartella. Per ogni sessione: chiamate,
contesto all'avvio e massimo, token scritti e letti in cache, costo a listino API. Poi le
letture dei documenti di contesto e l'andamento dell'iniezione, dalla traccia degli hook.

Ogni numero è marcato **[misurato]**, cioè registrato dall'agente o dalla misura esatta, o
**[stimato]**, cioè calcolato. Come lo si sa:

- **token e costo delle sessioni:** confrontati con il costo che Claude Code calcola da
  sé (`claude -p --output-format json`) su sessioni con scrittura e lettura in cache.
  Coincidevano alla settima cifra decimale per Opus 5.5, Opus 5, Sonnet 5 e Haiku 4.5
  (Windows 11, Claude Code 2.1.283, 2026-09-26/28). Per gli altri modelli del listino il
  resoconto dice che il prezzo non è verificato. Per Codex dà i token, non i costi;
- **`misura`:** lancia Claude Code headless in una copia usa e getta, vuota, con
  `AGENTS.md`/`CLAUDE.md` e con l'iniezione, e sottrae i totali. Ogni strato è misurato
  due volte e le due misure devono coincidere, o la misura si ferma senza salvare. Il
  risultato va in `.git/context-cost.json`, legato al contenuto: se i file cambiano, il
  resoconto torna a stimare e lo dice;
- **non provato:** macOS e Linux; Codex nella `misura`, che oggi usa solo Claude Code.

## Cambiare sessione senza perdere il filo: handoff

1. L'hook `prompt` ferma il messaggio **una volta per sessione** quando il contesto supera
   `handoff_warn_tokens` (150.000 token di partenza) e propone `/keep-fresh:handoff`. Non
   ferma mai un comando `/`, né i messaggi che l'agente genera da sé (la notifica di fine
   di un sotto-agente o di un comando in background, `<task-notification>`).
2. `/keep-fresh:handoff`: l'agente scrive in `.git/keep-fresh-handoff/` un file con obiettivo,
   fatto, decisioni, vicoli ciechi e prossimo passo. Poi fai `/clear` o apri una sessione nuova.
3. Nella sessione nuova l'hook di avvio accoda **un indice** (una riga per handoff aperto,
   al massimo cinque). Non ne legge il contenuto e non agisce.
4. `/keep-fresh:resume [n|parola]` riprende quello che scegli. Se è scritto su un altro
   branch o su un HEAD che non è nel tuo storico, lo dice e non lo consuma; con
   `--comunque` lo riprende lo stesso.

Si possono avere più handoff in coda. Ognuno è `aperto`, poi `ripreso` o `scartato`
(`/keep-fresh:handoff --scarta [n|parola]`); oltre `handoff_ore` (48 di partenza) non
compare più nell'indice, ma nominandolo si riprende ancora; i chiusi e gli scaduti da più
di `handoff_prune_giorni` (30) si cancellano da soli all'avvio. Le tre chiavi stanno in
`[context]` di `config.toml`, commentate con il loro valore. Gli handoff sono **locali**:
stanno in `.git/` e non finiscono in un commit.

## Gli hook

Gli stessi per tutti gli agenti (`plugins/keep-fresh/scripts/agent_hooks.py`), tre:

- **all'avvio** (`SessionStart`) inietta lo stato del lavoro da `status.md`;
- **a fine turno** (`Stop`) blocca una volta se il codice è cambiato e `status.md` no;
- **prima di un tuo messaggio** (`UserPromptSubmit`), dopo una pausa più lunga della cache
  con un contesto grande, ferma il messaggio **una volta** e dice quanto costa riprendere;
  oltre `handoff_warn_tokens` propone l'handoff. Reinviato, passa.

Sono **fail-open**: un errore interno esce 0 senza stampare. L'unico modo di sapere se
girano è la traccia `.git/agent-hooks.log`, una riga per esecuzione, che
`/keep-fresh:status` riassume. Lo stdout di `SessionStart` va nel contesto dell'agente, non a
schermo: non vedere niente è normale.

Codex legge `AGENTS.md` da solo. Claude Code legge `CLAUDE.md`, quindi gli serve un
`CLAUDE.md` che importi `AGENTS.md`: lo scrive l'agente seguendo la guida.

## Migrare i progetti col vecchio impianto

Le versioni precedenti copiavano gli script in ogni progetto (`.keep-fresh/scripts/`) e
agganciavano gli hook in `.claude/settings.local.json` e `.codex/hooks.json`. Per portarli
tutti sul plugin:

1. installa il plugin in tutte le configurazioni (sopra);
2. `/keep-fresh:migrate`: prova a vuoto su tutti i progetti sotto `C:\projects` (o
   `--root DIR`), poi, con la tua conferma, scrive. Toglie script, guida e versione copiati,
   toglie dai file di aggancio solo gli hook di keep-fresh, e nei documenti sostituisce i
   comandi degli script con i comandi della skill. Salta, dicendolo, un progetto con
   modifiche non committate nei file da toccare. Non committa;
3. guarda il `git diff` di ogni progetto e committa;
4. togli le vecchie skill copiate a mano (`~/.claude/skills/keep-fresh` e simili), che
   altrimenti si vedono accanto a quelle del plugin.

Finché un progetto non è migrato, gli hook del plugin **cedono il passo** alla sua copia
vecchia: un solo impianto lavora, mai due.

## Aggiornare

```powershell
claude plugin update keep-fresh@keep-fresh     # in ogni configurazione
codex plugin marketplace upgrade               # Codex
```

Oppure, in Claude Code, `/plugin` → *Marketplaces* → keep-fresh → *Enable auto-update*. Un
aggiornamento arriva solo quando cambia la versione del plugin. `config.toml` e `status.md`
non vengono mai toccati.

## Se qualcosa non torna

- **"Non sei dentro un repository git"**: `git init` prima.
- **Gli hook non partono e `.git/agent-hooks.log` resta vuoto**: il plugin non è
  installato o è disattivato in quella configurazione (`/keep-fresh:status` lo dice); con
  Codex, gli hook non sono approvati (`/hooks`). In un progetto non migrato la traccia dice
  `ceduto al vecchio impianto`: è normale, migra.
- **Il lint accusa decine di identificatori inesistenti al primo giro**: è normale. Prima
  si corregge la taratura in `config.toml`, poi i documenti. Una segnalazione che descrive
  un difetto vero non si mette a tacere: si registra in `status.md` come lavoro aperto.

## Sviluppare keep-fresh

```
.claude-plugin/marketplace.json      marketplace per Claude Code
.agents/plugins/marketplace.json     marketplace per Codex
plugins/keep-fresh/                  il plugin
  .claude-plugin/plugin.json         manifesto Claude Code (version)
  .codex-plugin/plugin.json          manifesto Codex (version, file di hook)
  hooks/hooks.json                   hook per Claude Code, via hooks/run-hook.cmd
  hooks/codex-hooks.json             hook per Codex (command / commandWindows)
  scripts/                           lint, hook, handoff, costi, init, migrate
  skills/<comando>/SKILL.md          una skill per comando
  guide.md                           la guida che l'agente esegue
  templates/config.toml              il seme della taratura
  tests/selftest.py                  il self-test
```

- Si lavora su `develop`; `master` è ciò che gli utenti installano.
- Per provare una modifica senza toccare i progetti: una sessione con
  `claude --plugin-dir C:\projects\keep_fresh\plugins\keep-fresh`.
- `python plugins/keep-fresh/tests/selftest.py` deve stampare `self-test: OK`.
- **Rilascio**: versione aumentata in **tutti e due** i `plugin.json` (il self-test
  controlla che coincidano), merge su `master`, push.
