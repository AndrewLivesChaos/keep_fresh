---
name: lint
description: Use before declaring work done in a keep-fresh repository, or when asked to verify the context documents (status.md, AGENTS.md, docs/keep-fresh/context/) still tell the truth - runs the keep-fresh docs lint
---

# keep-fresh: lint

Nella radice del repository corrente esegui

    python "<scripts>/docs_lint.py"

(`python3` su macOS/Linux; `--quiet` per le sole segnalazioni). `<scripts>` è
`../../scripts/` rispetto a questo file; in Claude Code `${CLAUDE_SKILL_DIR}/../../scripts/`.

Riporta l'esito vero, non un riassunto rassicurante: errori e avvisi con il loro tag. Quando
trova qualcosa si corregge il documento, non si allarga l'eccezione in `config.toml`; una
segnalazione che descrive un difetto vero va registrata come lavoro aperto in `status.md`.
