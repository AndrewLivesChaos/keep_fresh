: << 'CMDBLOCK'
@echo off
REM Lanciatore degli hook di keep-fresh, valido per cmd e per sh (poliglotta, sul modello
REM di quello di superpowers). Lancia scripts\agent_hooks.py con gli stessi argomenti:
REM     run-hook.cmd <session-start|stop|prompt> --agent <nome>
REM Su Windows l'interprete e' python (python3 e' spesso l'alias dello Store, che non
REM funziona); altrove python3. Senza interprete esce 0 in silenzio: un hook che non puo'
REM girare deve valere come assente, mai come bloccante.
where python >nul 2>nul || exit /b 0
python "%~dp0..\scripts\agent_hooks.py" %*
exit /b 0
CMDBLOCK

# $0 puo' arrivare con le barre di Windows: si normalizzano, senza dirname ne' cd.
case "$0" in
  */*|*\\*) p="${0//\\//}"; SCRIPT_DIR="${p%/*}" ;;
  *) SCRIPT_DIR="." ;;
esac
if [ "$OS" = "Windows_NT" ]; then PY=python; else PY=python3; fi
command -v "$PY" >/dev/null 2>&1 || exit 0
exec "$PY" "$SCRIPT_DIR/../scripts/agent_hooks.py" "$@"
