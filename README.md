# keep-fresh

*[English](README.en.md)*

**Contesto di progetto per agenti di programmazione che resta vero nel tempo.**
Plugin per **Claude Code** e **Codex**: organizza la documentazione che gli agenti leggono,
la verifica contro il codice e la tiene aggiornata a ogni turno, con un consumo di token
misurato e sotto controllo.

## Il problema

Un agente di programmazione riparte da zero a ogni sessione. Per lavorare bene ha bisogno di
un contesto scritto: cos'è il progetto, le regole da non violare, a che punto è il lavoro.
Quel contesto, però, **invecchia in silenzio**: il codice cambia, i documenti no, e l'agente
segue con fiducia istruzioni che non sono più vere. In più, un contesto cresciuto senza
controllo si paga in token a ogni avvio.

## Cosa fa keep-fresh

- **Struttura il contesto.** Un ingresso unico (`AGENTS.md`) con tabelle di rotta verso
  documenti piccoli e tematici (`docs/keep-fresh/context/`): l'agente carica solo ciò che
  serve al compito, non tutto. Un solo contesto per tutti gli agenti: Claude Code lo legge
  da `CLAUDE.md`, che importa `AGENTS.md`.
- **Lo verifica contro il codice.** Un lint dei documenti controlla che gli identificatori
  citati esistano ancora, che i link risolvano, che ogni affermazione dichiari se è
  verificata, dedotta o assunta, e che lo stato del lavoro non sia rimasto indietro rispetto
  al codice.
- **Lo tiene aggiornato da sé.** Tre hook: all'avvio mettono lo stato del lavoro davanti
  all'agente; a fine turno lo fermano, una volta, se ha cambiato il codice senza aggiornare
  lo stato; prima di un messaggio avvisano quando riprendere una sessione costerebbe caro.
- **Fa passare il lavoro da una sessione all'altra.** Con `/keep-fresh:handoff` l'agente
  scrive dove è arrivato, le decisioni e i vicoli ciechi; una sessione nuova, leggera, lo
  riprende con `/keep-fresh:resume`.
- **Rende misurabile il costo.** `/keep-fresh:cost` dice quanto pesa davvero il contesto,
  sessione per sessione, distinguendo i numeri misurati da quelli stimati.
- **Non sporca il progetto.** Nel repository scrive solo due file iniziali; il codice sta
  nel plugin. Un aggiornamento del plugin arriva a tutti i progetti senza toccarli.

## Prestazioni e consumi

| Voce | Valore | Come è stato ottenuto |
|---|---|---|
| Chiamate al modello fatte dal plugin | **nessuna** (tranne `/keep-fresh:cost misura`, su richiesta, circa $0,40) | per costruzione: hook e lint sono script Python locali |
| Durata di un hook | **0,2–0,3 s** (avvio ~0,27 s, fine turno ~0,20 s) | misurata, repository piccolo, Windows 11, Python 3.14; cresce con le dimensioni del repository |
| Durata del lint | **~0,25 s** | misurata, stesse condizioni |
| Contesto iniettato all'avvio | **al massimo 8.000 caratteri** (circa 2.000–2.500 token) | tetto configurabile; oltre, solo un indice dei blocchi, e il lint lo segnala |
| Dipendenze | **nessuna** oltre Python e git | libreria standard di Python |

Dove si risparmia:

- **Il tetto all'iniezione.** In un progetto reale, prima del tetto, i blocchi caricati a
  ogni avvio erano arrivati a circa 134.000 caratteri, dell'ordine di 60.000 token pagati a
  ogni sessione. Con il tetto restano poche migliaia di token, e il lint indica cosa
  accorciare.
- **La ripresa dopo una pausa.** Quando la cache dei prompt è scaduta, il primo messaggio
  riscrive in cache l'intero contesto invece di leggerlo: sul listino Anthropic una
  scrittura in cache costa da 12,5 a 20 volte una lettura. Se il contesto è grande, l'hook
  ferma il messaggio una volta e dice quanto costerà; il messaggio fermato non arriva al
  modello e non costa niente. Reinviato, passa.
- **L'handoff.** Oltre una soglia (150.000 token di partenza) l'hook propone di passare il
  lavoro a una sessione nuova: ogni chiamata successiva rilegge un contesto più piccolo.
- **Il caricamento mirato.** Le tabelle di rotta fanno leggere all'agente solo i documenti
  del compito in corso.

I costi delle sessioni calcolati da `/keep-fresh:cost` sono stati confrontati con quelli che
Claude Code calcola da sé e coincidevano alla settima cifra decimale per Opus 5.5, Opus 5,
Sonnet 5 e Haiku 4.5. Per Codex il resoconto dà i token, non i costi.

## Requisiti

- git;
- Python **3.14** o successivo, raggiungibile come `python` su Windows e `python3` su
  macOS/Linux (il minimo tecnico è 3.11);
- Claude Code o Codex.

La guida per l'agente, le skill e i messaggi degli script sono in italiano.

## Installare

Il repository è il marketplace del plugin; si installa dal ramo `master`.

**Claude Code**, una volta per configurazione:

```bash
claude plugin marketplace add AndrewLivesChaos/keep_fresh
claude plugin install keep-fresh@keep-fresh
```

Claude Code prova prima a clonare via SSH. Su una macchina senza chiave SSH per GitHub
imposta `CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1`, altrimenti gli aggiornamenti dal pannello
`/plugin` possono fallire. Con più configurazioni (`CLAUDE_CONFIG_DIR`) ripeti i due comandi
per ognuna.

**Codex:**

```bash
codex plugin marketplace add AndrewLivesChaos/keep_fresh
codex plugin add keep-fresh@keep-fresh
```

Poi, dentro Codex, apri `/hooks` e approva i tre hook di keep-fresh. **Senza approvazione
Codex li salta senza avvisare.** L'approvazione vale per il plugin, non per il singolo
progetto.

## Primi passi

1. Apri l'agente nella radice del tuo repository git e lancia `/keep-fresh:init`
   (in Codex `$keep-fresh:init`). Fa una prova a vuoto, chiede conferma e scrive i due file
   iniziali.
2. Init stampa un prompt da incollare: con quello l'agente legge la guida del plugin, ti
   chiede ciò che non può dedurre dal codice e scrive il contesto (`AGENTS.md`, `CLAUDE.md`,
   `docs/keep-fresh/context/`).
3. L'agente lancia il lint finché esce pulito. Al primo giro è normale vedere molte
   segnalazioni: si corregge prima la taratura in `.keep-fresh/config.toml`, poi i documenti.
4. Rivedi e committa il contesto e la taratura. Da qui in avanti gli hook lavorano da soli.
5. `/keep-fresh:status` in qualsiasi momento dice se plugin, hook e lint sono a posto.

Funziona anche in una cartella appena creata con `git init`: in un repository senza commit
init fa un commit vuoto `Initial commit`, senza file, per avere un punto di riferimento.

## Comandi

| Comando | Cosa fa |
|---|---|
| `/keep-fresh:init` | prepara il repository corrente: prova a vuoto, conferma, poi scrive i due file iniziali |
| `/keep-fresh:status` | stato in sola lettura: plugin, hook, handoff, lint, cosa sistemare |
| `/keep-fresh:lint` | il lint dei documenti; lo usa anche l'agente da solo |
| `/keep-fresh:handoff` | l'agente scrive dove sei arrivato, per riprendere in una sessione nuova (`--elenco`, `--scarta n`) |
| `/keep-fresh:resume` | riprende un handoff (`n`, una parola del titolo, `--comunque`) |
| `/keep-fresh:cost` | quanto pesa il contesto (`misura`, `--giorni N`) |

In Codex le skill si invocano con `$keep-fresh:<nome>`.

## Come funziona

### Cosa scrive nel progetto

Solo due file, scritti se mancano e mai sovrascritti:

| Percorso | Cos'è |
|---|---|
| `.keep-fresh/config.toml` | la taratura del lint, fatta a mano |
| `docs/keep-fresh/context/status.md` | lo scheletro dello stato del lavoro |

Il resto del contesto lo scrive l'agente. Gli hook non si agganciano nel progetto: li porta
il plugin, e dove manca `.keep-fresh/config.toml` non fanno niente. In `.git/`, quindi fuori
da ogni commit, il plugin tiene la traccia degli hook (`agent-hooks.log`) e gli handoff
(`keep-fresh-handoff/`).

### Il lint

| Controllo | Cosa verifica |
|---|---|
| 0. Configurazione | cosa viene considerato codice |
| 1. Feature bandite | simboli che non devono tornare nel codice |
| 2. Identificatori | ciò che i documenti citano esiste ancora |
| 3. Evidenza | ogni affermazione è marcata verificata, dedotta o assunta |
| 4. Link e ancore | i rimandi risolvono |
| 5. Freschezza | `status.md` non è rimasto indietro rispetto al codice |
| 6. Peso | quanto entra nel contesto a ogni avvio |

### Gli hook

Gli stessi per Claude Code e Codex:

- **all'avvio** (`SessionStart`) inietta lo stato del lavoro da `status.md`, entro il tetto;
- **a fine turno** (`Stop`) blocca una volta se il codice è cambiato e `status.md` no;
- **prima di un tuo messaggio** (`UserPromptSubmit`) avvisa, una volta, se riprendere dopo
  una pausa costerebbe caro o se il contesto ha superato la soglia dell'handoff. Non ferma
  mai un comando `/`.

Sono **fail-open**: un errore interno non blocca mai il lavoro. Per sapere se girano c'è la
traccia `.git/agent-hooks.log`, riassunta da `/keep-fresh:status`.

### La taratura: `.keep-fresh/config.toml`

- `[code]`: `include` ed `exclude` correggono la rilevazione automatica del codice (codice
  generato, librerie copiate, cartelle che iniziano con un punto).
- `[lint.*]`: le eccezioni del lint. Partono **vuote di proposito** e si riempiono guardando
  i falsi positivi del primo giro, con il motivo scritto accanto a ogni voce.
- `[context]`: `max_injection_chars` (8000), `handoff_warn_tokens` (150.000), `handoff_ore`
  (48) e `handoff_prune_giorni` (30). Se il tetto all'iniezione non basta, il rimedio è
  accorciare i blocchi di `status.md`, non alzarlo.

### Quanto pesa il contesto: `/keep-fresh:cost`

```
/keep-fresh:cost                 resoconto, non chiama nessun modello
/keep-fresh:cost --giorni 30     solo le sessioni recenti
/keep-fresh:cost misura          misura esatta dei token fissi (circa $0,40)
```

Il resoconto legge le trascrizioni di Claude Code e i conteggi di token di Codex per le
sessioni aperte nel repository: chiamate, contesto all'avvio e massimo, token scritti e letti
in cache, costo a listino API. Ogni numero è marcato **[misurato]** o **[stimato]**.
`misura` lancia Claude Code headless in una copia usa e getta e confronta i totali con e
senza il contesto; ogni misura è ripetuta due volte e deve coincidere, altrimenti non viene
salvata.

### Handoff

1. Oltre `handoff_warn_tokens` l'hook ferma il messaggio una volta e propone l'handoff.
2. `/keep-fresh:handoff`: l'agente scrive obiettivo, lavoro fatto, decisioni, vicoli ciechi
   e prossimo passo. Poi `/clear` o una sessione nuova.
3. All'avvio l'hook mostra un indice degli handoff aperti (al massimo cinque), senza
   caricarne il contenuto.
4. `/keep-fresh:resume` riprende quello scelto. Se è stato scritto su un altro branch lo dice
   e non lo consuma; `--comunque` lo riprende lo stesso.

Gli handoff restano **locali**, in `.git/`, e non finiscono mai in un commit.

## Aggiornare

```bash
claude plugin update keep-fresh@keep-fresh     # in ogni configurazione di Claude Code
codex plugin marketplace upgrade               # Codex
```

Oppure, in Claude Code, `/plugin` → *Marketplaces* → keep-fresh → *Enable auto-update*.
Un aggiornamento arriva quando cambia la versione del plugin. `config.toml` e `status.md` non
vengono mai toccati.

## Se qualcosa non torna

- **"Non sei dentro un repository git"**: serve `git init` prima.
- **`.git/agent-hooks.log` resta vuoto**: il plugin non è installato o è disattivato in
  quella configurazione (`/keep-fresh:status` lo dice); con Codex, gli hook non sono stati
  approvati con `/hooks`.
- **All'avvio non si vede niente**: è normale. Ciò che l'hook di avvio produce va nel
  contesto dell'agente, non a schermo.
- **Il lint segnala decine di identificatori inesistenti al primo giro**: è normale. Prima si
  corregge la taratura, poi i documenti. Una segnalazione che descrive un difetto vero non si
  mette a tacere: si registra in `status.md` come lavoro aperto.

## Stato delle verifiche

- **Windows 11, Python 3.14**: self-test del plugin; plugin installato dal marketplace in
  Claude Code 2.1.308 e Codex 0.154.0, con gli hook verificati in sessioni reali.
- **macOS**: installazione dal marketplace riuscita; funzionamento degli hook non ancora
  verificato.
- **Linux**: non provato.
- La misura esatta di `/keep-fresh:cost` usa solo Claude Code.

## Sviluppare keep-fresh

```
.claude-plugin/marketplace.json      marketplace per Claude Code
.agents/plugins/marketplace.json     marketplace per Codex
plugins/keep-fresh/                  il plugin
  .claude-plugin/plugin.json         manifesto Claude Code (version)
  .codex-plugin/plugin.json          manifesto Codex (version, file di hook)
  hooks/hooks.json                   hook per Claude Code, via hooks/run-hook.cmd
  hooks/codex-hooks.json             hook per Codex
  scripts/                           lint, hook, handoff, costi, init
  skills/<comando>/SKILL.md          una skill per comando
  guide.md                           la guida che l'agente esegue
  templates/config.toml              il file iniziale della taratura
  tests/selftest.py                  il self-test
```

- Si lavora su `develop`; `master` è ciò che gli utenti installano.
- Per provare una modifica senza toccare i progetti: `claude --plugin-dir ./plugins/keep-fresh`
  dalla radice del repository.
- `python plugins/keep-fresh/tests/selftest.py` deve stampare `self-test: OK`.
- **Rilascio**: versione aumentata in **tutti e due** i `plugin.json` (il self-test controlla
  che coincidano), merge su `master`, push.

## Licenza

[MIT](LICENSE).
