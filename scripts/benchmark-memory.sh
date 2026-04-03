#!/usr/bin/env bash

set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"
SERVICE_NAME="${SERVICE_NAME:-api}"
POLL_INTERVAL="${POLL_INTERVAL:-1}"
OUTPUT_FILE="${OUTPUT_FILE:-}"
REQUEST_TIMEOUT="${REQUEST_TIMEOUT:-120}"

DEFAULT_IDENTIFIERS=(
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

usage() {
  cat <<'EOF'
Uso:
  scripts/benchmark-memory.sh [identificador1 identificador2 ...]

Variaveis opcionais:
  API_URL=http://127.0.0.1:8000
  SERVICE_NAME=api
  POLL_INTERVAL=1
  REQUEST_TIMEOUT=120
  OUTPUT_FILE=benchmark-memory.txt

Descricao:
  Mede consumo de memoria do container Docker da API em tres cenarios:
  1. Repouso
  2. Requisicoes sequenciais, uma por vez
  3. Requisicoes paralelas com todos os identificadores informados

Observacao:
  O valor por requisicao e uma estimativa baseada no pico de memoria do container.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "$#" -gt 0 ]]; then
  IDENTIFIERS=("$@")
else
  IDENTIFIERS=("${DEFAULT_IDENTIFIERS[@]}")
fi

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "Comando obrigatorio ausente: $1"
    exit 1
  fi
}

require_cmd docker
require_cmd curl
require_cmd awk

compose_container_id() {
  docker compose ps -q "$SERVICE_NAME"
}

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

mem_usage_text() {
  local container_id="$1"
  docker stats --no-stream --format '{{.MemUsage}}' "$container_id" | head -n 1
}

to_mib() {
  local raw="$1"
  awk '
    function trim(s) {
      sub(/^[[:space:]]+/, "", s)
      sub(/[[:space:]]+$/, "", s)
      return s
    }
    BEGIN {
      value = trim(ARGV[1])
      split(value, parts, " ")
      num = parts[1] + 0
      unit = parts[2]
      if (unit == "GiB")      mib = num * 1024
      else if (unit == "MiB") mib = num
      else if (unit == "KiB") mib = num / 1024
      else if (unit == "B")   mib = num / 1024 / 1024
      else                    mib = num
      printf "%.2f\n", mib
    }
  ' "$raw"
}

current_mem_mib() {
  local container_id="$1"
  local raw usage
  raw="$(mem_usage_text "$container_id")"
  usage="${raw%% / *}"
  to_mib "$usage"
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

measure_peak_while_running() {
  local container_id="$1"
  shift
  local pids=("$@")
  local peak
  peak="$(current_mem_mib "$container_id")"

  while true; do
    local any_running=0
    local pid
    for pid in "${pids[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        any_running=1
        break
      fi
    done

    local current
    current="$(current_mem_mib "$container_id")"
    peak="$(awk -v a="$peak" -v b="$current" 'BEGIN { if (b > a) print b; else print a }')"

    if [[ "$any_running" -eq 0 ]]; then
      break
    fi
    sleep "$POLL_INTERVAL"
  done

  printf '%s\n' "$peak"
}

join_by() {
  local sep="$1"
  shift
  local first=1
  local item
  for item in "$@"; do
    if [[ "$first" -eq 1 ]]; then
      printf '%s' "$item"
      first=0
    else
      printf '%s%s' "$sep" "$item"
    fi
  done
}

print_line() {
  printf '%s\n' "$1"
  if [[ -n "$OUTPUT_FILE" ]]; then
    printf '%s\n' "$1" >>"$OUTPUT_FILE"
  fi
}

CONTAINER_ID="$(compose_container_id)"
if [[ -z "$CONTAINER_ID" ]]; then
  log "Nenhum container encontrado para o service '$SERVICE_NAME'. Suba com: docker compose up -d"
  exit 1
fi

wait_for_health

if [[ -n "$OUTPUT_FILE" ]]; then
  : >"$OUTPUT_FILE"
fi

BASELINE_MEM="$(current_mem_mib "$CONTAINER_ID")"

print_line "Benchmark de memoria"
print_line "API_URL: $API_URL"
print_line "Container: $CONTAINER_ID"
print_line "Identificadores: $(join_by ', ' "${IDENTIFIERS[@]}")"
print_line "Memoria em repouso: ${BASELINE_MEM} MiB"
print_line ""
print_line "Sequencial"

SEQUENTIAL_SUM=0
SEQUENTIAL_COUNT=0

for identifier in "${IDENTIFIERS[@]}"; do
  BEFORE_MEM="$(current_mem_mib "$CONTAINER_ID")"
  curl_request "$identifier" &
  REQUEST_PID=$!
  PEAK_MEM="$(measure_peak_while_running "$CONTAINER_ID" "$REQUEST_PID")"
  wait "$REQUEST_PID"
  AFTER_MEM="$(current_mem_mib "$CONTAINER_ID")"
  DELTA_FROM_BEFORE="$(awk -v peak="$PEAK_MEM" -v base="$BEFORE_MEM" 'BEGIN { printf "%.2f", peak - base }')"
  DELTA_FROM_IDLE="$(awk -v peak="$PEAK_MEM" -v base="$BASELINE_MEM" 'BEGIN { printf "%.2f", peak - base }')"
  print_line "- ${identifier}: antes=${BEFORE_MEM} MiB pico=${PEAK_MEM} MiB depois=${AFTER_MEM} MiB delta_antes=${DELTA_FROM_BEFORE} MiB delta_repouso=${DELTA_FROM_IDLE} MiB"
  SEQUENTIAL_SUM="$(awk -v sum="$SEQUENTIAL_SUM" -v delta="$DELTA_FROM_IDLE" 'BEGIN { printf "%.2f", sum + delta }')"
  SEQUENTIAL_COUNT=$((SEQUENTIAL_COUNT + 1))
done

SEQUENTIAL_AVG="$(awk -v sum="$SEQUENTIAL_SUM" -v count="$SEQUENTIAL_COUNT" 'BEGIN { if (count == 0) print "0.00"; else printf "%.2f", sum / count }')"
print_line "Media estimada por requisicao sequencial: ${SEQUENTIAL_AVG} MiB"
print_line ""
print_line "Paralelo"

PIDS=()
for identifier in "${IDENTIFIERS[@]}"; do
  curl_request "$identifier" &
  PIDS+=("$!")
done

PARALLEL_PEAK="$(measure_peak_while_running "$CONTAINER_ID" "${PIDS[@]}")"
for pid in "${PIDS[@]}"; do
  wait "$pid"
done

PARALLEL_AFTER="$(current_mem_mib "$CONTAINER_ID")"
PARALLEL_DELTA="$(awk -v peak="$PARALLEL_PEAK" -v base="$BASELINE_MEM" 'BEGIN { printf "%.2f", peak - base }')"
PARALLEL_PER_REQUEST="$(awk -v delta="$PARALLEL_DELTA" -v count="${#IDENTIFIERS[@]}" 'BEGIN { if (count == 0) print "0.00"; else printf "%.2f", delta / count }')"

print_line "- Pico paralelo: ${PARALLEL_PEAK} MiB"
print_line "- Delta paralelo vs repouso: ${PARALLEL_DELTA} MiB"
print_line "- Estimativa por requisicao em paralelo (${#IDENTIFIERS[@]} reqs): ${PARALLEL_PER_REQUEST} MiB"
print_line "- Memoria ao final: ${PARALLEL_AFTER} MiB"
