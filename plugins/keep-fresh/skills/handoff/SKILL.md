---
name: handoff
disable-model-invocation: true
argument-hint: "[--elenco | --scarta n]"
description: Use when the user wants to close this session without losing the thread - write a keep-fresh handoff for the next session, list or discard handoffs
---

# keep-fresh: handoff

Serve a chiudere questa sessione senza perdere il filo: lo scrivi tu, perché decisioni,
vicoli ciechi e prossimo passo li conosci solo tu. Il repository deve usare keep-fresh
(`.keep-fresh/config.toml`); se non lo usa, dillo e proponi `/keep-fresh:init`.

`<scripts>` è `../../scripts/` rispetto a questo file; in Claude Code
`${CLAUDE_SKILL_DIR}/../../scripts/`. `python` su Windows, `python3` su macOS/Linux.

1. Esegui `python "<scripts>/handoff.py" new --title "<una riga>"`. Il titolo è ciò che
   l'utente vedrà nell'elenco: il lavoro e a che punto sei, non "handoff".
2. **Prima di scrivere, rileggi le fonti**: `status.md`, i piani e gli elenchi di cose da fare
   del progetto (cerca anche `docs/`, TODO, checklist). Per "Ancora da fare" copia ogni voce
   aperta da lì, una per una, con il suo riferimento (sezione, riga); non ricostruirla dalla
   conversazione e non riassumere "restano A, B e C". Se una voce è chiusa o cambiata,
   dillo. Confronta alla fine l'elenco con la fonte: nessuna voce aperta deve mancare.
3. Scrivi il corpo nel file che lo script ha stampato, nelle sezioni che trovi già lì
   (obiettivo, fatto, decisioni, cosa non ha funzionato, prossimo passo, file e stato git),
   e **cancella la riga `<!-- handoff-vuoto ... -->`**. Il modello è nella guida del plugin
   (`../../guide.md`). Niente credenziali, chiavi, token.
4. Di' all'utente il percorso e che ora può fare `/clear` o aprire una sessione nuova: lo
   vedrà lì in elenco, e lo riprende con `/keep-fresh:resume`. Non committare.

Con `--elenco` esegui solo `handoff.py list`; con `--scarta [n|parola]`,
`handoff.py discard [n|parola]`. Riporta l'uscita all'utente.
