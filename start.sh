#!/bin/bash
# JHC Viral Engine — Inicializador macOS
# Uso: ./start.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
LOG="/tmp/jhc_viral_engine.log"
PID_FILE="/tmp/jhc_viral_engine.pid"
PORT=8765
HOST="127.0.0.1"

echo "🚀 JHC Viral Engine — Iniciando..."

# Verificar venv
if [ ! -f "$VENV/bin/python" ]; then
    echo "❌ Virtual environment não encontrado em $VENV"
    echo "   Execute: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

# Verificar se já está rodando
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "⚠️  Servidor já está rodando (PID $OLD_PID)"
        echo "   Use ./stop.sh para parar antes de reiniciar."
        exit 0
    else
        rm -f "$PID_FILE"
    fi
fi

# Verificar porta
if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    EXISTING_PID=$(lsof -ti :$PORT 2>/dev/null | head -1)
    echo "⚠️  Porta $PORT ocupada por PID $EXISTING_PID"
    echo "   Matando processo existente..."
    kill "$EXISTING_PID" 2>/dev/null || true
    sleep 2
fi

# Iniciar servidor
cd "$SCRIPT_DIR"
nohup "$VENV/bin/python" -m uvicorn src.api.main:app \
    --host "$HOST" --port "$PORT" \
    --log-level info \
    > "$LOG" 2>&1 &

NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

# Aguardar startup
sleep 3

# Health check via script Python externo
HEALTH_OUTPUT=$("$VENV/bin/python3" "$SCRIPT_DIR/health_check.py" 2>&1) || true

if echo "$HEALTH_OUTPUT" | grep -q "^OK"; then
    echo "✅ Servidor iniciado com sucesso!"
    echo "   PID: $NEW_PID"
    echo "   URL: http://$HOST:$PORT"
    echo "   API Docs: http://$HOST:$PORT/docs"
    echo "   Logs: $LOG"
    echo ""
    echo "🌐 Abrindo painel no navegador..."
    open "http://$HOST:$PORT/docs" 2>/dev/null || \
    xdg-open "http://$HOST:$PORT/docs" 2>/dev/null || \
    echo "   Abra manualmente: http://$HOST:$PORT/docs"
else
    echo "❌ Falha ao iniciar servidor:"
    echo "$HEALTH_OUTPUT"
    echo "   Verifique os logs: tail -20 $LOG"
    rm -f "$PID_FILE"
    exit 1
fi