#!/usr/bin/env bash
# Processa tudo o que estiver em /acervo/entrada, em segundo plano.
# Pode fechar o terminal/SSH que continua rodando.
#
#   ./rodar_lote.sh            inicia
#   ./rodar_lote.sh status     mostra se está rodando e as últimas linhas do log
#   ./rodar_lote.sh parar      interrompe (pode retomar depois rodando de novo)
#
# Configuração (pode trocar aqui ou definir antes de chamar):
ACERVO="${ACERVO:-/acervo}"
MODELO_IA="${MODELO_IA:-qwen2.5:7b}"      # deixe vazio ("") para não gerar resumo por IA
PGDSN="${PGDSN:-postgresql:///acervo}"    # banco local, usuário do sistema
OPCOES_OCR="${OPCOES_OCR:---salvar-removidas}"
[ -d "$ACERVO/flash_exemplos" ] && [ -n "$(ls -A "$ACERVO/flash_exemplos" 2>/dev/null)" ] \
    && OPCOES_OCR="$OPCOES_OCR --flash-ref $ACERVO/flash_exemplos"

DIR="$(cd "$(dirname "$0")" && pwd)"
LOGDIR="$ACERVO/logs"
PIDFILE="$LOGDIR/lote.pid"
mkdir -p "$LOGDIR"

case "${1:-iniciar}" in
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "RODANDO (pid $(cat "$PIDFILE"))"
    else
      echo "Parado."
    fi
    echo "--- últimas linhas de $LOGDIR/lote.log ---"
    tail -n 15 "$LOGDIR/lote.log" 2>/dev/null
    exit 0 ;;
  parar)
    [ -f "$PIDFILE" ] && pkill -TERM -g "$(ps -o pgid= "$(cat "$PIDFILE")" | tr -d ' ')" && echo "Parado."
    rm -f "$PIDFILE"; exit 0 ;;
  iniciar) ;;
  *) echo "uso: $0 [iniciar|status|parar]"; exit 2 ;;
esac

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Já está rodando (pid $(cat "$PIDFILE")). Use: $0 status"; exit 1
fi

setsid nohup bash -c "
  set -o pipefail
  echo \"===== Início do lote: \$(date) =====\"
  python3 '$DIR/inventario.py' '$ACERVO/entrada' '$ACERVO/saida/inventario' --sem-paginas
  python3 '$DIR/processar_acervo.py' '$ACERVO/entrada' '$ACERVO/saida' $OPCOES_OCR
  if [ -n '$MODELO_IA' ] && curl -s -m 3 http://localhost:11434 >/dev/null; then
    python3 '$DIR/resumir_local.py' '$ACERVO/saida' --modelo '$MODELO_IA'
  else
    echo 'Resumo por IA pulado (sem modelo definido ou Ollama desligado).'
  fi
  PGDSN='$PGDSN' python3 '$DIR/importar_postgres.py' '$ACERVO/saida'
  echo \"===== Fim do lote: \$(date) =====\"
" >> "$LOGDIR/lote.log" 2>&1 &
echo $! > "$PIDFILE"
echo "Lote iniciado em segundo plano. Acompanhe com: $0 status"
