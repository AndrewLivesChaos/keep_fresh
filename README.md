# agent_context_init — come si usa

Portare in un altro repository la struttura di contesto per agenti che questo progetto
usa: `docs/context/`, il lint dei documenti, i due hook di Claude Code.

## Risposta breve

Sì: **basta copiare `scripts/agent_context_init.py` nel repo di destinazione e
lanciarlo.** È un unico file Python senza dipendenze, e i file che deve installare se li
porta dentro, in coda al sorgente (il *payload*). Servono solo tre cose sulla macchina:

- **Python 3** raggiungibile come `python` su Windows, `python3` altrove — è il nome che
  lo script scrive negli hook, e se non risponde a quel nome gli hook non partono;
- **git**, e il repo di destinazione **già inizializzato** (`git init` se non lo è);
- almeno **un commit**, se vuoi il marcatore di freschezza in `status.md` — senza un
  `HEAD` lo script non lo scrive, e lo segnala.

Una cosa conviene saperla subito, perché cambia il modo di usarlo. Gli hook si
dichiarano in `.claude/settings.local.json`, che git non traccia, quindi **non viaggiano
col repo**: lo script va lanciato una volta su ogni macchina, non una volta per
progetto. Il perché sta [più sotto](#se-il-repo-passa-da-una-macchina-allaltra).

Il resto di questo documento serve a due cose: sapere cosa aspettarsi, e non copiare un
payload invecchiato.

## Prima di copiare: rigenera il payload

Il payload è una fotografia dei file di riferimento presa l'ultima volta che qualcuno ha
eseguito `--pack`. Se da allora il lint o gli hook di questo progetto sono cambiati, la
fotografia è vecchia e il repo nuovo nasce indietro.

```powershell
cd C:\progetti\progetto
python scripts\agent_context_init.py --pack
```

`--pack` rilegge i cinque file di riferimento, ne **neutralizza la taratura** (le
costanti specifiche di PROGETTO non devono finire in un altro progetto), riscrive sé stesso,
e poi si verifica: rilegge il proprio payload e monta un repo finto dove fa girare il
lint appena impacchettato. Se una di queste due prove fallisce, esce con errore invece di
dire "fatto".

I cinque file impacchettati sono:

| File | A che serve |
|---|---|
| `scripts/docs_lint.py` | i cinque controlli sui documenti |
| `.claude/hooks/hooklib.py` | funzioni comuni ai due hook |
| `.claude/hooks/session_start.py` | inietta lo stato del lavoro all'avvio della sessione |
| `.claude/hooks/stop_check.py` | blocca la chiusura del turno se il codice è cambiato e lo stato no |
| `docs/agent_docs_guide.md` | le istruzioni che l'agente esegue per **scrivere** il contesto |

Dopo `--pack`, `scripts/agent_context_init.py` risulta modificato: committalo, altrimenti
la prossima copia riparte di nuovo dalla versione vecchia.

## Nel repo di destinazione

```powershell
copy C:\progetti\progetto\scripts\agent_context_init.py C:\percorso\altro_repo\
cd C:\percorso\altro_repo
python agent_context_init.py --dry-run
python agent_context_init.py
```

`--dry-run` stampa tutto quello che farebbe senza scrivere niente. Vale la pena guardarlo
almeno la prima volta, soprattutto la sezione **"Rilevato in questo repo"**: lì lo script
dice quali directory considera codice, quali estensioni ha trovato e cosa sorveglierà
l'hook di Stop. Quei valori finiscono scritti nelle costanti in cima a `docs_lint.py` e
`hooklib.py`. Se ha sbagliato, si correggono a mano lì, non si ritara il progetto.

Lo script può stare ovunque: nella radice, in `scripts/`, dove preferisci. Si orienta con
`git rev-parse`, non con la propria posizione.

### Cosa scrive

| Percorso | Regola |
|---|---|
| `scripts/docs_lint.py` | gestito: se esiste viene rispettato, `--force` lo aggiorna |
| `.claude/hooks/*.py` | gestiti, come sopra |
| `docs/agent_docs_guide.md` | gestito, come sopra |
| `docs/context/status.md` | **seme**: scritto solo se manca, mai sovrascritto, nemmeno con `--force` |
| `.claude/settings.local.json` | **fuso**: ci mette i due hook, lascia intatto il resto. Non è tracciato da git |
| `.claude/settings.json` | toccato solo per **togliere** i nostri hook, se li aveva dalle versioni precedenti |
| `.gitignore` | aggiunge `.claude/settings.local.json` se non c'è |

`AGENTS.md` e `CLAUDE.md` **non** li scrive lo script: li scrive l'agente, seguendo
`docs/agent_docs_guide.md`, perché dipendono da cosa c'è nel repo.

Alla fine lo script fa una **diagnosi** e stampa cosa non funziona ancora. Il caso tipico
è un repo che aveva già un `status.md` o un `settings.json`: vengono rispettati, e proprio
per questo restano senza i marcatori che gli hook usano. Le due cose che la diagnosi
cerca in `docs/context/status.md` sono il commento `context-verified-at` con lo sha, e la
coppia di marcatori `session-start: begin` / `session-start: end` che delimita ciò che
viene iniettato a ogni avvio.

### Poi tocca all'agente

Lo script ha fatto solo la meccanica. Il contesto non esiste ancora: nasce leggendo il
repo e chiedendo all'utente quello che nel repo non c'è — stato del lavoro, decisioni
prese fuori dal codice, verifiche fatte a mano.

L'ultima cosa che lo script stampa è **il prompt da incollare in una sessione
dell'agente**. Usa quello: contiene anche i punti lasciati aperti dalla diagnosi.

Tre costanti del lint partono vuote di proposito, perché sono lavoro di dominio e nessuna
rilevazione automatica le indovina: `NOT_SYMBOLS` (parole in backtick che non sono
simboli), `EXPECTED_ABSENT` (simboli che il codice non deve avere, e il documento cita
per dire proprio quello), `EXTERNAL_SYMBOLS` (simboli di librerie esterne). Si riempiono
guardando i falsi positivi del primo giro di lint, con il motivo scritto accanto a ogni
voce.

### Se il repo passa da una macchina all'altra

Il comando di un hook contiene il nome dell'interprete, e quel nome è un fatto della
macchina: `python` su Windows, `python3` su macOS e Linux. Per questo gli hook non si
dichiarano in `.claude/settings.json`, che git traccia e che quindi porterebbe il nome
in giro, ma in `.claude/settings.local.json`, che resta dov'è. Ogni macchina tiene il
suo, e in git non viaggia niente di specifico.

**Su ogni macchina nuova, dopo il clone, lancia l'inizializzatore una volta.** È l'unico
passo di installazione, e serve proprio perché il file locale non viene clonato.

```powershell
cd C:\percorso\repo_clonato
python agent_context_init.py
```

Il rovescio della medaglia, che è giusto conoscere: **un clone appena fatto non ha
hook** finché non fai quel giro. Niente iniezione dello stato all'avvio, niente
controllo di Stop. È una perdita visibile e uguale su tutte le macchine, e si preferisce
all'alternativa, cioè hook presenti che puntano a un interprete inesistente. Quelli sono
fail-open: non danno errore, semplicemente non fanno niente, e non te ne accorgi.

Se il repo veniva da una versione precedente dello script, gli hook stavano nel file
condiviso. L'inizializzatore li sposta e te lo dice:

```
migrazione: tolti SessionStart, Stop da settings.json (adesso stanno nel file
            locale; dichiarati in due posti girerebbero due volte)
```

Dichiararli in tutti e due i file non è innocuo: girano davvero due volte, misurato su
Claude Code 2.1.269 con una sonda in entrambi i file. La rimozione tocca un file
tracciato, quindi la vedi nel `git diff`: è voluta, e va committata. Permessi e hook di
altri nello stesso file non vengono toccati.

### Verifica finale

```powershell
python scripts\docs_lint.py
```

Deve uscire pulito. Poi apri una sessione nuova dell'agente e guarda
`.git/claude-hooks.log`: è lì che gli hook scrivono cosa hanno fatto. A schermo non vedi
niente, perché l'iniezione va nel contesto dell'agente, non nel tuo terminale. Gli hook
sono **fail-open**: qualunque errore li fa uscire 0, quindi un hook rotto non blocca il
lavoro e non si fa notare. Il log è l'unico modo per accorgersene.

## Aggiornare un repo già inizializzato

Quando il lint o gli hook migliorano qui, si ricopia lo script aggiornato nell'altro repo
e si rilancia con `--force`:

```powershell
python agent_context_init.py --force
```

`--force` riporta lint, hook e guida alla versione di riferimento. **Riporta anche la
taratura ai valori rilevati**, quindi le tre costanti di dominio riempite a mano e ogni
correzione fatta nei blocchi di taratura vanno rimesse: guarda il `git diff` prima di
committare.

`docs/context/status.md` non viene toccato in nessun caso.

## Le opzioni, tutte

| Opzione | Cosa fa |
|---|---|
| *(nessuna)* | installa nel repo corrente, rispettando i file già presenti |
| `--dry-run` | dice cosa farebbe, non scrive niente |
| `--force` | aggiorna i file gestiti alla versione di riferimento |
| `--pack` | nel progetto di riferimento: rigenera il payload dai file veri |
| `--self-test` | verifica che il payload sia leggibile ed esce |

## Se qualcosa non torna

- **"Non sei dentro un repository git"** — `git init` prima.
- **"Questo file non ha payload"** — hai copiato uno script troncato. Il sentinella del
  payload compare due volte nel sorgente e il taglio va fatto sempre sull'ultima; se un
  editor o un copia-incolla ha rovinato la coda, ricopia il file dal progetto di
  riferimento.
- **Gli hook non partono e `.git/claude-hooks.log` resta vuoto** — quasi sempre perché
  su questa macchina lo script non è mai stato lanciato, e il file che dichiara gli hook
  non viene clonato. Lancialo. Se il log non si popola nemmeno dopo, la diagnosi dello
  script dice quale interprete sta invocando e se qui funziona.
- **`settings.local.json` "NON TOCCATO"** — non è JSON valido, o `hooks` non ha la forma
  attesa. Gli hook **non** sono agganciati: si corregge a mano e si rilancia.
- **Gli hook sembrano girare due volte** — sono dichiarati sia nel file locale sia in
  `.claude/settings.json`. Rilancia lo script, che li toglie dal secondo.
- **Il lint accusa decine di identificatori inesistenti al primo giro** — è normale.
  Prima si correggono i controlli (le tre costanti di dominio), poi i documenti. Una
  segnalazione che descrive un difetto vero non si mette a tacere: si registra in
  `status.md` come lavoro aperto.
