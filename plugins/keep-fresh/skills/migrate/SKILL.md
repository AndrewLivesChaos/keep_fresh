---
name: migrate
disable-model-invocation: true
argument-hint: "[--root DIR]"
description: Use when projects still have the old keep-fresh setup (scripts copied in .keep-fresh/scripts/, hooks in settings.local.json or .codex/hooks.json) and must move to the plugin, all at once
---

# keep-fresh: migrate

Porta sul plugin, in un colpo, tutti i progetti inizializzati con il vecchio impianto: toglie
gli script copiati e i loro agganci, e nei documenti sostituisce i percorsi con i comandi
della skill. Non committa.

`<scripts>` è `../../scripts/` rispetto a questo file; in Claude Code
`${CLAUDE_SKILL_DIR}/../../scripts/`. `python` su Windows, `python3` su macOS/Linux.

1. **Prova a vuoto**, che non scrive niente:
   `python "<scripts>/migrate.py"` (con `--root DIR` se l'utente l'ha indicata; senza, cerca in
   `C:\projects` su Windows e in `~/projects` altrove).
2. **Mostra all'utente l'uscita**: in testa dove il plugin è installato (se manca in una
   configurazione, lì i progetti migrati resterebbero senza hook: dillo chiaramente), poi per
   ogni progetto cosa toglie e cosa riscrive, quali salta e perché.
3. **Aspetta il suo via libera.** Mai `--apply` senza conferma.
4. Poi `python "<scripts>/migrate.py" --apply` (stessa `--root`).
5. Di' all'utente di guardare il `git diff` di ogni progetto migrato e che i commit li fa
   lui. I progetti saltati restano col vecchio impianto: si rilancia dopo aver sistemato il
   motivo (di solito modifiche non committate).
