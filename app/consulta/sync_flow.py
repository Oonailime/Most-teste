from __future__ import annotations

import base64
import re
from urllib.parse import quote_plus

from playwright.sync_api import Error as SyncError
from playwright.sync_api import Locator as SyncLocator
from playwright.sync_api import Page as SyncPage
from playwright.sync_api import TimeoutError as SyncPlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.consulta.common import (
    BASE_URL,
    BROWSER_CHANNEL,
    DEFAULT_WINDOWS_UA,
    RESULT_POLL_INTERVAL_MS,
    SEARCH_URL_TEMPLATE,
    clean_table_cell,
    find_summary_value,
    get_first_present,
    human_delay_ms,
    monotonic_deadline,
    normalize_space,
    remaining_timeout_ms,
    slugify_label,
)
from app.models import ConsultaScriptRequest, ConsultaScriptResultado


def apply_stealth_sync(page: SyncPage) -> None:
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


def wait_delay_sync(page: SyncPage, deadline: float, delay_ms: int | None = None) -> None:
    effective_delay_ms = human_delay_ms() if delay_ms is None else delay_ms
    page.wait_for_timeout(min(effective_delay_ms, remaining_timeout_ms(deadline, effective_delay_ms)))


def wait_for_locator_visible_sync(locator: SyncLocator, deadline: float) -> None:
    locator.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))


def click_with_stealth_pause_sync(page: SyncPage, locator: SyncLocator, deadline: float) -> None:
    wait_for_locator_visible_sync(locator, deadline)
    wait_delay_sync(page, deadline)
    locator.click(timeout=remaining_timeout_ms(deadline))


def wait_for_any_visible_sync(page: SyncPage, selectors: list[str], deadline: float) -> SyncLocator:
    while True:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if locator.is_visible(timeout=min(300, remaining_timeout_ms(deadline, 300))):
                    return locator
            except SyncError:
                continue
        page.wait_for_timeout(min(150, remaining_timeout_ms(deadline, 150)))


def wait_for_checkbox_state_sync(
    page: SyncPage,
    checkbox: SyncLocator,
    checked: bool,
    deadline: float,
) -> None:
    while True:
        try:
            if checkbox.is_checked() == checked:
                return
        except SyncError:
            pass
        page.wait_for_timeout(min(150, remaining_timeout_ms(deadline, 150)))


def dismiss_cookie_banner_sync(page: SyncPage, deadline: float) -> None:
    for selector in [
        "button:has-text('Aceitar')",
        "button:has-text('Concordo')",
        "button:has-text('Continuar')",
    ]:
        try:
            locator = page.locator(selector).first
            if locator.count():
                click_with_stealth_pause_sync(page, locator, deadline)
                return
        except SyncError:
            continue


def apply_programa_social_filter_sync(page: SyncPage, deadline: float) -> None:
    refine_button = page.locator("button.header[aria-controls='box-busca-refinada']").first
    refine_box = page.locator("#box-busca-refinada").first
    checkbox = page.locator("#beneficiarioProgramaSocial").first
    checkbox_label = page.locator("label[for='beneficiarioProgramaSocial']").first

    wait_for_locator_visible_sync(refine_button, deadline)
    if not refine_box.is_visible(timeout=300):
        click_with_stealth_pause_sync(page, refine_button, deadline)
        wait_for_locator_visible_sync(refine_box, deadline)

    wait_for_locator_visible_sync(checkbox, deadline)
    if not checkbox.is_checked():
        wait_delay_sync(page, deadline)
        checkbox.scroll_into_view_if_needed(timeout=remaining_timeout_ms(deadline))
        try:
            click_with_stealth_pause_sync(page, checkbox_label, deadline)
        except SyncError:
            checkbox.check(force=True, timeout=remaining_timeout_ms(deadline))
        wait_for_checkbox_state_sync(page, checkbox, True, deadline)

    consult_button = page.locator("#btnConsultarPF").first
    with page.expect_navigation(
        wait_until="domcontentloaded",
        timeout=remaining_timeout_ms(deadline),
    ):
        click_with_stealth_pause_sync(page, consult_button, deadline)

    wait_for_any_visible_sync(
        page,
        [
            "#countResultados",
            "a.link-busca-nome",
            "a[href*='/busca/pessoa-fisica/']",
            "text=Foram encontrados",
        ],
        deadline,
    )


def wait_for_results_sync(page: SyncPage, deadline: float) -> int:
    while True:
        remaining_ms = remaining_timeout_ms(deadline)
        try:
            count_locator = page.locator("#countResultados").first
            if count_locator.count():
                count_text = count_locator.inner_text().strip()
                if count_text.isdigit():
                    return int(count_text)
        except SyncError:
            pass

        try:
            body_text = normalize_space(page.locator("body").inner_text())
            count_matches = re.findall(r"Foram encontrados\s+(\d+)\s+resultados", body_text)
            if count_matches:
                return int(count_matches[0])
            if re.search(r"Foram encontrados\s+0\s+resultados", body_text, flags=re.IGNORECASE):
                return 0
        except SyncError:
            pass

        try:
            result_links = page.locator("a.link-busca-nome, a[href*='/busca/pessoa-fisica/']")
            count = result_links.count()
            if count:
                return count
        except SyncError:
            pass

        page.wait_for_timeout(min(RESULT_POLL_INTERVAL_MS, remaining_ms))


def click_first_result_sync(page: SyncPage, deadline: float) -> str:
    result_link = page.locator("a.link-busca-nome, a[href*='/busca/pessoa-fisica/']").first
    wait_for_locator_visible_sync(result_link, deadline)
    result_name = normalize_space(result_link.inner_text())
    with page.expect_navigation(
        wait_until="domcontentloaded",
        timeout=remaining_timeout_ms(deadline),
    ):
        click_with_stealth_pause_sync(page, result_link, deadline)
    wait_for_any_visible_sync(
        page,
        [
            "section.dados-tabelados",
            "button.header[aria-controls='accordion-recebimentos-recursos']",
        ],
        deadline,
    )
    if "/busca/pessoa-fisica/" not in page.url:
        raise RuntimeError("A navegacao para o detalhe da pessoa nao ocorreu.")
    return result_name


def open_recebimentos_sync(page: SyncPage, deadline: float) -> None:
    button = page.locator(
        "button.header[aria-controls='accordion-recebimentos-recursos']"
    ).first
    click_with_stealth_pause_sync(page, button, deadline)
    wait_for_any_visible_sync(
        page,
        [
            "#accordion-recebimentos-recursos table",
            "#accordion-recebimentos-recursos a#btnDetalharBpc",
            "#accordion-recebimentos-recursos a[href*='/beneficios/']",
        ],
        deadline,
    )


def capture_screenshot_base64_sync(page: SyncPage) -> str:
    image_bytes = page.screenshot(full_page=True, type="png")
    return base64.b64encode(image_bytes).decode("utf-8")


def click_detail_sync(page: SyncPage, deadline: float) -> str:
    detail_link = wait_for_any_visible_sync(
        page,
        [
            "a#btnDetalharBpc",
            "a.br-button.secondary.mt-3[href*='/beneficios/']",
        ],
        deadline,
    )
    href = detail_link.get_attribute("href") or ""
    expected_url_part = href if href.startswith("http") else f"{BASE_URL}{href}"
    with page.expect_navigation(
        wait_until="domcontentloaded",
        timeout=remaining_timeout_ms(deadline),
    ):
        click_with_stealth_pause_sync(page, detail_link, deadline)
    wait_for_any_visible_sync(
        page,
        [
            "#tabelaDetalheDisponibilizado",
            "section.dados-detalhados",
        ],
        deadline,
    )
    if expected_url_part and expected_url_part not in page.url and "/beneficios/" not in page.url:
        raise RuntimeError("A navegacao para o detalhe do beneficio nao ocorreu.")
    return page.url


def extract_person_summary_sync(page: SyncPage) -> dict[str, str | None]:
    sections = page.locator("section.dados-tabelados")
    count = sections.count()
    data: dict[str, str] = {}
    section_texts: list[str] = []

    for index in range(count):
        section = sections.nth(index)
        try:
            section_texts.append(normalize_space(section.inner_text()))
        except SyncError:
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
    cpf = data.get("cpf") or find_summary_value(combined_text, ["cpf"], ["localidade", "imprimir"])
    localidade = data.get("localidade") or find_summary_value(
        combined_text,
        ["localidade"],
        ["imprimir"],
    )
    return {"nome": data.get("nome"), "cpf": cpf, "localidade": localidade}


def extract_table_rows_sync(table: SyncLocator) -> tuple[list[str], list[dict[str, str]]]:
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


def extract_recebimento_summary_sync(page: SyncPage, deadline: float) -> dict[str, str | None]:
    accordion = page.locator("#accordion-recebimentos-recursos").first
    accordion.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    table = accordion.locator("table").first
    table.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    _, rows = extract_table_rows_sync(table)
    first_row = rows[0] if rows else {}
    return {
        "nis": get_first_present(first_row, ["NIS"]),
        "valor_recebido": get_first_present(
            first_row,
            ["Valor Recebido", "Valor", "Valor do benefício", "Valor do beneficio"],
        ),
    }


def extract_detail_table_sync(page: SyncPage, deadline: float) -> dict[str, object]:
    table = page.locator("#tabelaDetalheDisponibilizado").first
    table.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    headers, rows = extract_table_rows_sync(table)
    return {"cabecalhos": headers, "linhas": rows}


def run_consulta_script_sync(request: ConsultaScriptRequest) -> ConsultaScriptResultado:
    deadline = monotonic_deadline(request.timeout_ms)
    termo = quote_plus(request.identificador)
    search_url = SEARCH_URL_TEMPLATE.format(termo=termo)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel=BROWSER_CHANNEL,
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

        try:
            apply_stealth_sync(page)
            page.set_default_timeout(request.timeout_ms)
            page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=remaining_timeout_ms(deadline),
            )
            dismiss_cookie_banner_sync(page, deadline)
            apply_programa_social_filter_sync(page, deadline)

            resultados = wait_for_results_sync(page, deadline)
            if resultados == 0:
                return ConsultaScriptResultado(
                    status="sem_resultados",
                    nome_busca=request.identificador,
                    url_busca=search_url,
                    evidencia_base64=capture_screenshot_base64_sync(page),
                    mensagem=(
                        f'O identificador pesquisado "{request.identificador}" '
                        "não possui nenhum benefício registrado."
                    ),
                    detalhe_portal=(
                        f'Foram encontrados 0 resultados para o termo "{request.identificador}".'
                    ),
                )

            nome_resultado = click_first_result_sync(page, deadline)
            person_summary = extract_person_summary_sync(page)
            open_recebimentos_sync(page, deadline)
            recebimento_summary = extract_recebimento_summary_sync(page, deadline)
            evidencia_base64 = capture_screenshot_base64_sync(page)
            url_detalhe = click_detail_sync(page, deadline)
            tabela_detalhada = extract_detail_table_sync(page, deadline)

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
        except SyncPlaywrightTimeoutError as exc:
            raise TimeoutError("Não foi possível retornar os dados no tempo de resposta solicitado") from exc
        finally:
            context.close()
            browser.close()
