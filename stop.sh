#!/bin/bash
# JHC Viral Engine — Parar servidor
# Uso: ./stop.sh
set -e

PID_FILE="/tmp/jhc_viral_engine.pid"
PORT=8765

echo "🛑 JHC Viral Engine — Parando..."

# Tentar parar via PID file
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "✅ Servidor parado (PID $PID)"
        rm -f "$PID_FILE"
    else
        echo "⚠️ Processo $PID não encontrado (já parou?)"
        rm -f "$PID_FILE"
    fi
else
    echo "⚠️ Arquivo PID não encontrado em $PID_FILE"
fi

# Fallback: matar qualquer processo na porta
if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    FALLBACK_PID=$(lsof -ti :$PORT 2>/dev/null | head -1)
    if [ -n "$FALLBACK_PID" ]; then
        echo "⚠️ Porta $PORT ainda ocupada por PID $FALLBACK_PID, matando..."
        kill "$FALLBACK_PID" 2>/dev/null || true
        sleep 1
    fi
fi

# Verificar se parou
if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    echo "❌ Falha ao parar. Porta $PORT ainda ocupada."
    echo "   Tente: kill -9 $(lsof -ti :$PORT)"
    exit 1
else
    echo "✅ Porta $PORT liberada."
fi