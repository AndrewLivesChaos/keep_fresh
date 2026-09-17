# agent_context_init

Prepara un repository git perché gli agenti di programmazione ci lavorino con un contesto
che non marcisce: documenti di contesto, un lint che controlla che dicano ancora il vero,
e hook che mettono lo stato del lavoro davanti all'agente e gli impediscono di chiudere
un turno se il codice è cambiato e lo stato no.

Lo script fa solo la meccanica. Il contesto lo scrive l'agente, seguendo la guida che lo
script installa.

> **Stato delle verifiche.** Provato su **Windows 11** con **Python 3.14**, eseguendo lo
> script e gli hook a mano in repository finti. Gli hook sono scritti per **Claude
> Code**. Non provato: macOS, Linux, Codex. I comandi per shell POSIX qui sotto sono
> dedotti, non eseguiti.

## Uso in breve

Serve **git**, e **Python 3.14** o successivo raggiungibile come `python` su Windows e
`python3` altrove: è il nome che lo script scrive negli hook.

Copia `agent_context_init.py` nel repository e lancialo da lì dentro:

```powershell
# Windows, PowerShell
python agent_context_init.py --dry-run
python agent_context_init.py
```

```sh
# macOS / Linux (non provato)
python3 agent_context_init.py --dry-run
python3 agent_context_init.py
```

`--dry-run` dice cosa farebbe senza scrivere niente. Alla fine lo script stampa una
diagnosi di ciò che non funziona ancora e **il prompt da incollare all'agente**.

### Anche in una cartella vuota

Un progetto appena nato va bene: basta `git init` prima. Lo script non ha bisogno di
codice, perché **dove sta il codice non lo scrive da nessuna parte**. Lo rilevano il lint
e gli hook a ogni esecuzione, dai file che git conosce: una cartella creata domani viene
vista domani, senza rilanciare niente.

L'unica cosa che manca in un repository senza commit è il marcatore di freschezza di
`status.md`, perché non c'è ancora uno sha a cui ancorarlo. Dopo il primo commit,
rilancia lo script una volta: lo aggiunge da solo, se `status.md` è ancora lo scheletro.

## Cosa scrive

| Percorso | Categoria | Regola |
|---|---|---|
| `scripts/docs_lint.py` | gestito | scritto se manca; `--force` lo aggiorna |
| `scripts/context_core.py` | gestito | come sopra. Comune a lint e hook: dove sta il codice |
| `.claude/hooks/*.py` | gestito | come sopra |
| `docs/agent_docs_guide.md` | gestito | come sopra. La guida che l'agente esegue |
| `scripts/agent_context_version.json` | gestito | come sopra. Quale versione dello script ha scritto i file gestiti |
| `docs/context/status.md` | **seme** | scritto solo se manca, mai sovrascritto, nemmeno con `--force` |
| `docs/context/config.toml` | **seme** | come sopra. La taratura fatta a mano |
| `.claude/settings.local.json` | **fuso** | ci aggiunge i due hook, lascia intatto il resto. Non tracciato da git |
| `.claude/settings.json` | ripulito | toccato solo per **togliere** i nostri hook, se una versione vecchia ce li aveva messi |
| `.gitignore` | fuso | aggiunge `.claude/settings.local.json` se manca |

`AGENTS.md` e `CLAUDE.md` non li scrive lo script: li scrive l'agente, perché dipendono da
cosa c'è nel repository.

## La taratura: `docs/context/config.toml`

Il lint rileva il codice da solo e lo dice nel controllo 0. Se sbaglia, si corregge in
`[code]`: `include` per percorsi che deve considerare codice (una directory che inizia con
un punto, file senza estensione riconosciuta), `exclude` per quelli che non deve
considerare (codice generato, librerie copiate).

Le quattro tabelle `[lint.*]` partono **vuote di proposito**: sono lavoro di dominio, e si
riempiono guardando i falsi positivi del primo giro di lint, con il motivo scritto accanto
a ogni voce.

Il file è un seme: nessun aggiornamento lo sovrascrive.

## Se il repository passa da una macchina all'altra

Il comando di un hook contiene il nome dell'interprete, che è un fatto della macchina. Per
questo gli hook si agganciano in `.claude/settings.local.json`, che git non traccia, e non
in `.claude/settings.json`. **Su ogni macchina, dopo il clone, lancia lo script una
volta.** Finché non lo fai, quel clone non ha hook.

Dichiarare gli hook in tutti e due i file non è innocuo: girano due volte (misurato su
Claude Code 2.1.269, Windows, 2026-09-11). Se il repository veniva da una versione vecchia
che li metteva nel file condiviso, lo script li sposta e lo dice; la rimozione compare nel
`git diff` ed è voluta.

## Aggiornare un repository già inizializzato

Copia lo script nuovo e rilancialo con `--force`:

```powershell
python agent_context_init.py --force
```

Aggiorna i file gestiti e non tocca i semi. Da una versione che teneva la taratura dentro
gli script, le liste di eccezioni vengono **migrate** in `config.toml` al primo giro, prima
che `--force` riscriva il lint. Guarda comunque il `git diff` prima di committare.

Una differenza da conoscere: la versione vecchia sorvegliava solo le directory rilevate il
giorno dell'installazione, e il lint solo `src` e `drivers`. Adesso è sorvegliato tutto il
codice, compresi script e file di build nella radice. Il lint e l'hook di fine turno
possono quindi segnalare commit che prima ignoravano; se non sono codice per te, vanno in
`[code] exclude`.

## Quale versione è installata

Ogni copia dello script porta un **timbro**, scritto da `--pack`: data, repository sorgente,
commit, se `payload/` aveva modifiche non committate, e un hash del contenuto installato.
Due copie con lo stesso hash installano gli stessi file.

```powershell
python agent_context_init.py --version
```

L'inizializzazione registra il timbro in `scripts/agent_context_version.json` del
repository di destinazione. Quando rilanci lo script, la diagnosi confronta il
**contenuto** dei file gestiti installati con quello della copia che stai usando, e se
differiscono mostra le due versioni: se la tua è più recente, `--force` aggiorna. Se quei
file sono stati modificati a mano, `--force` cancella le modifiche.

## Verifica

```powershell
python scripts\docs_lint.py
```

Deve uscire senza errori; gli avvisi non fanno fallire. Poi apri una sessione nuova
dell'agente e guarda `.git/claude-hooks.log`: è lì che gli hook scrivono cosa hanno fatto.
A schermo non vedi niente, perché l'iniezione va nel contesto dell'agente. Gli hook sono
**fail-open**: qualunque errore li fa uscire 0, quindi il log è l'unico modo di accorgersi
che non girano.

## Le opzioni

| Opzione | Cosa fa |
|---|---|
| *(nessuna)* | installa nel repository corrente, rispettando i file già presenti |
| `--dry-run` | dice cosa farebbe, non scrive niente |
| `--force` | aggiorna i file gestiti; i semi non vengono mai toccati |
| `--pack` | solo in questo repository: rigenera il payload da `payload/` |
| `--self-test` | verifica che il payload sia leggibile e coincida col timbro, ed esce |
| `--version` | dice da dove e quando viene questa copia ed esce |

## Se qualcosa non torna

- **"Non sei dentro un repository git"**: `git init` prima.
- **"Questo file non ha payload"**: lo script è troncato. Il sentinella del payload
  compare due volte nel sorgente e il taglio va fatto sempre sull'ultima; ricopia il file.
- **Gli hook non partono e `.git/claude-hooks.log` resta vuoto**: quasi sempre lo script
  non è mai stato lanciato su questa macchina. Se il log resta vuoto anche dopo, la
  diagnosi dice quale interprete gli hook invocano e se qui funziona.
- **`settings.local.json` "NON TOCCATO"**: non è JSON valido, o `hooks` non ha la forma
  attesa. Gli hook non sono agganciati: si corregge a mano e si rilancia.
- **Il lint accusa decine di identificatori inesistenti al primo giro**: è normale. Prima
  si corregge la taratura in `config.toml`, poi i documenti. Una segnalazione che descrive
  un difetto vero non si mette a tacere: si registra in `status.md` come lavoro aperto.

## Sviluppare lo strumento

I file installati vivono in `payload/`, con gli stessi percorsi che avranno nel repository
di destinazione. Si modificano lì, poi:

```powershell
python agent_context_init.py --pack
```

`--pack` impacchetta tutto `payload/` in coda allo script, controlla che lo script
riscritto si esegua e rilegga il payload, e poi lo usa su un repository finto dall'inizio:
cartella vuota, primo commit, codice che compare dopo in una directory qualunque, hook di
fine turno e di avvio, versione registrata e deriva segnalata. Se qualcosa non va, esce con
errore invece di dire "fatto".

Perché il timbro nomini un commit che contiene davvero il payload impacchettato:

1. modifica `payload/`, lancia `--pack` finché la prova a vuoto passa;
2. committa `payload/` e `agent_context_init.py`;
3. rilancia `--pack`: ora `payload/` è committato e il timbro lo dice;
4. committa `agent_context_init.py`.

Se impacchetti con `payload/` modificato, il timbro lo dichiara (`payload con modifiche NON
committate`) e `--pack` lo ricorda. Il contenuto resta comunque identificato dall'hash.
