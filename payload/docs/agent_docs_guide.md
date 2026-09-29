# Istruzioni per l'agente — creare il contesto di progetto

Sei stato incaricato di organizzare la documentazione per gli agenti AI di questo
progetto. Segui queste istruzioni. Non sono una descrizione di come è fatto un altro
repo: sono il compito da eseguire in questo.

## Obiettivo

Produrre un contesto che l'agente **non debba caricare tutto per fare una cosa sola**,
che non vada duplicato per ogni tool, e che **non marcisca in silenzio**.

Le prime due sono questioni di struttura. La terza è quella che decide se il lavoro sarà
ancora utile fra tre mesi, e non si risolve scrivendo meglio: si risolve costruendo un
piccolo livello che **esegue** invece di ricordare. Se produci solo i documenti, hai fatto
metà del lavoro.

## Risultato atteso

```
AGENTS.md            ingresso canonico: cos'è il progetto + tabelle di rotta
CLAUDE.md            poche righe: rinvio + import verso AGENTS.md (solo se si usa Claude Code)
docs/context/        contesto per l'agente
  invariants.md      regole inviolabili: regola | dove vive | link al perché
  conventions.md     nomi, unità, scelte lessicali, cosa non si rinomina
  development.md     build, test, release, comandi di verifica
  architecture.md    mappa dei moduli, proprietà delle risorse, flusso dei dati
  collaboration.md   come si lavora: tono, git, dove va una cosa nuova
  <sottosistema>.md  un file per sottosistema (quanti ne servono)
  status.md          stato corrente, difetti aperti, registro di collaudo, cronologia
docs/                documentazione dell'applicazione, per le persone

docs/context/config.toml     taratura a mano del lint: eccezioni, correzioni alla rilevazione

scripts/docs_lint.py         IL LIVELLO CHE ESEGUE — i documenti dicono ancora il vero?
scripts/agent_hooks.py       hook di avvio, di fine turno e di ripresa, uguali per ogni agente
scripts/context_core.py      comune a lint e hook: dove sta il codice, marcatori
scripts/context_cost.py      quanto pesa il contesto: sessioni misurate, misura esatta

aggancio degli hook, NON versionato, uno per agente e per macchina:
.claude/settings.local.json  Claude Code
.codex/hooks.json            Codex
```

Adatta i nomi al progetto, non la logica della divisione. **Scrivi gli script in Python**,
non nella shell della piattaforma: devono girare uguali su Windows e su macOS, e due
implementazioni della stessa cosa divergono — che è il problema che tutto questo esiste
per evitare.

## Portare questa struttura su un altro progetto

Non copiare file a mano: c'è **un inizializzatore**, `agent_context_init.py`, che è un
solo file Python senza dipendenze e porta il payload dentro di sé. Lo si copia nel repo e
lo si lancia; funziona anche in un repo appena creato con `git init`, senza codice.

```
<python> agent_context_init.py --dry-run   # dice cosa farebbe
<python> agent_context_init.py             # scrive lint, hook, aggancio, scheletri
```

**`<python>` in questa guida** vuol dire l'interprete della macchina in cui sei: `python` su
Windows, `python3` su macOS e Linux (lì `python` di solito non esiste). Sostituiscilo tu
quando lanci un comando; non riscrivere la guida per farlo.

Crea `scripts/docs_lint.py`, `scripts/agent_hooks.py`, `scripts/context_core.py`, questa
guida, uno scheletro di `status.md`, una `config.toml` vuota, e aggancia gli hook nel file
locale di **ogni agente supportato** (oggi Claude Code e Codex) **con l'interprete giusto
per la macchina** (`python` su Windows, `python3` altrove). Il comando non contiene
percorsi: la radice del repository la trova git a ogni esecuzione, quindi spostare la
cartella non rompe gli hook. Non sovrascrive niente senza `--force`, ed è idempotente. Alla fine stampa il
prompt da incollare e i passi che restano all'utente per ciascun agente.

**L'aggancio degli hook non è versionato, di proposito.** Il comando contiene il nome
dell'interprete, che è un fatto della macchina: in un file tracciato viaggerebbero con il repo e
arriverebbero sbagliati altrove, e gli hook, essendo fail-open, non girerebbero senza
dirlo. Per questo **non dichiarare mai gli hook in un file di configurazione versionato**,
come `.claude/settings.json`: dichiarati sia lì sia nel file locale girano due volte. Il
prezzo è che un clone appena fatto non ha hook finché non si lancia l'inizializzatore una
volta su quella macchina: va detto all'utente.

**Codex salta gli hook del repository senza avvisare** finché il progetto non è segnato
come fidato e gli hook non sono stati approvati dall'utente con `/hooks` dentro Codex; va
rifatto quando `.codex/hooks.json` cambia. L'agente non può farlo al posto dell'utente:
glielo deve dire.

**Su un repo che ha già un contesto** non si perde niente: ogni file esistente viene
rispettato, non sovrascritto. Ma proprio per questo resta **mezzo cablato**, e in modi
silenziosi — è il caso che va gestito bene, non quello del repo vuoto:

- il file locale di un agente, se esiste, va **fuso**: aggiungere solo gli hook
  mancanti e lasciare intatto il resto. Saltarlo perché esiste lascia gli script su disco
  senza che niente li invochi, e gli hook sono fail-open: nessuno se ne accorge.
  Sovrascriverlo cancella i permessi già configurati. Nessuna delle due è accettabile.
- Un `status.md` scritto prima **non ha i marcatori**: né `context-verified-at`, né i
  blocchi `session-start`. Gli hook girano e non hanno niente su cui lavorare.

Per questo l'inizializzatore chiude con una **diagnosi** che elenca cosa non funziona
ancora e come sistemarlo. Senza, l'utente crede di aver finito e ha in mano un impianto
scollegato. Vale come regola generale: uno script che rispetta i file esistenti **deve**
dire cosa ha lasciato a metà.

**Aggiornare un repo gia' inizializzato**: `--force` riscrive i file **gestiti** — lint,
modulo comune, hook, guida — alla versione di riferimento, e **non tocca mai** i file
**seme**, `docs/context/status.md` e `docs/context/config.toml`, che dal primo giorno
contengono lavoro umano. La distinzione fra file gestiti e file seme e' quella che rende
`--force` sicuro da usare: senza, aggiornare uno script significherebbe cancellare lo
stato del progetto o la taratura, e nessuno lo farebbe mai.

E' il caso che si presenta subito: un repo dove la guida era stata copiata a mano tempo
prima ha una versione superata proprio del file che dice all'agente cosa fare. Va
aggiornata, e il resto va lasciato stare.

**Quello che l'inizializzatore NON fa è il contesto.** I documenti nascono solo leggendo
il repo e chiedendo all'utente ciò che nel repo non c'è. Lo script prepara il terreno; il
lavoro lo fa l'agente col prompt che ti stampa.

**Dove sta il codice non si scrive da nessuna parte.** Lint e hook lo rilevano a ogni
esecuzione dai file che git conosce, tracciati e nuovi non ignorati. Un progetto che nasce
vuoto, cresce o si riorganizza resta sorvegliato senza toccare niente. Il lint stampa cosa
ha rilevato nel controllo 0: se sbaglia, si corregge con `[code] include` ed `exclude` in
`docs/context/config.toml`, non modificando gli script.

Restano vuote di proposito le tabelle `[lint.not_symbols]`, `[lint.expected_absent]`,
`[lint.external_symbols]` e `[lint.received_docs]` di `config.toml`: sono lavoro di
**dominio**, non deducibile dall'albero, e si riempiono guardando i falsi positivi del
primo giro di lint. `not_symbols` in particolare contiene parole di prosa nella lingua dei
documenti.

**Non modificare gli script installati.** Sono gestiti: `--force` li riporta alla versione
di riferimento. Una correzione fatta lì dentro si perde al primo aggiornamento; se serve,
va fatta nello strumento, non nella copia.

**Come chiederlo all'agente.** L'inizializzatore stampa il prompt, ed è questo. Due frasi
cambiano l'esito, e vanno messe entrambe:

> Leggi `docs/agent_docs_guide.md` ed eseguilo su questo repository. **Sono istruzioni
> operative, non la descrizione di un altro progetto.** Prima di scrivere, **chiedimi
> quello che non è deducibile dal repo**: stato del lavoro, decisioni prese fuori dal
> codice, verifiche fatte a mano. In `scripts/` trovi già il lint e gli hook
> e **non vanno riscritti**: dove sta il codice lo rilevano da soli, restano da riempire
> solo le liste di dominio in `config.toml`, guardando i falsi positivi del primo giro.

Senza la prima, la guida viene letta come documentazione *sul* progetto di origine invece
che come compito. Senza la seconda, i buchi vengono riempiti per plausibilità invece che
con una domanda — ed è esattamente l'informazione che questa struttura esiste per
conservare.

## Le due categorie, da tenere separate

- **`docs/context/` è per l'agente**: come si lavora *su* questo progetto — struttura,
  scelte e perché, vincoli, stato del lavoro.
- **`docs/` è per le persone**: come si comporta il prodotto verso l'esterno, per chi lo
  integra o ne manutiene il protocollo.

Se un documento serve a entrambi sta in `docs/`, e `docs/context/` ci mette un link.
**Una sola copia, sempre**: due copie divergono e nessuno sa quale vale.

## Da dove prendi il contenuto

In quest'ordine, fermandoti quando hai abbastanza:

1. Un file di istruzioni già esistente (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`, …) —
   spesso è un monolite cresciuto per strati: è la sorgente principale.
2. `README`, documenti in `docs/`, commenti che spiegano un *perché* invece di un *cosa*.
3. La storia git: i messaggi di commit che spiegano una scelta, e i fix ricorrenti sullo
   stesso punto (sono invarianti non scritti).
4. Il codice, per la mappa dei moduli e la proprietà delle risorse condivise.
5. **Chiedi all'utente** quello che non è deducibile da nessuna delle fonti sopra: stato
   del lavoro, decisioni prese fuori dal repo, verifiche fatte a mano, e **qual è la
   regola su commit e push**. Non inventarlo e non dedurlo per plausibilità.

## Come scrivere l'ingresso

`AGENTS.md` è la convenzione condivisa fra tool diversi: il contenuto sta lì, e il file
di ciascun tool è solo un rinvio, e solo per i tool che non leggono `AGENTS.md` da soli.
Codex lo legge da solo, anche partendo da una sottocartella (provato il 2026-09-17 con
Codex 0.154.0). Claude Code legge `CLAUDE.md` e non `AGENTS.md`, secondo la sua
documentazione, quindi gli serve il rinvio. `CLAUDE.md`:

```markdown
Il contesto di progetto è in [`AGENTS.md`](AGENTS.md), unico e condiviso fra tool
diversi. La riga qui sotto lo importa; se l'import non fosse attivo, leggilo dal link.

@AGENTS.md
```

Per aggiungere un tool che non legge `AGENTS.md` basta un file con lo stesso rinvio.
Crea solo quelli dei tool effettivamente in uso: chiedi all'utente quali sono, e verifica
sulla documentazione del tool se legge `AGENTS.md` da solo, invece di darlo per scontato.

Tieni **sia il link sia l'import**: se l'import non venisse espanso, resta un file
leggibile che dice dove andare, invece di un file quasi vuoto che rompe l'ingresso senza
segnalare niente.

**Non usare symlink** per condividere il rinvio fra i file dei vari tool: su Windows senza
modalità sviluppatore git li materializza come file di testo contenenti il path, e
l'ingresso muore in silenzio.

`AGENTS.md` deve essere **agent-agnostic e code-agnostic**: niente nomi di file sorgente,
niente istruzioni rivolte a un tool specifico. Sono le cose che cambiano più spesso, e
ogni volta che cambiano l'ingresso diventa falso.

Il suo cuore è una tabella che mappa **l'intenzione al documento**, non l'argomento al
documento — l'agente arriva con un compito, non con una curiosità:

```markdown
| Prima di… | Leggere |
|---|---|
| **qualsiasi modifica** | [invariants](...) · [conventions](...) · [development](...) |
| orientarsi nel codice | [architecture](...) |
| toccare un sottosistema | un link per sottosistema |
| pianificare lavoro o dichiararlo concluso | [status](...) |
| **dichiarare concluso** un lavoro | esegui il comando di lint dei documenti |
```

## Come scrivere `invariants.md`

È il file che regge tutto il resto. Estrai le regole che, violate, rompono il prodotto
**dai discorsi che le spiegano**, e mettile in una tabella di **tre** colonne: la regola,
**dove vive nel codice**, e il link al documento che dice perché.

```markdown
| Regola | Dove | Perché |
|---|---|---|
| Mai `preferences.begin()` diretto → usa il wrapper | `src/storage.c` | [storage](storage.md#nvs) |
```

Chi legge un file solo legge quello giusto; chi sta per contravvenire ha la motivazione a
un salto. Due misure: se la spiegazione sta nella tabella, è troppo lunga; se la regola
non sta in una riga, non è una regola, è un capitolo — spostala nel file del sottosistema.

La colonna **Dove** contiene **file e simboli, mai `file:riga`**. I numeri di riga
driftano a ogni modifica, e una tabella di invarianti che va corretta a ogni commit smette
di essere letta. Serve a due cose: rende la regola verificabile da uno script, e dice
all'agente dove guardare senza cercare.

### Scrivi i divieti in una forma eseguibile

Se il progetto ha feature bandite — cose che erano lì e non devono tornare — non
descriverle a parole. Scrivi la lista dei **simboli** vietati in un paragrafo di forma
fissa, e falla **leggere dallo script di lint** invece di duplicarla dentro lo script:

```markdown
Nessun riferimento nel codice a: `mt25qu` / `qspi`, `Memory_Flash_*`, FatFs (`ff.h`,
`fs/fs.h`), `USB_MASS_STORAGE`, `ad7779` / `Eeg_*`, `mcumgr` / `smp_bt`.
```

Così il documento **è** il test: aggiungere un divieto è modificare una riga di markdown,
e il controllo si adegua da solo. Duplicare la lista nello script crea due copie che
divergono, che è esattamente il problema che tutta questa struttura esiste per evitare.

## Come dividere il resto

**Per sottosistema** (es. rete, storage, UI, coda di invio), non per tipo di documento
(decisioni, caveat, problemi). Chi lavora arriva da un sottosistema: deve aprire un file
solo e trovarci com'è fatto, perché è fatto così, e cosa non deve fare.

`status.md` è l'unica eccezione, perché "a che punto siamo" è una domanda trasversale.

### `status.md` invecchia male: progettalo per questo

È l'unico file che cresce in modo illimitato — qui, dopo tre settimane, era il più grande
del repo di un ordine di grandezza. Se non è progettato per invecchiare, una sessione nuova
lo legge tutto per rispondere a «a che punto siamo», oppure si ferma alla prima sezione e
crede a uno stato di due settimane fa.

Sei accorgimenti, tutti pagati sul campo:

- **una data di ultimo aggiornamento in testa**, e un rimando esplicito del tipo «se
  riprendi da qui, salta a *Da sapere prima di riprendere*»;
- **una sola sezione dice lo stato corrente**, in una schermata. Il resto è cronologia. Se
  lo stato attuale va ricostruito leggendo la cronologia in ordine, il file ha già fallito;
- **le cose risolte si barrano e, nello stesso commit, escono dalla sezione degli aperti**:
  `~~voce~~ — FATTO il <data>` va nella cronologia, e fra gli aperti resta al più il link.
  Cancellare fa sparire il perché; lasciarle fra gli aperti fa sembrare aperto ciò che non
  lo è, e le fa pagare in token a ogni avvio (vedi sotto);
- **i blocchi `session-start` restano sotto il tetto** di `config.toml`
  (`[context] max_injection_chars`, 8000 caratteri di partenza): lo stato corrente in una
  schermata e i difetti aperti come **indice**, una riga per voce con il link all'ancora
  del dettaglio, che sta fuori dai blocchi. Quello che sta fra i marcatori entra nel
  contesto a ogni avvio, `/clear` e compattazione, e resta in ogni chiamata della sessione.
  Oltre il tetto l'hook inietta solo titoli e prime righe, e il lint avvisa;
- **i registri che crescono in modo illimitato** — collaudo, cronologia — stanno in file
  propri linkati da `status.md` appena superano qualche schermata. `status.md` risponde a
  «a che punto siamo»; se per rispondere va letto un file da centinaia di KB, costa più
  della domanda;
- **un marcatore di freschezza leggibile da una macchina**, in testa al file:

  ```markdown
  <!-- context-verified-at: <sha del commit> -->
  ```

  È il commit fino al quale il documento è stato **riconciliato con il codice**. Chi lo
  riconcilia lo riporta a `HEAD`. Da solo non fa niente: serve perché uno script possa
  dire *«7 commit hanno toccato `src/` da allora»*. Senza, la freschezza resta una
  sensazione; con, è un numero. **È il prerequisito degli hook**: senza marcatore, un hook
  può solo confrontare date di modifica dei file, che è un'euristica debole.

La sezione di stato corrente è quella che si sporca per prima, perché la aggiorna solo chi
si ricorda che esiste. **Va riletta ogni volta che si dichiara concluso qualcosa**, non ogni
tanto.

Cosa succede senza questi accorgimenti, misurato su un repository di questo impianto: in
tre settimane la sezione dei difetti aperti è arrivata a 53 voci, almeno 8 delle quali già chiuse,
e i blocchi iniettati sono passati da 26 mila a 135 mila caratteri [misurato, traccia
degli hook], circa 60 mila token a ogni avvio [stimato]. Ridotti al loro indice pesano
3.096 token [misurato con `context_cost.py misura`, 2026-09-28]. Nessuno se n'era
accorto, perché la crescita si vedeva solo nella traccia: per questo ora c'è un tetto.

### Distingui il livello di evidenza, sempre — e rendilo cercabile

È la proprietà più utile emersa dall'uso, e la più facile da perdere. Non scrivere che una
cosa funziona: scrivi **come lo sai**. Tre livelli bastano, e vanno tenuti distinti anche
dentro la stessa tabella:

- **verificato** — un comando eseguito, con il suo esito e **la data**;
- **dedotto** — un ragionamento fondato sul codice, che nessuno ha ancora messo alla prova;
- **assunto** — un buco dichiarato.

Un test unitario verde e una prova su dispositivo reale non sono la stessa cosa, e scrivere
«collaudato» per entrambi cancella l'unica informazione che serviva. Vale anche per le
build: dire *su quale* è stato fatto un collaudo, perché una prova in debug non dice nulla
sull'offuscamento della release.

**Fissa la forma, non solo il concetto.** Le tre parole si scrivono sempre in grassetto e
sempre uguali. Non è pedanteria: è ciò che trasforma la convenzione in un cruscotto
(`git grep -c '\*\*assunto\*\*'`) e la rende controllabile da uno script — che deve
**fallire se un verificato non porta la data**.

Se il progetto usa anche un lessico di sicurezza nella *conversazione* (`[Certo]`,
`[Probabile]`, `[Ipotesi]`), tieni i due vocabolari separati e falli separare anche dal
lint: quello conversazionale non entra nei documenti. Sono due cose diverse — quanto sei
sicuro adesso mentre parli, e come è nota una cosa scritta.

Serve una **fuga esplicita** per la riga che *parla* della convenzione invece di
applicarla (la legenda, la tabella che descrive il controllo). Usa un marcatore visibile e
cercabile in fondo alla riga, `<!-- docs-lint: ignore -->`, non un'eccezione nascosta
dentro lo script. Se ti serve spesso, la regola è sbagliata, non la riga.

Regola pratica: se stai per scrivere che qualcosa è a posto e non riesci a citare il
comando, la data o chi l'ha guardato, quello che stai scrivendo è una deduzione — segnala
che lo è.

### Il collaudo è un registro, non una lista di cose da fare

Se il progetto ha verifiche manuali ancora da eseguire, non scriverle come checklist. Dalle
**subito** la forma finale, anche se è vuota:

```markdown
| # | Prova | Esito | Data | Chi |
|---|---|---|---|---|
| E1 | ... | — | | |
```

`Esito`: `OK` · `KO` · `—` (non eseguita). Un `OK` senza data e senza nome non vale: è la
stessa regola del livello *verificato*.

Costa cinque minuti farlo ora e significa riscrivere risultati già presi se lo fai dopo.
Su un prodotto con un obbligo di tracciabilità — clinico, industriale, regolato — è la
differenza fra «l'abbiamo provato» e **«possiamo dimostrare di averlo provato»**.

Dentro ogni file: prima com'è fatto, poi perché quella scelta e cosa era stato scartato.
Il *perché* è la parte che il codice non contiene e che nessuno può ricostruire dopo.

## Il livello che esegue

Tutto quello sopra è **convenzione**, e una convenzione vale quanto l'aderenza di chi la
applica. I due modi in cui questa struttura fallisce sono:

1. **Nessuno aggiorna i documenti.** L'utente se ne accorge e deve chiederlo ogni volta.
2. **I documenti mentono.** Una funzione è stata rinominata, il build resta verde, e non
   se ne accorge nessuno finché qualcuno non ci lavora sopra e sbaglia.

Il secondo è il pericoloso: il primo lo vede l'utente, il secondo no. Costruisci due cose,
e **prova che funzionino** prima di dichiararle fatte.

### 1. Il lint dei documenti — è la parte più importante

Uno script, versionato, che non guarda il prodotto ma **i documenti che lo descrivono**.
Sei controlli, in ordine di valore:

| # | Controllo | Cosa intercetta |
|---|---|---|
| 1 | **Feature bandite** | un simbolo vietato tornato nell'albero. Lista letta da `invariants.md`, non duplicata |
| 2 | **Identificatori** | un simbolo o percorso citato fra backtick in `docs/context/` che non esiste più |
| 3 | **Evidenza** | un *verificato* senza data, o il lessico conversazionale entrato in un documento |
| 4 | **Link e ancore** | un rimando o un'ancora che non risolve |
| 5 | **Freschezza** | quanti commit hanno toccato il codice dopo il marcatore `context-verified-at` |
| 6 | **Peso** | quanto testo l'hook di avvio inietta; avvisa se i blocchi `session-start` superano il tetto |

Esce non-zero se trova errori. Le scelte di progetto che contano:

- **Cio' che e' rilevabile si rileva a ogni esecuzione, non si scrive.** Dove sta il
  codice lo dicono i file che git conosce, che gia' distingue le sorgenti da build, cache e
  dipendenze. Una costante scritta al momento dell'installazione e' giusta quel giorno e
  falsa appena il progetto cresce: un repo nato vuoto resterebbe sorvegliato su una
  cartella che non esiste. Lint e hook usano lo **stesso** modulo per rilevarlo, o
  finiscono per rispondere in modo diverso alla stessa domanda.
- **Cio' che non e' rilevabile sta in un file seme** (`config.toml`: i divieti, il
  lessico di prosa, le eccezioni), che parte **vuoto** con il formato e l'obbligo del
  motivo scritti nei commenti, e che nessun aggiornamento sovrascrive. Un elenco vuoto e'
  onesto; un elenco pieno di roba di un altro progetto silenzia i controlli veri.
- **Assenza non e' errore.** `invariants.md` che non c'e' ancora, la sezione dei divieti
  mancante, nessun `verificato`: in un progetto appena inizializzato sono lo stato
  normale. Vanno segnalati come avvisi che dichiarano quale controllo e' inattivo, non
  come errori — o il primo giro esce rosso e nessuno lo guarda piu'.
- **Confronto per sottostringa** sugli identificatori. I documenti citano di proposito la
  coda di un enum lungo (`INFO_ID_STREAM` per `USB_CONNECTION_PACKET_INFO_ID_STREAM`): è
  la regola dell'altitudine, e il controllo deve tollerarla o diventa rumore.
- **Tabelle di eccezioni con il motivo obbligatorio**: `expected_absent` (assente per
  costruzione: un id ritirato, un modulo rimosso) ed `external_symbols` (esiste, ma in una
  libreria, non nel tuo albero). Senza motivo scritto non si aggiunge niente, o in sei mesi
  la lista è una discarica che silenzia i controlli veri.
- **Solo i file tracciati** per il controllo dei link: un documento di appunti non
  versionato non deve far fallire niente.
- **Escludi lo script da sé stesso** nel controllo sui simboli banditi — li contiene per
  poterli cercare, e senza esclusione si accusa da solo. Ma **solo lì**: se lo escludi da
  tutto l'albero, i simboli che lo script stesso definisce risultano inesistenti.

### 2. Gli hook — li esegue l'harness, non l'agente

È tutta la differenza: `CLAUDE.md`, `AGENTS.md` e le skill dipendono dall'aderenza
dell'agente, che è la variabile che sta fallendo. Un hook parte comunque.

Gli **script** degli hook sono versionati e **uguali per ogni agente**
(`scripts/agent_hooks.py`); il loro **aggancio** no. Il comando che li invoca contiene
il nome dell'interprete, che cambia da macchina a macchina, quindi sta nella
configurazione locale di ciascun agente, ignorata da git, e lo scrive l'inizializzatore su
ogni macchina. Non spostarlo nella configurazione versionata "perché valga ovunque":
arriverebbe sbagliato su un'altra macchina, e se resta anche nel file locale gli hook
girano due volte.

Gli script usano solo cio' che gli agenti supportati hanno in comune: all'avvio, testo su
stdout; a fine turno, uscita `0` con `{"decision": "block", "reason": "..."}` su stdout.
**Non usare l'uscita `2` per bloccare**: Codex 0.154.0 la tratta come errore e chiude il
turno comunque, mentre la decisione JSON blocca sia lì sia su Claude Code 2.1.274
(provato il 2026-09-17, su Windows).

**`SessionStart`** — inietta in contesto, a ogni avvio (`/clear` e compattazione compresi),
le sezioni volatili: cosa è bloccato, cosa è rotto, il cruscotto dell'evidenza, e un avviso
se il codice è andato avanti rispetto al marcatore di freschezza. Non «ricordati di
leggere»: è già lì. Il suo stdout entra nel contesto, quindi ogni riga si paga in token a
ogni avvio e in ogni chiamata successiva — inietta le due sezioni che contano, non tutto
il file. Il testo lo costruisce `context_core.build_injection`, lo stesso per l'hook, il
lint e la misura dei consumi: così i tre non possono dare numeri diversi. Oltre il tetto
di `config.toml` l'hook inietta solo l'indice dei blocchi (titoli e prima riga di ogni
voce) con un avviso, e chiede all'agente di leggere nel file **la sezione che gli serve**,
non il file intero: su uno `status.md` di centinaia di KB, «rileggi il file» costa più
dell'iniezione stessa.

**`Stop`** — scatta **alla fine di ogni risposta**, non a fine sessione: è il punto che
viene frainteso più spesso, ed è anche il motivo per cui funziona. Se il codice è cambiato
e il documento di stato è intatto, chiede di non chiudere e il turno continua finché non è
stato gestito. Non esiste nessun «momento finale» da intercettare, quindi chiudere il terminale
non salta nessun controllo: è già avvenuto a ogni turno precedente.

**`UserPromptSubmit`** — prima che un messaggio dell'utente parta. Se la sessione riprende
dopo una pausa più lunga della cache del contesto (1 ora per Claude Code, letta dalla
trascrizione) e il contesto supera la soglia di `config.toml` (100 mila token di partenza),
ferma il messaggio **una volta** e dice quanto costa riprendere: riscrivere tutto il
contesto in cache, poi rileggerlo a ogni chiamata. Il messaggio fermato non arriva al
modello; reinviato, passa. Non ferma mai un comando `/`: il rimedio è proprio `/clear`,
che non chiama il modello, azzera il contesto e fa ripartire `SessionStart`. Serve perché
le pause sono il costo che non si vede: su un repository di questo impianto, 21 riprese
dopo più di un'ora hanno riscritto 7 milioni di token, circa $72 [stimato da token
misurati, trascrizioni di settembre 2026]. Il formato che ferma è
`{"decision": "block", "reason": ...}`, provato su Claude Code 2.1.283 il 2026-09-28; su
Codex è quello della documentazione, non provato.

**Non usare un hook di fine sessione.** Non può bloccare, il suo output viene ignorato, e
non scatta se il processo viene ucciso. `SessionStart` + `Stop` chiudono le due estremità e
rendono quell'evento irrilevante.

Due proprietà non negoziabili:

- **Fail-open.** Qualunque errore interno esce `0` e non stampa. Un hook rotto deve
  degradare ad «assente», mai a «bloccante».
- **Una traccia su file**, in una directory non versionata (es. `.git/`), con orario,
  evento ed esito — inclusi gli esiti silenziosi. È **obbligatoria**, non un lusso: essendo
  fail-open, un hook rotto è indistinguibile da un hook assente, e senza traccia l'utente
  non ha modo di sapere quale dei due ha. Non dirgli mai «se non compare l'iniezione
  all'avvio non funziona»: lo stdout di `SessionStart` va nel contesto dell'agente, **non a
  schermo**, quindi l'utente non vede nulla neanche quando funziona perfettamente. È
  l'errore che ho commesso, e ha portato l'utente a credere rotto un hook che girava.
- **Blocca una volta sola per sessione.** `Stop` scattando a ogni turno diventa martellante
  se ripete. Lascia un marcatore (in una directory non versionata, es. `.git/`) e taci; e
  non bloccare un turno che l'agente ha gia' prolungato per un hook (`stop_hook_active`).

### 3. La misura dei consumi — quanto pesa davvero il contesto

```
<python> scripts/context_cost.py            resoconto: niente chiamate al modello
<python> scripts/context_cost.py misura     misura esatta del contesto fisso (~$0,40)
```

Il resoconto legge ciò che gli agenti registrano — le trascrizioni di Claude Code e i
`token_count` di Codex — e ne ricava, sessione per sessione, chiamate, contesto all'avvio e
massimo, token scritti e letti in cache, costo a listino. Poi le letture dei documenti di
contesto e l'andamento dell'iniezione nel tempo, dalla traccia degli hook.

Ogni numero porta la sua fonte, ed è la regola da rispettare quando lo riporti:
**[misurato]** è ciò che l'agente ha registrato o che la misura esatta ha trovato;
**[stimato]** è un calcolo (caratteri divisi per un rapporto, token per un prezzo). Non
dare mai un numero di token come fatto se lo strumento lo marca stimato.

`misura` è l'unico modo di sapere quanti token pesano `AGENTS.md` e l'iniezione **senza**
un'API di conteggio: lancia Claude Code headless in una copia usa e getta, una volta
vuota, una con le istruzioni, una anche con l'iniezione, e sottrae i totali che Claude
Code riporta. Tutto ciò che non è di questo impianto si elide. Rifalla dopo aver cambiato
`AGENTS.md` o i blocchi `session-start`: il resoconto sa se la misura è ancora di quei
contenuti e, se non lo è, torna a stimare e lo dice.

Cosa hanno trovato le prime misure, per orientarsi: sulla macchina dove sono state fatte,
con i suoi plugin, la base dell'harness vale circa 28 mila token e l'impianto ne aggiunge
3-4 mila [misurato, 2026-09-28], mentre il contesto medio per chiamata nelle sessioni
lunghe va da 175 a 260 mila token [misurato, trascrizioni]. **Il costo lo decide la lunghezza delle sessioni**: una sessione
per compito, `/clear` fra un compito e l'altro, sottoagenti per le letture pesanti.

## Procedura

L'ordine conta: è quello che evita di perdere informazione mentre riordini.

1. **Inventario.** Leggi le fonti e decidi per ogni blocco dove va. Non riscrivere ancora
   niente.
2. **Sposta quasi verbatim.** Prima muovi, poi riformuli. Se riscrivi mentre sposti non
   hai più un riferimento contro cui verificare.
3. **Estrai gli invarianti** in tabella, lasciando le spiegazioni dove sono.
4. **Scrivi l'ingresso** e i rinvii dei tool.
5. **Verifica** (sotto).
6. **Solo adesso deduplica** e accorcia, ri-verificando dopo ogni passata.
7. **Costruisci il livello che esegue**: prima il lint, poi gli hook. Il lint per primo,
   perché è quello che gli hook eseguiranno, e perché ti trova errori nei documenti che
   hai appena scritto — **aspettati che ne trovi**, ed è il segno che funziona.
8. **Provalo davvero.** Il lint sul repo vero; gli hook in un repo di prova usa-e-getta,
   costruito apposta, perché nel repo vero l'albero è sporco e le condizioni non si
   riproducono. Copri il caso in cui deve tacere, quello in cui deve bloccare, quello in
   cui non deve ripetersi, e l'input malformato.

Il passo 6 è quello che morde: togliendo un blocco che *sembra* già presente altrove
sparisce la frase che in quel blocco era l'unica non duplicata.

## Verifica

Due verifiche, con destini diversi.

**Usa e getta — nessuna perdita di contenuto.** Vale solo per la migrazione: scrivi lo
script, mostra l'output all'utente, buttalo. Ogni riga sostanziale delle fonti originali si
ritrova in qualche file nuovo. Confronta su un frammento normalizzato (es. i primi 60
caratteri senza spazi multipli), non sulla riga esatta: così tolleri la riformulazione ma
la sparizione emerge. **L'output non è una lista di errori**: classifica in tre categorie —
ritrovata verbatim, riformulata (copertura delle parole di contenuto sopra una soglia), da
esaminare a mano — e **leggi a mano solo la terza**, decidendo per ciascuna se è una
riscrittura voluta o una perdita. Riferisci i tre conteggi e le perdite vere che hai
reintegrato.

**Permanente — link e ancore.** Non buttarlo: **è il controllo 4 del lint**, e da lì in poi
vive con il repo. Per ogni link markdown verso un percorso locale, con o senza ancora
(`file.md#ancora`), il file esiste e l'ancora corrisponde a un titolo (slug in stile GitHub:
minuscolo, spazi in trattini, punteggiatura via). Le ancore si rompono per prime: basta
ritoccare un titolo. Salta i blocchi di codice, altrimenti i commenti `#` diventano titoli
e i link degli esempi risultano rotti. **Includi i file di ingresso nella lista**: sono
quelli che contengono quasi tutti i link, ed è banale dimenticarli e ottenere un "OK" che
non ha controllato niente. Indicizza anche le ancore HTML esplicite (`<a id="...">`), che
servono quando un titolo numerato produce uno slug che non vuoi citare.

E poi: **fai girare il lint completo e mostra l'output vero**, non un riassunto.

## Trappole

- **Rinominare cambiando solo maiuscole/minuscole su Windows**: il filesystem è
  case-insensitive e `git mv A.md a.md` non fa nulla. Serve il doppio passaggio,
  `git mv A.md tmp.md && git mv tmp.md a.md`.
- **Cartelle non tracciate**: `git mv` fallisce; usa `mv` e poi `git add -A`.
- **Riferimenti fuori dai `.md`**: prima di chiudere fai un `grep` dei path vecchi su
  tutto il repo. Un commento nel codice che cita un documento rinominato non lo trova
  nessun controllo sui markdown.
- **Archivi storici** (piani, specifiche, note di sessioni passate): lasciali com'erano,
  riferimenti vecchi inclusi. Riscriverli falsifica il registro di cosa si sapeva e quando.
- **L'import va verificato davvero**, in una sessione nuova. In Claude Code lo dice
  `/context`, alla voce dei file di memoria caricati. **Non puoi provarlo dalla sessione in cui lo
  scrivi**: dillo all'utente invece di dichiararlo funzionante.
- **Non confondere «l'utente non lo vede» con «non funziona».** Vale per tutto ciò che un
  hook inietta nel contesto: è per l'agente, non per lo schermo. Quando spieghi all'utente
  come verificare, dagli un controllo che può eseguire da solo — una traccia su file — non
  qualcosa che dovrebbe comparirgli davanti.
- **Il lint accusa il testo che descrive il lint.** Le righe che parlano della convenzione
  ne violano la forma. Serve la fuga esplicita, non un'eccezione nello script.
- **Un output di lint rumoroso non viene letto.** Se al primo giro escono cinquanta
  segnalazioni, non correggere i documenti: **correggi i controlli** finché restano solo
  quelle vere, poi correggi i documenti. Un lint con dieci falsi positivi è peggio di
  nessun lint, perché insegna a ignorarlo.
- **Il repo puo' non avere ancora un commit.** Lanciare l'inizializzatore prima del
  primo commit e' legittimo, ma non c'e' nessuno sha a cui ancorare il marcatore di
  freschezza. Non scrivere un marcatore finto per far passare il controllo di presenza:
  ometterlo e segnalarlo e' l'unica opzione onesta, e il controllo va fatto sulla
  **forma** dello sha, non sulla presenza della stringa.
- **Lo scheletro che generi deve passare il lint che generi.** Sembra ovvio e non lo e':
  il primo giro segnalava parole usate dallo scheletro stesso (`Esito`, `Chi`) perche' il
  lessico neutro non le conteneva. Uno strumento che accusa il file che ha appena scritto
  perde credibilita' al primo sguardo.
- **La console Windows non è UTF-8.** Uno script che stampa `→` o `«»` muore con
  `UnicodeEncodeError`. Forza la codifica dello stdout.
- **Il costo in token dell'hook di avvio è ricorrente**, e si paga anche a ogni `/clear` e
  a ogni compattazione. Misuralo e dillo all'utente in numeri, non a sensazione.

## Criteri di accettazione

- [ ] `AGENTS.md` sta in una schermata e non nomina né file sorgente né tool.
- [ ] Il file di ogni tool in uso è un rinvio di poche righe, con link **e** import.
- [ ] Ogni regola inviolabile è una riga in `invariants.md` con **dove vive** e il link al
      perché.
- [ ] I divieti sono scritti in forma eseguibile, e il lint legge la lista dal documento.
- [ ] Ogni sottosistema ha un file, e quel file dice anche *perché* è fatto così.
- [ ] Ogni affermazione porta il suo livello di evidenza, nella forma fissata; ogni
      *verificato* porta la data.
- [ ] `status.md` ha il marcatore `context-verified-at` e una sola sezione di stato
      corrente.
- [ ] Le verifiche manuali sono un registro con `Esito | Data | Chi`, non una checklist.
- [ ] Il lint esiste, è versionato, **gira pulito**, e il suo output è stato mostrato
      all'utente.
- [ ] Gli script degli hook esistono, sono versionati e fail-open, e il loro aggancio sta
      **solo** nella configurazione locale della macchina, non in quella versionata.
- [ ] Gli hook sono stati **provati** nei casi
      taci / blocca / non ripetere / input malformato.
- [ ] Esiste una traccia su file degli hook, e all'utente è stato spiegato come leggerla —
      non come «guardare se compare qualcosa a schermo».
- [ ] Nessun path vecchio è rimasto nel repo, `.md` o no.
- [ ] La regola su commit e push che l'utente ha dichiarato è stata rispettata.

## Cosa dire alla fine

Riferisci: l'albero prodotto, l'output **vero** del lint e delle prove sugli hook, cosa hai
chiesto all'utente e cosa hai dedotto, le informazioni che non sei riuscito a collocare, e
**cosa non hai potuto verificare da qui** (l'import, l'aggancio degli hook nella sessione
successiva). Se una scelta ti sembrava sbagliata e l'hai fatta lo stesso perché richiesta,
dillo.

## Mantenerla, dopo

Lascia scritte le tre domande che dicono dove va una cosa nuova, in quest'ordine:

1. È una regola che, violata, rompe qualcosa? → riga in `invariants.md`, più la
   spiegazione nel file del sottosistema.
2. Riguarda un sottosistema? → il suo file.
3. È stato del lavoro (problema noto, TODO, verifica fatta)? → `status.md`.

Il lavoro che emerge durante una sessione — un difetto notato di sfuggita, una verifica
saltata, una decisione rimandata — va in `status.md` **subito**, senza aspettare che
l'utente lo chieda. È l'unica cosa che sopravvive alla fine della sessione.

E una regola sull'ingresso: **`AGENTS.md` cresce solo se nasce un sottosistema.** Se stai
aggiungendo una riga di contenuto lì dentro, quasi certamente va in un file linkato.

Lo stesso vale per i blocchi `session-start` di `status.md`: una voce chiusa esce dagli
aperti nel commit che la chiude, e il controllo 6 del lint dice quanto pesa l'iniezione.
Se supera il tetto, si accorcia il documento, non si alza il tetto.

Infine, la regola che tiene in piedi il livello che esegue: **il lint va fatto girare prima
di dichiarare concluso qualcosa**, e quando trova qualcosa si corregge il documento, non si
allarga l'eccezione.
