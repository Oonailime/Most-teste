#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

API_URL="${API_URL:-http://127.0.0.1:8000}"
LATENCY_TIMEOUT="${LATENCY_TIMEOUT:-600}"
MEMORY_TIMEOUT="${MEMORY_TIMEOUT:-600}"
OUTPUT_DIR="${OUTPUT_DIR:-$SCRIPT_DIR/../benchmark-results}"

usage() {
  cat <<'EOF'
Uso:
  scripts/benchmark-server.sh

Variaveis opcionais:
  API_URL=http://127.0.0.1:8000
  LATENCY_TIMEOUT=600
  MEMORY_TIMEOUT=600
  OUTPUT_DIR=./benchmark-results

Descricao:
  Executa os benchmarks de latencia e memoria com timeouts maiores,
  salvando os resultados em arquivos separados para uso na VM.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

mkdir -p "$OUTPUT_DIR"

LATENCY_OUTPUT="${OUTPUT_DIR}/benchmark-latency-${TIMESTAMP}.txt"
MEMORY_OUTPUT="${OUTPUT_DIR}/benchmark-memory-${TIMESTAMP}.txt"

printf 'Executando benchmark de latencia...\n'
API_URL="$API_URL" \
REQUEST_TIMEOUT="$LATENCY_TIMEOUT" \
OUTPUT_FILE="$LATENCY_OUTPUT" \
  "$SCRIPT_DIR/benchmark-latency.sh"

printf 'Executando benchmark de memoria...\n'
API_URL="$API_URL" \
REQUEST_TIMEOUT="$MEMORY_TIMEOUT" \
OUTPUT_FILE="$MEMORY_OUTPUT" \
  "$SCRIPT_DIR/benchmark-memory.sh"

printf '\nArquivos gerados:\n'
printf '%s\n' "$LATENCY_OUTPUT"
printf '%s\n' "$MEMORY_OUTPUT"
