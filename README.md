# keep-fresh

Skill per agenti di programmazione, il cui motore è lo script `agent_context_init.py`.

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

## Come skill di Claude Code

La radice di questo repository **è** la cartella della skill: `SKILL.md` sta accanto a
`agent_context_init.py`. Perché Claude Code la veda, la cartella deve comparire in
`~/.claude/skills/` con il nome `keep-fresh`. Un collegamento basta, e le modifiche al
repository valgono subito (la documentazione di Claude Code dice che segue le cartelle di
skill collegate con link simbolici).

```powershell
# Windows, PowerShell: giunzione, non richiede privilegi (non ancora provato)
New-Item -ItemType Junction -Path "$HOME\.claude\skills\keep-fresh" -Target "C:\projects\keep_fresh"
```

```sh
# macOS / Linux (non provato)
ln -s ~/projects/keep_fresh ~/.claude/skills/keep-fresh
```

Se invece la installi **copiando** i tre file che servono (`SKILL.md`,
`agent_context_init.py`, `README.md`), la copia resta indietro a ogni modifica del
repository. `deploy.py` la riallinea, in `~/.claude/skills` e in `~/.claude-lavoro/skills`
(salta quelle che non esistono sulla macchina):

```powershell
python deploy.py --check     # confronta soltanto; esce con 1 se una copia e' indietro
python deploy.py --dry-run   # dice cosa copierebbe
python deploy.py             # copia dove c'e' differenza
```

Non scrive in una destinazione che è un collegamento (modificherebbe il repository) e non
cancella i file in più. Provato su Windows 11, Python 3.14.7, in cartelle di prova.

Poi `/keep-fresh` dentro il progetto da preparare. La skill è **solo manuale**
(`disable-model-invocation: true`): l'agente non la attiva da solo e la sua descrizione
non entra nel contesto delle sessioni, perché serve di rado. Lancia lo script sul repository della cartella
corrente, prima a vuoto, e chiede conferma prima di scrivere. La procedura è in `SKILL.md`.

### I comandi della skill

Si scrivono in Claude Code, con la barra. Gli argomenti non hanno trattini davanti, salvo le
opzioni indicate:

| Comando | Cosa fa |
|---|---|
| `/keep-fresh` | installa o aggiorna l'impianto nel repository corrente: prova a vuoto, conferma, poi scrive |
| `/keep-fresh status` | stato dell'impianto, in sola lettura (vedi sotto); include quanti handoff aperti ci sono |
| `/keep-fresh handoff` | scrive l'handoff della sessione che stai chiudendo |
| `/keep-fresh handoff --elenco` | elenca gli handoff aperti, con numero, data, branch e titolo |
| `/keep-fresh handoff --scarta [n\|parola]` | scarta un handoff; senza argomento, solo se ce n'è uno |
| `/keep-fresh resume [n\|parola]` | riprende un handoff; senza argomento, solo se ce n'è uno |
| `/keep-fresh resume [n\|parola] --comunque` | lo riprende anche se è scritto su un altro branch o su un HEAD che non è nel tuo storico |

`n` è il numero dell'elenco; `parola` una parola del titolo (se sta in più titoli, la skill
li elenca e ti chiede quale). Di solito `--comunque` non lo scrivi: se `resume` si ferma per
un branch o un HEAD diverso, l'agente te lo dice e, se rispondi di sì, rilancia lui con
`--comunque`.

`/keep-fresh status` e `--status` sono la stessa cosa: la forma con i trattini è quella dello
script, che si lancia da terminale (vedi "Le opzioni").

## Controllare che funzioni: `--status`

```powershell
python agent_context_init.py --status      # o: /keep-fresh status
```

Stato dell'impianto nel repository corrente, **in sola lettura**: layout, versione installata
e se coincide con questa copia, file gestiti, hook agganciati per ogni agente con la data
dell'ultima esecuzione (dalla traccia `.git/agent-hooks.log`) e l'ultimo `Stop`, esito del
lint con freschezza di `status.md` e peso dell'iniezione, copie dell'inizializzatore diverse.
In fondo l'elenco "da sistemare". Esce 0 se non c'è niente da sistemare, 1 altrimenti.

L'ultima esecuzione è l'unico segnale per gli hook, che sono fail-open: se smettono di
partire non danno errori, e l'ultima riga della traccia diventa vecchia.

Provato su Windows 11, Python 3.14.7: su un progetto vero (6077 file, `.git` compreso:
nessun file cambiato dopo l'esecuzione) e in repository finti: senza impianto, con layout
precedente, dopo la migrazione. La sola lettura è nella prova a vuoto, verificata anche in
negativo. Non provato su macOS/Linux.

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

Due posti, di proposito. **`.keep-fresh/`** è la meccanica: script, taratura, guida, versione.
La installa lo script, nessuno la scrive a mano, e si riconosce e si rimuove in un colpo
solo. **`docs/keep-fresh/context/`** è il contesto: lo scrive l'agente, lo leggono gli
agenti e le persone (`status.md`, `architecture.md`, `conventions.md`...).

| Percorso | Categoria | Regola |
|---|---|---|
| `.keep-fresh/scripts/docs_lint.py` | gestito | scritto se manca; `--force` lo aggiorna |
| `.keep-fresh/scripts/context_core.py` | gestito | come sopra. Comune a lint e hook: dove sta il codice |
| `.keep-fresh/scripts/agent_hooks.py` | gestito | come sopra. Gli hook, uguali per ogni agente |
| `.keep-fresh/scripts/context_cost.py` | gestito | come sopra. Quanto pesa il contesto, misurato |
| `.keep-fresh/scripts/handoff.py` | gestito | come sopra. Gli handoff fra sessioni, in `.git/keep-fresh-handoff/` |
| `.keep-fresh/guide.md` | gestito | come sopra. La guida che l'agente esegue |
| `.keep-fresh/version.json` | gestito | come sopra. Quale versione dello script ha scritto i file gestiti |
| `docs/keep-fresh/context/status.md` | **seme** | scritto solo se manca, mai sovrascritto, nemmeno con `--force` |
| `.keep-fresh/config.toml` | **seme** | come sopra. La taratura fatta a mano |
| `.claude/settings.local.json` | **fuso** | aggancio degli hook per Claude Code; lascia intatto il resto. Non tracciato da git |
| `.codex/hooks.json` | **fuso** | aggancio degli hook per Codex, come sopra |
| `.claude/settings.json` | ripulito | toccato solo per **togliere** i nostri hook, se una versione vecchia ce li aveva messi |
| `.claude/hooks/*.py` | ritirato | script di hook della versione precedente: `--force` li toglie, se nessun aggancio li usa più |
| `.gitignore` | fuso | aggiunge i due file di aggancio se mancano |

`AGENTS.md` e `CLAUDE.md` non li scrive lo script: li scrive l'agente, perché dipendono da
cosa c'è nel repository.

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

Il file è un seme: nessun aggiornamento lo sovrascrive. Un repository inizializzato prima
del tetto non ha la sezione `[context]`: vale il tetto di partenza, e la si aggiunge a
mano solo per cambiarlo.

## Quanto pesa il contesto: `.keep-fresh/scripts/context_cost.py`

```powershell
python .keep-fresh/scripts/context_cost.py            # resoconto, non chiama nessun modello
python .keep-fresh/scripts/context_cost.py misura     # misura esatta dei token fissi (circa $0,40)
python .keep-fresh/scripts/context_cost.py --giorni 30 --anche C:\vecchio\percorso
```

Il resoconto legge le trascrizioni di Claude Code e i `token_count` di Codex delle sessioni
aperte in questo repository, anche in una sua sottocartella o dove stava prima di essere
spostato, se le trascrizioni sono nella cartella che Claude Code intesta al percorso di
adesso. Per ogni sessione: chiamate, contesto all'avvio e massimo, token scritti e letti in
cache, costo a listino API. Poi le letture dei documenti di contesto e l'andamento
dell'iniezione, dalla traccia degli hook.

Ogni numero è marcato **[misurato]**, cioè registrato dall'agente o dalla misura esatta, o
**[stimato]**, cioè calcolato. Come lo si sa:

- **token e costo delle sessioni:** confrontati con il costo che Claude Code calcola da
  sé (`claude -p --output-format json`) su sessioni con scrittura e lettura in cache.
  Coincidevano alla settima cifra decimale per Opus 5.5, Opus 5, Sonnet 5 e Haiku 4.5
  (Windows 11, Claude Code 2.1.283, 2026-09-26/28). Per gli altri modelli del listino il
  resoconto dice che il prezzo non è verificato. Per Codex dà i token, non i costi;
- **`misura`:** lancia Claude Code headless in una copia usa e getta, vuota, con
  `AGENTS.md`/`CLAUDE.md` e con l'iniezione, e sottrae i totali. Ogni strato è misurato
  due volte e le due misure devono coincidere, o la misura si ferma senza salvare. I
  server MCP dell'utente restano fuori: il 2026-09-28 entravano nel contesto solo in
  alcune esecuzioni, circa 3.000 token, e hanno fatto fallire due misure su tre prima
  della correzione. Due misure della stessa copia hanno
  dato 1.302 e 1.300 token per le istruzioni e 2.142 per l'iniezione in entrambe: la
  precisione è di pochi token. Il risultato va in `.git/context-cost.json`, legato al
  contenuto: se i file cambiano, il resoconto torna a stimare e lo dice;
- **non provato:** macOS e Linux; Codex nella `misura`, che oggi usa solo Claude Code.

## Cambiare sessione senza perdere il filo: handoff

Quando il contesto di una sessione è troppo grande, conviene aprirne una nuova. Per non
perdere il filo:

1. L'hook `prompt` ferma il messaggio **una volta per sessione** quando il contesto supera
   `handoff_warn_tokens` (150.000 token di partenza) e propone `/keep-fresh handoff`.
2. `/keep-fresh handoff`: l'agente scrive in `.git/keep-fresh-handoff/` un file con obiettivo,
   fatto, decisioni, vicoli ciechi e prossimo passo. Poi fai `/clear` o apri una sessione nuova.
3. Nella sessione nuova l'hook di avvio accoda **un indice** (una riga per handoff aperto,
   al massimo cinque). Non ne legge il contenuto e non agisce: se parli d'altro, lo ignora.
4. `/keep-fresh resume [n|parola]` riprende quello che scegli. Se è scritto su un altro
   branch o su un HEAD che non è nel tuo storico, lo dice e non lo consuma;
   `/keep-fresh resume [n|parola] --comunque` lo riprende lo stesso.

Si possono avere più handoff in coda. Ognuno è `aperto`, poi `ripreso` o `scartato`
(`/keep-fresh handoff --scarta [n|parola]`); oltre `handoff_ore` (48 di partenza) non
compare più nell'indice, ma nominandolo si riprende ancora; i chiusi e gli scaduti da più
di `handoff_prune_giorni` (30) si cancellano da soli all'avvio. Le tre chiavi stanno in
`[context]` di `config.toml`, commentate con il loro valore.

Gli handoff sono **locali**: stanno in `.git/`, non finiscono in un commit e non passano
da una macchina all'altra. `/keep-fresh status` dice quanti ce ne sono, `/keep-fresh handoff
--elenco` li mostra uno per uno.

- **provato:** Windows, con i collaudi di `--pack`: ciclo `new` → `resume`, indice, soglia,
  scadenza, pulizia, branch diverso, repository senza commit, file rotti;
- **non provato:** Codex (il formato del blocco in `prompt` è quello della documentazione),
  macOS e Linux, e il comportamento della sessione vera di Claude Code oltre i collaudi.

## Gli agenti

Gli hook sono gli stessi per tutti gli agenti (`.keep-fresh/scripts/agent_hooks.py`), e sono tre:

- **all'avvio** (`SessionStart`) inietta lo stato del lavoro da `status.md`;
- **a fine turno** (`Stop`) blocca una volta se il codice è cambiato e `status.md` no;
- **prima di un tuo messaggio** (`UserPromptSubmit`), se la sessione riprende dopo una
  pausa più lunga della cache con più di 100 mila token di contesto (soglia in
  `config.toml`), ferma il messaggio **una volta** e dice quanto costa riprendere. Se lo
  reinvii passa; se non ti serve tutto quel contesto, `/clear` non chiama il modello e
  riparte dallo stato. Provato su Claude Code 2.1.283 (Windows, 2026-09-28) con una
  sessione vera ripresa dopo una pausa simulata; su Codex non provato.

Cambia solo dove si agganciano, e cosa resta da fare a te:

| Agente | Aggancio | Cosa devi fare tu |
|---|---|---|
| Claude Code | `.claude/settings.local.json` | niente: partono alla sessione successiva |
| Codex | `.codex/hooks.json` | aprire Codex nel repository, **fidarti del progetto**, e con `/hooks` **approvare** gli hook. Da rifare se il file cambia |

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

Il comando di un hook contiene il nome dell'interprete (`python` su Windows, `python3`
altrove), che è un fatto della macchina. Per questo gli hook si agganciano nei file locali
degli agenti, che git non traccia, e non in quelli condivisi. **Su ogni macchina, dopo il
clone, lancia lo script una volta** (e per Codex rifai fiducia e approvazione). Finché non
lo fai, quel clone non ha hook.

Il comando non contiene percorsi: la radice del repository la trova git a ogni esecuzione,
da qualunque sottocartella parta la sessione. Spostare o rinominare la cartella non rompe
gli hook. Le versioni precedenti scrivevano il percorso assoluto dello script: rilanciando
lo script, il comando viene riscritto, e la diagnosi segnala quelli rimasti.

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

### Dal layout precedente (script in `scripts/`, contesto in `docs/context/`)

Fino alla versione `3ada75c` gli script stavano in `scripts/`, la guida in `docs/` e il
contesto in `docs/context/`. Un repository così **si rifiuta di migrare senza `--force`** e
non scrive niente, perché la migrazione sposta dei file. Prima la prova a vuoto, poi vera:

```powershell
python agent_context_init.py --dry-run     # dice cosa sposterebbe
python agent_context_init.py --force
```

Cosa fa: sposta `docs/context/` in `docs/keep-fresh/context/` e `docs/context/config.toml`
in `.keep-fresh/config.toml`, con `git mv` (la storia dei file resta); toglie i vecchi file
gestiti, ma solo se riconosce che sono i nostri; riscrive l'aggancio degli hook sul nuovo
script; riscrive i **link relativi** dei documenti `.md` che lo spostamento rompe, anche nei
piani storici (il loro testo non si tocca, i link restano navigabili). **Non tocca** gli altri file di `scripts/`, che nei progetti sono pieni di roba
propria, né le copie dell'inizializzatore.

Cosa **non** fa: riscrivere i documenti che citano ancora i vecchi percorsi. Li elenca fra i
punti aperti del prompt finale, e li sistema l'agente. I piani e le specifiche storici non
si riscrivono. Dopo la migrazione, `git status` mostra rinomine e cancellazioni già in
indice: è voluto, il commit lo fai tu. Finché non committi, l'hook di fine turno non
blocca, perché `status.md` risulta già toccato.

Provato su Windows 11, Python 3.14.7, in repository finti usa e getta: layout generato con
lo script del commit `093967c`, stato e taratura scritti a mano. Non provato su
macOS/Linux, né sui progetti veri.

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

L'inizializzazione registra il timbro in `.keep-fresh/version.json` del
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
| `--status` | stato dell'impianto in sola lettura (è `/keep-fresh status`); esce 1 se c'è qualcosa da sistemare |

### Gli handoff da terminale: `.keep-fresh/scripts/handoff.py`

È lo script che la skill usa per `handoff` e `resume`. Si lancia dal repository (`python3` su
macOS/Linux), e serve solo se vuoi gestire gli handoff senza passare dall'agente:

| Comando | Cosa fa |
|---|---|
| `handoff.py new --title "..."` | crea il file con i metadati di adesso e ne stampa il percorso; il corpo lo scrive l'agente |
| `handoff.py list` | gli handoff aperti e non scaduti, branch corrente per primo; segnala i file illeggibili |
| `handoff.py list --all` | anche quelli ripresi, scartati o scaduti |
| `handoff.py resume [n\|parola]` | stampa l'handoff e lo segna ripreso; esce 1 se la scelta è ambigua o se branch/HEAD non coincidono |
| `handoff.py resume [n\|parola] --comunque` | lo riprende anche con branch o HEAD diversi |
| `handoff.py discard [n\|parola]` | lo segna scartato |
| `handoff.py prune` | cancella ripresi, scartati e scaduti più vecchi di `handoff_prune_giorni` (gira già da sola all'avvio) |

Corrispondenza con la skill: `handoff` → `new` + il corpo scritto dall'agente; `handoff
--elenco` → `list`; `handoff --scarta` → `discard`; `resume` → `resume`. `prune` e `list --all`
non hanno un comando della skill.

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
