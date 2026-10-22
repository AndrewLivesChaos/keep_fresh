---
name: cost
argument-hint: "[misura] [--giorni N]"
description: Use when asked how much the agent context of a keep-fresh repository costs in tokens or money - session report from transcripts, or exact measurement
---

# keep-fresh: cost

Nella radice del repository corrente esegui

    python "<scripts>/context_cost.py" [argomenti]

con gli argomenti ricevuti: niente per il resoconto (non chiama nessun modello), `misura`
per la misura esatta del contesto fisso (lancia Claude Code headless, costa qualche decimo di
dollaro: dillo prima), `--giorni N` per le sole sessioni recenti. `python3` su macOS/Linux.
`<scripts>` è `../../scripts/` rispetto a questo file; in Claude Code
`${CLAUDE_SKILL_DIR}/../../scripts/`.

Riporta i numeri con la loro fonte: **[misurato]** o **[stimato]**, come li marca lo script.
Non dare come fatto un numero che lo script marca stimato.
