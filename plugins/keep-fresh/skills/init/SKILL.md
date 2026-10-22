---
name: init
disable-model-invocation: true
description: Use when a git repository needs keep-fresh set up - no docs/keep-fresh/context/status.md, no .keep-fresh/config.toml, or the user mentions stale CLAUDE.md/AGENTS.md, context rot, "inizializza il contesto", "prepara il repo per gli agenti"
---

# keep-fresh: init

Prepara un repository git perché gli agenti ci lavorino con un contesto che non marcisce:
un lint dei documenti e hook che iniettano lo stato del lavoro e bloccano il turno se il
codice è cambiato e lo stato no. Lint e hook stanno nel plugin; nel progetto lo script
scrive solo due semi. **I documenti li scrivi tu**, seguendo la guida del plugin.

Gli script stanno in `../../scripts/` rispetto a questo file (in Claude Code:
`${CLAUDE_SKILL_DIR}/../../scripts/`). Qui sotto `<scripts>` è quella cartella.

## Prima di cominciare

- Serve un repository git (`git rev-parse --show-toplevel`). Se non lo è, chiedi se fare `git init`.
- Serve Python 3.14 o successivo: `python` su Windows, `python3` su macOS/Linux.
- Lo script lavora sul repository **della cartella corrente**. Resta nella radice del
  progetto di destinazione.

## Procedura

1. **Prova a vuoto.** Non scrive nulla: `python "<scripts>/kf_init.py" --dry-run`
2. **Mostra all'utente** cosa farebbe e aspetta il suo via libera.
3. **Esegui davvero**, stesso comando senza `--dry-run`. Non tocca mai `status.md` né
   `config.toml` se esistono già.
4. Se lo script dice che c'è **il vecchio impianto** (`.keep-fresh/scripts/`), non
   sistemarlo a mano: proponi all'utente `/keep-fresh:migrate`.
5. **Segui il prompt** che lo script stampa alla fine: dice come scrivere `AGENTS.md`,
   `CLAUDE.md` e `docs/keep-fresh/context/status.md` leggendo il repo e chiedendo
   all'utente ciò che nel repo non c'è. La guida è `../../guide.md` rispetto a questo file.
6. **Leggi la diagnosi** stampata dallo script: elenca ciò che ancora non funziona. Se
   segnala **una copia del vecchio inizializzatore** nel progetto, non toglierla da solo:
   è una scelta del progetto, chiedi all'utente.

Non committare e non fare push senza che l'utente lo chieda.

## Da sapere

- Gli hook partono dal plugin, in ogni sessione: non c'è niente da agganciare nel progetto.
- **Codex** salta gli hook dei plugin, senza avvisare, finché l'utente non li approva con
  `/hooks`.
- Stato in sola lettura: `/keep-fresh:status`.
