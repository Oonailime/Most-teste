from __future__ import annotations

import os
import random
import re
import sys
import time

BASE_URL = "https://portaldatransparencia.gov.br"
SEARCH_URL_TEMPLATE = (
    f"{BASE_URL}/pessoa-fisica/busca/lista?termo={{termo}}&pagina=1&tamanhoPagina=10"
)
ACTION_DELAY_MS = 600
ACTION_JITTER_MS = 200
RESULT_POLL_INTERVAL_MS = 2000
DEFAULT_TIMEOUT_MS = 60000
MAX_CONCURRENT_CONSULTAS = int(os.getenv("MAX_CONCURRENT_CONSULTAS", "6"))
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "chromium")
ALLOW_HEADFUL_BROWSER = os.getenv("ALLOW_HEADFUL_BROWSER", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DEFAULT_WINDOWS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0"
)
USE_LOCAL_SYNC_FALLBACK = sys.platform == "win32" and sys.version_info >= (3, 14)


def monotonic_deadline(timeout_ms: int) -> float:
    return time.monotonic() + (timeout_ms / 1000)


def remaining_timeout_ms(deadline: float, fallback_ms: int = DEFAULT_TIMEOUT_MS) -> int:
    remaining_ms = int((deadline - time.monotonic()) * 1000)
    if remaining_ms <= 0:
        raise TimeoutError("Não foi possível retornar os dados no tempo de resposta solicitado")
    return min(remaining_ms, fallback_ms)


def normalize_space(value: str) -> str:
    return " ".join(value.split())


def clean_table_cell(value: str, headers: list[str]) -> str:
    cleaned = normalize_space(value)
    if not cleaned or not headers:
        return cleaned

    for header in sorted((item for item in headers if item), key=len, reverse=True):
        leading_pattern = rf"^(?:{re.escape(header)}\s+)+"
        trailing_pattern = rf"(?:\s+{re.escape(header)})+$"
        updated = re.sub(leading_pattern, "", cleaned)
        updated = re.sub(trailing_pattern, "", updated)
        cleaned = normalize_space(updated)

    return cleaned


def human_delay_ms(base_ms: int = ACTION_DELAY_MS, jitter_ms: int = ACTION_JITTER_MS) -> int:
    if jitter_ms <= 0:
        return base_ms
    lower_bound = max(150, base_ms - jitter_ms)
    upper_bound = max(lower_bound, base_ms + jitter_ms)
    return random.randint(lower_bound, upper_bound)


def slugify_label(value: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "_", value.lower())
    return raw.strip("_") or "campo"


def find_summary_value(text: str, labels: list[str], stop_labels: list[str] | None = None) -> str | None:
    normalized_text = normalize_space(text)
    escaped_labels = "|".join(re.escape(label) for label in labels)
    stop_pattern = r"|".join(re.escape(label) for label in (stop_labels or []))
    pattern = (
        rf"(?:{escaped_labels})\s*:?\s*(.+?)"
        rf"(?=\s+(?:{stop_pattern})\b|\s*$)"
    )
    match = re.search(pattern, normalized_text, flags=re.IGNORECASE)
    if not match:
        return None
    value = normalize_space(match.group(1))
    return value or None


def get_first_present(data: dict[str, str], candidates: list[str]) -> str | None:
    normalized = {normalize_space(key).casefold(): value for key, value in data.items()}
    for candidate in candidates:
        value = normalized.get(candidate.casefold())
        if value:
            return value
    return None

