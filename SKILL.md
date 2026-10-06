---
name: keep-fresh
disable-model-invocation: true
argument-hint: "[status | handoff [--elenco | --scarta n] | resume [n] [--comunque]]"
description: Use when a git repository needs agent context set up, updated or repaired - no docs/keep-fresh/context/status.md, no docs lint, missing SessionStart/Stop hooks, hooks lost after a clone, or the user mentions stale CLAUDE.md/AGENTS.md, context rot, "inizializza il contesto", "prepara il repo per gli agenti"
---

# keep-fresh

Prepara un repository git perché gli agenti ci lavorino con un contesto che non marcisce:
un lint dei documenti, hook che iniettano lo stato del lavoro e bloccano il turno se il
codice è cambiato e lo stato no. Lo script fa la meccanica; **i documenti li scrivi tu**,
seguendo la guida che lo script installa.

## Se invocata con `status`

Se l'argomento e' `status` (`$ARGUMENTS`), non installare niente: esegui solo
`python "${CLAUDE_SKILL_DIR}/agent_context_init.py" --status` (`python3` su macOS/Linux) nel
repository corrente e riporta all'utente cosa dice: layout, versione, hook agganciati e quando
hanno girato l'ultima volta, lint, e l'elenco "da sistemare". E' di sola lettura. Esce 1 se
c'e' qualcosa da sistemare: non e' un errore del comando.

## Se invocata con `handoff`

Serve a chiudere questa sessione senza perdere il filo: lo scrivi tu, perche' decisioni,
vicoli ciechi e prossimo passo li conosci solo tu. L'impianto deve essere gia' installato
nel repository (`.keep-fresh/scripts/handoff.py`); se manca, dillo e proponi di rilanciare
l'inizializzazione con `--force`.

1. Esegui `python .keep-fresh/scripts/handoff.py new --title "<una riga>"` (`python3` su
   macOS/Linux). Il titolo e' cio' che l'utente vedra' nell'elenco: il lavoro e a che punto
   sei, non "handoff".
2. Scrivi il corpo nel file che lo script ha stampato, nelle sezioni che trovi gia' li
   (obiettivo, fatto, decisioni, cosa non ha funzionato, prossimo passo, file e stato git),
   e **cancella la riga `<!-- handoff-vuoto ... -->`**. Il modello e' in
   `.keep-fresh/guide.md`. Niente credenziali, chiavi, token.
3. Di' all'utente il percorso e che ora puo' fare `/clear` o aprire una sessione nuova: lo
   vedra' li' in elenco, e lo riprende con `/keep-fresh resume`. Non committare.

Con `handoff --elenco` esegui solo `handoff.py list`; con `handoff --scarta [n|parola]`,
`handoff.py discard [n|parola]`. Riporta l'uscita all'utente.

## Se invocata con `resume`

Riprende un handoff scritto da una sessione precedente. Esegui
`python .keep-fresh/scripts/handoff.py resume [n|parola]` con quello che l'utente ha detto
dopo `resume`.

- Con piu' handoff aperti e nessuna scelta, lo script li elenca ed esce 1: mostra l'elenco
  all'utente e chiedigli quale.
- Se esce 1 con `ATTENZIONE` (branch o HEAD diversi da quando fu scritto), non l'ha letto ne'
  consumato: dillo all'utente e rilancia con `--comunque` solo se conferma.
- Se l'utente ha scritto lui `--comunque` dopo `resume` (`/keep-fresh resume 2 --comunque`),
  passalo allo script: vuol dire che sa gia' che branch o HEAD sono diversi.
- Se esce 0 ha stampato l'handoff e l'ha segnato ripreso: lavora da quel contenuto, e
  dichiara se qualcosa non torna con lo stato attuale del repository.

## Prima di cominciare

- Serve un repository git (`git rev-parse --show-toplevel`). Se non lo è, chiedi se fare `git init`.
- Serve Python 3.14 o successivo: `python` su Windows, `python3` su macOS/Linux.
  Il minimo tecnico è 3.11; il Python di sistema di macOS (3.9) non basta.
- Lo script lavora sul repository **della cartella corrente**, non su quello della skill.
  Resta nella radice del progetto di destinazione.

## Procedura

1. **Prova a vuoto.** Non scrive nulla:
   `python "${CLAUDE_SKILL_DIR}/agent_context_init.py" --dry-run`
2. **Mostra all'utente** cosa farebbe e aspetta il suo via libera.
3. **Esegui davvero**, stesso comando senza `--dry-run`. Se il repository è già stato
   inizializzato e vuoi aggiornare lint, hook e guida, aggiungi `--force`
   (non tocca `status.md` né `config.toml`; poi guarda il `git diff`).
   Se lo script risponde "layout precedente" e si rifiuta (exit 2), il repository ha gli
   script in `scripts/` e il contesto in `docs/context/`: la migrazione **sposta file**.
   Mostra all'utente la prova a vuoto e usa `--force` solo con il suo via libera.
4. **Segui il prompt** che lo script stampa alla fine: dice come scrivere `AGENTS.md`,
   `CLAUDE.md` e `docs/keep-fresh/context/status.md` leggendo il repo e chiedendo all'utente ciò che
   nel repo non c'è. La guida è anche in `.keep-fresh/guide.md` del progetto.
5. **Leggi la diagnosi** stampata dallo script: elenca ciò che ancora non funziona.
   Se segnala **un'altra copia dell'inizializzatore** nel progetto (per esempio
   `scripts/agent_context_init.py`), **non sostituirla e non toglierla da solo**: e' una
   scelta del progetto. Serve a chi clona e non ha la skill, per riagganciare gli hook; chi
   ha la skill installata non ne ha bisogno. Dillo all'utente con i due esiti (sostituirla
   con la copia nuova, o toglierla), e che la guida ne prevede una in `.keep-fresh/` e non
   nel percorso del vecchio layout. Poi aspetta la sua risposta.

Non committare e non fare push senza che l'utente lo chieda.

## Da sapere

- Gli hook vanno agganciati **su ogni macchina** dopo un clone: lo script va rilanciato una volta.
- **Codex** salta gli hook del repository, senza avvisare, finché il progetto non è fidato
  e gli hook non sono approvati con `/hooks`.
- Gli handoff stanno in `.git/keep-fresh-handoff/`: locali, mai nel repository; dopo 48 ore
  non compaiono piu' da soli nell'indice all'avvio, ma nominandoli si riprendono ancora.
- Comandi utili: `--version` (che copia è), `--self-test`, `--force`, `--dry-run`.
- Dettagli, tabella dei file scritti e taratura (`config.toml`): `${CLAUDE_SKILL_DIR}/README.md`.
