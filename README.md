# agent_context_init

Prepara un repository git perché gli agenti di programmazione ci lavorino con un contesto
che non marcisce: documenti di contesto, un lint che controlla che dicano ancora il vero,
e hook che mettono lo stato del lavoro davanti all'agente e gli impediscono di chiudere
un turno se il codice è cambiato e lo stato no.

Lo script fa solo la meccanica. Il contesto lo scrive l'agente, seguendo la guida che lo
script installa.

> **Stato delle verifiche.** Provato su **Windows 11** con **Python 3.14**, in repository
> finti: lo script e gli hook eseguiti a mano, e sessioni vere di **Claude Code 2.1.274**
> (headless, `claude -p`) e **Codex 0.154.0** (`codex exec`), in cui l'hook di avvio ha
> iniettato lo stato e quello di fine turno ha bloccato dopo una modifica al codice. Non
> provato: macOS, Linux, le sessioni interattive. I comandi per shell POSIX qui sotto sono
> dedotti, non eseguiti.

## Uso in breve

Serve **git**, e **Python 3.14** o successivo raggiungibile come `python` su Windows e
`python3` altrove: è il nome che lo script scrive negli hook. Il minimo tecnico è 3.11,
perché lint e hook leggono `config.toml` con `tomllib`, ma è provato solo con 3.14. Il
Python di sistema di macOS (3.9) non basta. La diagnosi dovrebbe segnalarlo, ma questo
controllo non è ancora stato provato su un Mac.

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
| `scripts/agent_hooks.py` | gestito | come sopra. Gli hook, uguali per ogni agente |
| `docs/agent_docs_guide.md` | gestito | come sopra. La guida che l'agente esegue |
| `scripts/agent_context_version.json` | gestito | come sopra. Quale versione dello script ha scritto i file gestiti |
| `docs/context/status.md` | **seme** | scritto solo se manca, mai sovrascritto, nemmeno con `--force` |
| `docs/context/config.toml` | **seme** | come sopra. La taratura fatta a mano |
| `.claude/settings.local.json` | **fuso** | aggancio degli hook per Claude Code; lascia intatto il resto. Non tracciato da git |
| `.codex/hooks.json` | **fuso** | aggancio degli hook per Codex, come sopra |
| `.claude/settings.json` | ripulito | toccato solo per **togliere** i nostri hook, se una versione vecchia ce li aveva messi |
| `.claude/hooks/*.py` | ritirato | script di hook della versione precedente: `--force` li toglie, se nessun aggancio li usa più |
| `.gitignore` | fuso | aggiunge i due file di aggancio se mancano |

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

## Gli agenti

Gli hook sono gli stessi per tutti gli agenti (`scripts/agent_hooks.py`). Cambia solo dove
si agganciano, e cosa resta da fare a te:

| Agente | Aggancio | Cosa devi fare tu |
|---|---|---|
| Claude Code | `.claude/settings.local.json` | niente: partono alla sessione successiva |
| Codex | `.codex/hooks.json` | aprire Codex nel repository, **fidarti del progetto**, e con `/hooks` **approvare** i due hook. Da rifare se il file cambia |

Codex, senza progetto fidato e hook approvati, **salta gli hook del repository senza
avvisare** (provato il 2026-09-17, Codex 0.154.0, Windows). La diagnosi dello script
controlla se il progetto risulta fidato in `~/.codex/config.toml`; l'approvazione degli
hook non la può vedere.

Codex legge `AGENTS.md` da solo. Claude Code legge `CLAUDE.md`, quindi gli serve un
`CLAUDE.md` che importi `AGENTS.md`: lo scrive l'agente seguendo la guida.

Un'osservazione non ancora risolta: nella prova con `codex exec` e sandbox
`workspace-write`, su Windows, Codex ha rifiutato qualunque comando, anche di sola
lettura (`blocked by policy`). In quelle condizioni non potrebbe nemmeno lanciare il lint.

## Se il repository passa da una macchina all'altra

Il comando di un hook contiene interprete e percorso assoluto dello script, che sono fatti
della macchina. Per questo gli hook si agganciano nei file locali degli agenti, che git non
traccia, e non in quelli condivisi. **Su ogni macchina, dopo il clone, lancia lo script
una volta** (e per Codex rifai fiducia e approvazione). Finché non lo fai, quel clone non
ha hook. Lo stesso vale se sposti la cartella del repository: la diagnosi lo segnala.

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

Una differenza da conoscere: la versione vecchia sorvegliava solo le directory scritte nel
lint (`CODE_DIRS`, `CODE_FILES`), mentre adesso il codice si rileva da solo. Quello che la
rilevazione prende e il lint vecchio lasciava fuori finisce in `[code] exclude`, perché
spesso era escluso di proposito (per esempio un archivio congelato che contiene simboli
banditi). Lo script lo elenca: se una di quelle voci è codice, toglila.

Dalla versione precedente lo script toglie anche `.claude/hooks/`, compresi i `.pyc`, e
segnala le altre copie di `agent_context_init.py` nel repository diverse da quella che
stai lanciando. Una copia versionata nel progetto, tenuta per agganciare gli hook sui
cloni, va sostituita con quella nuova. Il prompt stampato alla fine chiede all'agente di
**allineare** il contesto esistente, non di riscriverlo.

Provato il 2026-09-23 su Windows su un progetto vero con il contesto della versione
precedente. Dopo l'aggiornamento il lint esce pulito, e in una sessione di Claude Code
(`claude -p`) sono partiti l'hook di avvio e quello di fine turno. Codex non l'ho provato
su quel progetto.

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
dell'agente e guarda `.git/agent-hooks.log`: è lì che gli hook scrivono cosa hanno fatto,
una riga per esecuzione con il nome dell'agente.
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
- **Gli hook non partono e `.git/agent-hooks.log` resta vuoto**: quasi sempre lo script
  non è mai stato lanciato su questa macchina. Con Codex, il progetto non è fidato o gli
  hook non sono approvati (`/hooks`). Se il log resta vuoto anche dopo, la diagnosi dice
  quale interprete gli hook invocano e se qui funziona.
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
fine turno e di avvio, aggancio di ogni agente, versione registrata e deriva segnalata. Se qualcosa non va, esce con
errore invece di dire "fatto".

Perché il timbro nomini un commit che contiene davvero il payload impacchettato:

1. modifica `payload/`, lancia `--pack` finché la prova a vuoto passa;
2. committa `payload/` e `agent_context_init.py`;
3. rilancia `--pack`: ora `payload/` è committato e il timbro lo dice;
4. committa `agent_context_init.py`.

Se impacchetti con `payload/` modificato, il timbro lo dichiara (`payload con modifiche NON
committate`) e `--pack` lo ricorda. Il contenuto resta comunque identificato dall'hash.
