---
name: resume
disable-model-invocation: true
argument-hint: "[n] [--comunque]"
description: Use when the user wants to pick up a keep-fresh handoff written by a previous session
---

# keep-fresh: resume

Riprende un handoff scritto da una sessione precedente. Esegui

    python "<scripts>/handoff.py" resume [n|parola]

con quello che l'utente ha detto dopo `resume`. `<scripts>` è `../../scripts/` rispetto a
questo file; in Claude Code `${CLAUDE_SKILL_DIR}/../../scripts/`. `python3` su macOS/Linux.

- Con più handoff aperti e nessuna scelta, lo script li elenca ed esce 1: mostra l'elenco
  all'utente e chiedigli quale.
- Se esce 1 con `ATTENZIONE` (branch o HEAD diversi da quando fu scritto), non l'ha letto né
  consumato: dillo all'utente e rilancia con `--comunque` solo se conferma.
- Se l'utente ha scritto lui `--comunque` (`/keep-fresh:resume 2 --comunque`), passalo allo
  script: vuol dire che sa già che branch o HEAD sono diversi.
- Se esce 0 ha stampato l'handoff e l'ha segnato ripreso: lavora da quel contenuto, e
  dichiara se qualcosa non torna con lo stato attuale del repository.
