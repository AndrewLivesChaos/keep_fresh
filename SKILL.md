---
name: keep-fresh
disable-model-invocation: true
argument-hint: "[status]"
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

Non committare e non fare push senza che l'utente lo chieda.

## Da sapere

- Gli hook vanno agganciati **su ogni macchina** dopo un clone: lo script va rilanciato una volta.
- **Codex** salta gli hook del repository, senza avvisare, finché il progetto non è fidato
  e gli hook non sono approvati con `/hooks`.
- Comandi utili: `--version` (che copia è), `--self-test`, `--force`, `--dry-run`.
- Dettagli, tabella dei file scritti e taratura (`config.toml`): `${CLAUDE_SKILL_DIR}/README.md`.
