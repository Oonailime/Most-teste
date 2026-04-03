#!/usr/bin/env bash

set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"
REQUEST_TIMEOUT="${REQUEST_TIMEOUT:-180}"
OUTPUT_FILE="${OUTPUT_FILE:-}"

BASE_IDENTIFIERS=(
  "Maria"
  "Jose"
  "Joao"
  "Joaquim"
  "Rosa"
  "A Anne Christine Silva Ribeiro"
)

log() {
  printf '%s\n' "$*" >&2
}

print_line() {
  printf '%s\n' "$1"
  if [[ -n "$OUTPUT_FILE" ]]; then
    printf '%s\n' "$1" >>"$OUTPUT_FILE"
  fi
}

usage() {
  cat <<'EOF'
Uso:
  scripts/benchmark-latency.sh

Variaveis opcionais:
  API_URL=http://127.0.0.1:8000
  REQUEST_TIMEOUT=180
  OUTPUT_FILE=benchmark-latency.txt

Descricao:
  Mede o tempo total para concluir 6 e 12 requisicoes paralelas contra a API.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "Comando obrigatorio ausente: $1"
    exit 1
  fi
}

require_cmd curl
require_cmd python3

wait_for_health() {
  log "Aguardando API em ${API_URL}/health ..."
  local attempt
  for attempt in $(seq 1 60); do
    if curl -fsS "${API_URL}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  log "API nao respondeu em ${API_URL}/health"
  exit 1
}

curl_request() {
  local identifier="$1"
  curl -fsS \
    --max-time "$REQUEST_TIMEOUT" \
    -H 'Content-Type: application/json' \
    -d "{\"identificador\":\"$identifier\"}" \
    "${API_URL}/consulta-script" \
    >/dev/null
}

build_identifiers() {
  local target_count="$1"
  local -n out_ref="$2"
  out_ref=()
  local idx=0
  while [[ "${#out_ref[@]}" -lt "$target_count" ]]; do
    out_ref+=("${BASE_IDENTIFIERS[$idx]}")
    idx=$(((idx + 1) % ${#BASE_IDENTIFIERS[@]}))
  done
}

run_parallel_batch() {
  local batch_size="$1"
  local identifiers=()
  build_identifiers "$batch_size" identifiers

  local started_at ended_at
  started_at="$(python3 -c 'import time; print(time.perf_counter())')"

  local pids=()
  local identifier
  for identifier in "${identifiers[@]}"; do
    curl_request "$identifier" &
    pids+=("$!")
  done

  local pid
  for pid in "${pids[@]}"; do
    wait "$pid"
  done

  ended_at="$(python3 -c 'import time; print(time.perf_counter())')"

  python3 - "$started_at" "$ended_at" "$batch_size" <<'PY'
import sys
started = float(sys.argv[1])
ended = float(sys.argv[2])
batch_size = int(sys.argv[3])
elapsed = ended - started
per_request = elapsed / batch_size if batch_size else 0.0
print(f"{elapsed:.2f}|{per_request:.2f}")
PY
}

wait_for_health

if [[ -n "$OUTPUT_FILE" ]]; then
  : >"$OUTPUT_FILE"
fi

print_line "Benchmark de latencia"
print_line "API_URL: $API_URL"
print_line ""

for batch_size in 6 12; do
  result="$(run_parallel_batch "$batch_size")"
  elapsed="${result%%|*}"
  per_request="${result##*|}"
  print_line "- ${batch_size} requisicoes paralelas: ${elapsed}s totais"
  print_line "- ${batch_size} requisicoes paralelas: ${per_request}s medio por requisicao no lote"
done
