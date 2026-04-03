from __future__ import annotations

import asyncio
import base64
import re
from urllib.parse import quote_plus

from playwright.sync_api import Error, Page, sync_playwright

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


def wait_delay(page: Page, delay_ms: int = ACTION_DELAY_MS) -> None:
    page.wait_for_timeout(delay_ms)


def dismiss_cookie_banner(page: Page) -> None:
    selectors = [
        "button:has-text('Aceitar')",
        "button:has-text('Concordo')",
        "button:has-text('Continuar')",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count():
                wait_delay(page)
                locator.click(timeout=2000)
                wait_delay(page)
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


def wait_for_results(page: Page) -> int:
    for _ in range(DEFAULT_TIMEOUT_MS // 1000):
        try:
            count_locator = page.locator("#countResultados").first
            if count_locator.count():
                count_text = count_locator.inner_text().strip()
                if count_text.isdigit():
                    page.wait_for_timeout(RESULT_WAIT_MS)
                    return int(count_text)
        except Error:
            pass

        try:
            body_text = normalize_space(page.locator("body").inner_text())
            count_matches = re.findall(r"Foram encontrados\s+(\d+)\s+resultados", body_text)
            if count_matches:
                page.wait_for_timeout(RESULT_WAIT_MS)
                return int(count_matches[0])

            if re.search(r"Foram encontrados\s+0\s+resultados", body_text, flags=re.IGNORECASE):
                page.wait_for_timeout(RESULT_WAIT_MS)
                return 0
        except Error:
            pass

        try:
            result_links = page.locator("a.link-busca-nome, a[href*='/busca/pessoa-fisica/']")
            if result_links.count():
                page.wait_for_timeout(RESULT_WAIT_MS)
                return result_links.count()
        except Error:
            pass

        page.wait_for_timeout(RESULT_POLL_INTERVAL_MS)

    raise TimeoutError("Tempo excedido aguardando resultados da busca.")


def click_first_result(page: Page) -> str:
    result_link = page.locator("a.link-busca-nome, a[href*='/busca/pessoa-fisica/']").first
    result_link.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
    result_name = normalize_space(result_link.inner_text())
    wait_delay(page)
    with page.expect_navigation(wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS):
        result_link.click()
    wait_delay(page)
    if "/busca/pessoa-fisica/" not in page.url:
        raise RuntimeError("A navegacao para o detalhe da pessoa nao ocorreu.")
    return result_name


def open_recebimentos(page: Page) -> None:
    button = page.locator(
        "button.header[aria-controls='accordion-recebimentos-recursos']"
    ).first
    button.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
    wait_delay(page)
    button.click()
    wait_delay(page)


def capture_screenshot_base64(page: Page) -> str:
    image_bytes = page.screenshot(full_page=True, type="png")
    return base64.b64encode(image_bytes).decode("utf-8")


def click_detail(page: Page) -> str:
    detail_link = page.locator(
        "a#btnDetalharBpc, a.br-button.secondary.mt-3[href*='/beneficios/']"
    ).first
    detail_link.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
    href = detail_link.get_attribute("href") or ""
    expected_url_part = href if href.startswith("http") else f"{BASE_URL}{href}"
    wait_delay(page)
    with page.expect_navigation(wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS):
        detail_link.click()
    wait_delay(page)
    if expected_url_part and expected_url_part not in page.url and "/beneficios/" not in page.url:
        raise RuntimeError("A navegacao para o detalhe do beneficio nao ocorreu.")
    return page.url


def extract_section_data(page: Page) -> dict[str, object]:
    section = page.locator("section.dados-detalhados").first
    section.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
    raw_text = normalize_space(section.inner_text())
    lines = [line.strip() for line in section.inner_text().splitlines() if line.strip()]

    structured_rows: list[dict[str, str]] = []
    current_row: dict[str, str] = {}
    for line in lines:
        if ":" in line:
            key, value = line.split(":", 1)
            structured_rows.append({"campo": normalize_space(key), "valor": normalize_space(value)})
            current_row = {}
        else:
            if not current_row:
                current_row = {"campo": line, "valor": ""}
                structured_rows.append(current_row)
            else:
                if current_row["valor"]:
                    current_row["valor"] = f"{current_row['valor']} {normalize_space(line)}".strip()
                else:
                    current_row["valor"] = normalize_space(line)

    return {
        "url": page.url,
        "texto_bruto": raw_text,
        "campos": structured_rows,
    }


def slugify_label(value: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "_", value.lower())
    return raw.strip("_") or "campo"


def extract_person_summary(page: Page) -> dict[str, str | None]:
    sections = page.locator("section.dados-tabelados")
    count = sections.count()
    data: dict[str, str] = {}

    for index in range(count):
        section = sections.nth(index)
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

    return {
        "nome": data.get("nome"),
        "cpf": data.get("cpf"),
        "localidade": data.get("localidade"),
    }


def extract_detail_table(page: Page) -> dict[str, object]:
    table = page.locator("#tabelaDetalheDisponibilizado").first
    table.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)

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

    return {
        "cabecalhos": headers,
        "linhas": rows,
    }


def run_consulta_script(request: ConsultaScriptRequest) -> ConsultaScriptResultado:
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
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        try:
            termo = quote_plus(request.nome)
            search_url = SEARCH_URL_TEMPLATE.format(termo=termo)

            page.goto(search_url, wait_until="domcontentloaded")
            dismiss_cookie_banner(page)

            resultados = wait_for_results(page)

            if resultados == 0:
                return ConsultaScriptResultado(
                    status="sem_resultados",
                    nome_busca=request.nome,
                    url_busca=search_url,
                    evidencia_base64=capture_screenshot_base64(page),
                    mensagem=f'O nome pesquisado "{request.nome}" não possui nenhum benefício registrado.',
                    detalhe_portal=f'Foram encontrados 0 resultados para o termo "{request.nome}".',
                )

            nome_resultado = click_first_result(page)
            person_summary = extract_person_summary(page)
            evidencia_base64 = capture_screenshot_base64(page)

            open_recebimentos(page)

            url_detalhe = click_detail(page)
            dados = extract_section_data(page)
            tabela_detalhada = extract_detail_table(page)

            return ConsultaScriptResultado(
                status="sucesso",
                nome=person_summary["nome"],
                cpf=person_summary["cpf"],
                localidade=person_summary["localidade"],
                nome_busca=request.nome,
                resultado_clicado=nome_resultado,
                url_busca=search_url,
                url_detalhe=url_detalhe,
                evidencia_base64=evidencia_base64,
                #dados_detalhados=dados,
                tabela_detalhada=tabela_detalhada,
            )
        finally:
            context.close()
            browser.close()


class ScriptConsultaService:
    async def run(self, request: ConsultaScriptRequest) -> ConsultaScriptResultado:
        return await asyncio.wait_for(
            asyncio.to_thread(run_consulta_script, request),
            timeout=request.timeout_ms / 1000,
        )
