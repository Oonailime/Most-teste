from __future__ import annotations

import asyncio
import base64
import re
import time
from urllib.parse import quote_plus

from playwright.sync_api import Error, Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

try:
    from app.models import ConsultaScriptRequest, ConsultaScriptResultado
except ModuleNotFoundError:
    from models import ConsultaScriptRequest, ConsultaScriptResultado

BASE_URL = "https://portaldatransparencia.gov.br"
SEARCH_URL_TEMPLATE = (
    f"{BASE_URL}/pessoa-fisica/busca/lista?termo={{termo}}&pagina=1&tamanhoPagina=10"
)
ACTION_DELAY_MS = 2500
RESULT_WAIT_MS = 1000
RESULT_POLL_INTERVAL_MS = 2000
DEFAULT_TIMEOUT_MS = 60000
DEFAULT_WINDOWS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0"
)


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


def wait_delay(page: Page, deadline: float, delay_ms: int = ACTION_DELAY_MS) -> None:
    page.wait_for_timeout(min(delay_ms, remaining_timeout_ms(deadline, delay_ms)))


def dismiss_cookie_banner(page: Page, deadline: float) -> None:
    selectors = [
        "button:has-text('Aceitar')",
        "button:has-text('Concordo')",
        "button:has-text('Continuar')",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count():
                wait_delay(page, deadline)
                locator.click(timeout=min(2000, remaining_timeout_ms(deadline, 2000)))
                wait_delay(page, deadline)
                return
        except Error:
            continue


def apply_stealth(page: Page) -> None:
    page.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });
        Object.defineProperty(navigator, 'languages', {
            get: () => ['pt-BR', 'pt', 'en-US', 'en'],
        });
        Object.defineProperty(navigator, 'platform', {
            get: () => 'Win32',
        });
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        window.chrome = window.chrome || {
            runtime: {},
            app: {},
        };
        """
    )


def wait_for_results(page: Page, deadline: float) -> int:
    while True:
        remaining_ms = remaining_timeout_ms(deadline)
        try:
            count_locator = page.locator("#countResultados").first
            if count_locator.count():
                count_text = count_locator.inner_text().strip()
                if count_text.isdigit():
                    page.wait_for_timeout(min(RESULT_WAIT_MS, remaining_ms))
                    return int(count_text)
        except Error:
            pass

        try:
            body_text = normalize_space(page.locator("body").inner_text())
            count_matches = re.findall(r"Foram encontrados\s+(\d+)\s+resultados", body_text)
            if count_matches:
                page.wait_for_timeout(min(RESULT_WAIT_MS, remaining_ms))
                return int(count_matches[0])

            if re.search(r"Foram encontrados\s+0\s+resultados", body_text, flags=re.IGNORECASE):
                page.wait_for_timeout(min(RESULT_WAIT_MS, remaining_ms))
                return 0
        except Error:
            pass

        try:
            result_links = page.locator("a.link-busca-nome, a[href*='/busca/pessoa-fisica/']")
            if result_links.count():
                page.wait_for_timeout(min(RESULT_WAIT_MS, remaining_ms))
                return result_links.count()
        except Error:
            pass

        page.wait_for_timeout(min(RESULT_POLL_INTERVAL_MS, remaining_ms))


def click_first_result(page: Page, deadline: float) -> str:
    result_link = page.locator("a.link-busca-nome, a[href*='/busca/pessoa-fisica/']").first
    result_link.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    result_name = normalize_space(result_link.inner_text())
    wait_delay(page, deadline)
    with page.expect_navigation(wait_until="domcontentloaded", timeout=remaining_timeout_ms(deadline)):
        result_link.click()
    wait_delay(page, deadline)
    if "/busca/pessoa-fisica/" not in page.url:
        raise RuntimeError("A navegacao para o detalhe da pessoa nao ocorreu.")
    return result_name


def open_recebimentos(page: Page, deadline: float) -> None:
    button = page.locator(
        "button.header[aria-controls='accordion-recebimentos-recursos']"
    ).first
    button.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    wait_delay(page, deadline)
    button.click()
    wait_delay(page, deadline)


def capture_screenshot_base64(page: Page) -> str:
    image_bytes = page.screenshot(full_page=True, type="png")
    return base64.b64encode(image_bytes).decode("utf-8")


def click_detail(page: Page, deadline: float) -> str:
    detail_link = page.locator(
        "a#btnDetalharBpc, a.br-button.secondary.mt-3[href*='/beneficios/']"
    ).first
    detail_link.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    href = detail_link.get_attribute("href") or ""
    expected_url_part = href if href.startswith("http") else f"{BASE_URL}{href}"
    wait_delay(page, deadline)
    with page.expect_navigation(wait_until="domcontentloaded", timeout=remaining_timeout_ms(deadline)):
        detail_link.click()
    wait_delay(page, deadline)
    if expected_url_part and expected_url_part not in page.url and "/beneficios/" not in page.url:
        raise RuntimeError("A navegacao para o detalhe do beneficio nao ocorreu.")
    return page.url


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


def extract_person_summary(page: Page) -> dict[str, str | None]:
    sections = page.locator("section.dados-tabelados")
    count = sections.count()
    data: dict[str, str] = {}
    section_texts: list[str] = []

    for index in range(count):
        section = sections.nth(index)
        try:
            section_texts.append(normalize_space(section.inner_text()))
        except Error:
            pass
        rows = section.locator("li, tr, .row, .col, .dados-tabelados__item")
        row_count = rows.count()
        for row_index in range(row_count):
            row = rows.nth(row_index)
            texts = [normalize_space(text) for text in row.locator(":scope *").all_inner_texts()]
            texts = [text for text in texts if text]
            if len(texts) < 2:
                continue

            key = slugify_label(texts[0])
            value = texts[1] if len(texts) == 2 else " ".join(texts[1:])
            data[key] = value

    combined_text = " ".join(section_texts)
    cpf = data.get("cpf") or find_summary_value(
        combined_text,
        ["cpf"],
        ["localidade", "imprimir"],
    )
    localidade = data.get("localidade") or find_summary_value(
        combined_text,
        ["localidade"],
        ["imprimir"],
    )

    return {
        "nome": data.get("nome"),
        "cpf": cpf,
        "localidade": localidade,
    }


def extract_table_rows(table: Locator) -> tuple[list[str], list[dict[str, str]]]:
    headers = [
        normalize_space(item)
        for item in table.locator("thead th").all_inner_texts()
        if normalize_space(item)
    ]

    rows_locator = table.locator("tbody tr")
    row_count = rows_locator.count()
    rows: list[dict[str, str]] = []

    for index in range(row_count):
        row = rows_locator.nth(index)
        values = [
            clean_table_cell(item, headers)
            for item in row.locator("td").all_inner_texts()
        ]
        if not values:
            continue

        if headers and len(headers) == len(values):
            rows.append({header: value for header, value in zip(headers, values, strict=False)})
        else:
            rows.append({f"coluna_{position + 1}": value for position, value in enumerate(values)})

    return headers, rows


def get_first_present(data: dict[str, str], candidates: list[str]) -> str | None:
    normalized = {normalize_space(key).casefold(): value for key, value in data.items()}
    for candidate in candidates:
        value = normalized.get(candidate.casefold())
        if value:
            return value
    return None


def extract_recebimento_summary(page: Page, deadline: float) -> dict[str, str | None]:
    accordion = page.locator("#accordion-recebimentos-recursos").first
    accordion.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    table = accordion.locator("table").first
    table.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    _, rows = extract_table_rows(table)
    first_row = rows[0] if rows else {}

    return {
        "nis": get_first_present(first_row, ["NIS"]),
        "valor_recebido": get_first_present(
            first_row,
            ["Valor Recebido", "Valor", "Valor do benefício", "Valor do beneficio"],
        ),
    }


def extract_detail_table(page: Page, deadline: float) -> dict[str, object]:
    table = page.locator("#tabelaDetalheDisponibilizado").first
    table.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    headers, rows = extract_table_rows(table)

    return {
        "cabecalhos": headers,
        "linhas": rows,
    }


def run_consulta_script(request: ConsultaScriptRequest) -> ConsultaScriptResultado:
    deadline = monotonic_deadline(request.timeout_ms)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel=request.browser_channel,
            headless=request.headless,
            args=[
                "--start-maximized",
                "--disable-notifications",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1600, "height": 2200},
            locale="pt-BR",
            user_agent=DEFAULT_WINDOWS_UA,
        )
        page = context.new_page()
        apply_stealth(page)
        page.set_default_timeout(request.timeout_ms)

        try:
            termo = quote_plus(request.identificador)
            search_url = SEARCH_URL_TEMPLATE.format(termo=termo)

            page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=remaining_timeout_ms(deadline),
            )
            dismiss_cookie_banner(page, deadline)

            resultados = wait_for_results(page, deadline)

            if resultados == 0:
                return ConsultaScriptResultado(
                    status="sem_resultados",
                    nome_busca=request.identificador,
                    url_busca=search_url,
                    evidencia_base64=capture_screenshot_base64(page),
                    mensagem=(
                        f'O identificador pesquisado "{request.identificador}" '
                        "não possui nenhum benefício registrado."
                    ),
                    detalhe_portal=(
                        f'Foram encontrados 0 resultados para o termo "{request.identificador}".'
                    ),
                )

            nome_resultado = click_first_result(page, deadline)
            person_summary = extract_person_summary(page)

            open_recebimentos(page, deadline)
            recebimento_summary = extract_recebimento_summary(page, deadline)
            evidencia_base64 = capture_screenshot_base64(page)

            url_detalhe = click_detail(page, deadline)
            tabela_detalhada = extract_detail_table(page, deadline)

            return ConsultaScriptResultado(
                status="sucesso",
                nome=nome_resultado,
                nis=recebimento_summary["nis"],
                cpf=person_summary["cpf"],
                localidade=person_summary["localidade"],
                valor_recebido=recebimento_summary["valor_recebido"],
                nome_busca=request.identificador,
                resultado_clicado=nome_resultado,
                url_busca=search_url,
                url_detalhe=url_detalhe,
                evidencia_base64=evidencia_base64,
                tabela_detalhada=tabela_detalhada,
            )
        except PlaywrightTimeoutError as exc:
            raise TimeoutError("Não foi possível retornar os dados no tempo de resposta solicitado") from exc
        finally:
            context.close()
            browser.close()


class ScriptConsultaService:
    async def run(self, request: ConsultaScriptRequest) -> ConsultaScriptResultado:
        return await asyncio.to_thread(run_consulta_script, request)
