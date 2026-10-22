---
name: status
disable-model-invocation: true
description: Use when the user asks for the keep-fresh state of the current repository - plugin installed, hooks running, lint, handoffs, what to fix
---

# keep-fresh: status

Non installare niente. Esegui solo, nella radice del repository corrente:

    python "<scripts>/kf_init.py" --status

(`python3` su macOS/Linux). `<scripts>` è `../../scripts/` rispetto a questo file; in Claude
Code `${CLAUDE_SKILL_DIR}/../../scripts/`.

Riporta all'utente cosa dice: dove il plugin è installato, quando gli hook hanno girato
l'ultima volta in questo progetto, gli handoff, il lint e l'elenco "da sistemare". È di sola
lettura. Esce 1 se c'è qualcosa da sistemare: non è un errore del comando.
