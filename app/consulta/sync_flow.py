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
    BENEFICIO_DETAIL_READY_SELECTORS,
    BENEFICIO_DETAIL_TABLE_SELECTORS,
    BROWSER_CHANNEL,
    build_beneficio_resumos,
    DEFAULT_WINDOWS_UA,
    FULL_PAGE_SCREENSHOT,
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


# Aplica ajustes de stealth no contexto do navegador sync.
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


# Espera um pequeno atraso humano respeitando o deadline.
def wait_delay_sync(page: SyncPage, deadline: float, delay_ms: int | None = None) -> None:
    effective_delay_ms = human_delay_ms() if delay_ms is None else delay_ms
    page.wait_for_timeout(min(effective_delay_ms, remaining_timeout_ms(deadline, effective_delay_ms)))


# Aguarda um locator ficar visivel ate o deadline.
def wait_for_locator_visible_sync(locator: SyncLocator, deadline: float) -> None:
    locator.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))


# Clica em um locator com pausa e validacao de visibilidade.
def click_with_stealth_pause_sync(page: SyncPage, locator: SyncLocator, deadline: float) -> None:
    wait_for_locator_visible_sync(locator, deadline)
    wait_delay_sync(page, deadline)
    locator.click(timeout=remaining_timeout_ms(deadline))


# Espera ate algum dos seletores ficar visivel e retorna o primeiro.
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


# Espera ate o checkbox atingir o estado desejado.
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


# Tenta fechar o banner de cookies se existir.
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


# Aplica o filtro de beneficiario de programa social na busca!
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


# Detecta e retorna a quantidade de resultados da busca!
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


# Clica no primeiro resultado e retorna o nome exibido!
def click_first_result_sync(page: SyncPage, deadline: float) -> str:
    result_link = page.locator("a.link-busca-nome, a[href*='/busca/pessoa-fisica/']").first
    wait_for_locator_visible_sync(result_link, deadline)
    result_name = normalize_space(result_link.inner_text())
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


# Abre o accordion de recebimentos e espera o conteudo aparecer!
def open_recebimentos_sync(page: SyncPage, deadline: float) -> None:
    button = page.locator(
        "button.header[aria-controls='accordion-recebimentos-recursos']"
    ).first
    content_selectors = [
        "#accordion-recebimentos-recursos table",
        "#accordion-recebimentos-recursos a#btnDetalharBpc",
        "#accordion-recebimentos-recursos a#btnDetalharBolsaFamilia",
        "#accordion-recebimentos-recursos a[href*='/beneficios/']",
    ]

    for attempt in range(3):
        for selector in content_selectors:
            try:
                if page.locator(selector).first.is_visible(
                    timeout=min(250, remaining_timeout_ms(deadline, 250))
                ):
                    return
            except SyncError:
                continue

        wait_for_locator_visible_sync(button, deadline)
        try:
            button.scroll_into_view_if_needed(timeout=remaining_timeout_ms(deadline))
        except SyncError:
            pass

        try:
            click_with_stealth_pause_sync(page, button, deadline)
        except SyncError:
            try:
                wait_delay_sync(page, deadline)
                button.click(force=True, timeout=remaining_timeout_ms(deadline))
            except SyncError:
                if attempt == 2:
                    raise

        try:
            wait_for_any_visible_sync(page, content_selectors, deadline)
            return
        except TimeoutError:
            if attempt == 2:
                raise


# Captura screenshot da pagina e retorna em base64.
def capture_screenshot_base64_sync(page: SyncPage) -> str:
    image_bytes = page.screenshot(full_page=FULL_PAGE_SCREENSHOT, type="png")
    return base64.b64encode(image_bytes).decode("utf-8")


# Extrai nome, CPF e localidade da pagina da pessoa.
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


# Extrai cabecalhos e linhas de uma tabela simples.
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


# Encontra o container da tabela para controles de paginacao.
def get_table_container_sync(table: SyncLocator) -> SyncLocator:
    return table.locator("xpath=ancestor::div[contains(@class,'wrapper-table')][1]").first


# Coleta estado da tabela para detectar mudancas de pagina.
def get_table_state_sync(table: SyncLocator, container: SyncLocator) -> tuple[str | None, int, str]:
    table_id = table.get_attribute("id")
    info_text = ""
    row_count = 0
    try:
        if table_id:
            info = container.locator(f"#{table_id}_info").first
            if info.count():
                info_text = normalize_space(info.inner_text())
    except SyncError:
        info_text = ""

    try:
        row_count = table.locator("tbody tr").count()
    except SyncError:
        row_count = 0

    first_row_text = ""
    if row_count:
        try:
            first_row_text = normalize_space(table.locator("tbody tr").first.inner_text())
        except SyncError:
            first_row_text = ""

    return info_text or None, row_count, first_row_text


# Espera a tabela mudar de estado apos interacao.
def wait_for_table_state_change_sync(
    page: SyncPage,
    table: SyncLocator,
    container: SyncLocator,
    previous_state: tuple[str | None, int, str],
    deadline: float,
) -> None:
    while True:
        current_state = get_table_state_sync(table, container)
        if current_state != previous_state:
            return
        page.wait_for_timeout(min(150, remaining_timeout_ms(deadline, 150)))


# Tenta ativar paginacao completa quando disponivel.
def maybe_click_full_pagination_sync(
    page: SyncPage,
    table: SyncLocator,
    container: SyncLocator,
    deadline: float,
) -> None:
    button = container.locator("#btnPaginacaoCompleta, button:has-text('Paginação completa')").first
    try:
        if button.count() and button.is_visible(timeout=min(300, remaining_timeout_ms(deadline, 300))):
            previous_state = get_table_state_sync(table, container)
            click_with_stealth_pause_sync(page, button, deadline)
            wait_for_table_state_change_sync(page, table, container, previous_state, deadline)
    except SyncError:
        return


# Aumenta o tamanho da pagina da tabela quando possivel.
def maybe_expand_table_page_size_sync(
    page: SyncPage,
    table: SyncLocator,
    container: SyncLocator,
    deadline: float,
) -> None:
    table_id = table.get_attribute("id")
    if not table_id:
        return

    select = container.locator(
        f"select[name='{table_id}_length'], select[aria-controls='{table_id}']"
    ).first
    try:
        if not select.count():
            return
        option_values = [
            int(value)
            for value in (select.locator("option").evaluate_all("(options) => options.map((option) => option.value)") or [])
            if str(value).isdigit()
        ]
        if not option_values:
            return
        max_value = str(max(option_values))
        if select.input_value() != max_value:
            previous_state = get_table_state_sync(table, container)
            select.select_option(value=max_value, timeout=remaining_timeout_ms(deadline))
            wait_for_table_state_change_sync(page, table, container, previous_state, deadline)
    except SyncError:
        return


# Le informacao de pagina atual e total da tabela.
def get_table_page_info_sync(container: SyncLocator, table_id: str | None) -> tuple[int, int] | None:
    selectors = []
    if table_id:
        selectors.append(f"#{table_id}_info")
    selectors.append(".dataTables_info")

    for selector in selectors:
        info = container.locator(selector).first
        try:
            if not info.count():
                continue
            text = normalize_space(info.inner_text())
        except SyncError:
            continue
        match = re.search(r"Página\s+(\d+)\s+de\s+(\d+)", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


# Navega para a proxima pagina da tabela se existir.
def go_to_next_table_page_sync(
    page: SyncPage,
    table: SyncLocator,
    container: SyncLocator,
    deadline: float,
) -> bool:
    table_id = table.get_attribute("id")
    next_candidates = []
    if table_id:
        next_candidates.append(f"#{table_id}_next")
    next_candidates.append(".paginate_button.next")

    next_item: SyncLocator | None = None
    for selector in next_candidates:
        candidate = container.locator(selector).first
        try:
            if candidate.count():
                next_item = candidate
                break
        except SyncError:
            continue

    if next_item is None:
        return False

    try:
        class_name = (next_item.get_attribute("class") or "").lower()
        if "disabled" in class_name:
            return False
    except SyncError:
        return False

    next_button = next_item.locator("button, a").first
    try:
        previous_state = get_table_state_sync(table, container)
        click_with_stealth_pause_sync(page, next_button, deadline)
        wait_for_table_state_change_sync(page, table, container, previous_state, deadline)
        return True
    except SyncError:
        return False


# Extrai todas as linhas de uma tabela paginada.
def extract_all_table_rows_sync(
    page: SyncPage,
    table: SyncLocator,
    deadline: float,
) -> tuple[list[str], list[dict[str, str]]]:
    container = get_table_container_sync(table)
    maybe_click_full_pagination_sync(page, table, container, deadline)
    maybe_expand_table_page_size_sync(page, table, container, deadline)

    headers: list[str] = []
    rows: list[dict[str, str]] = []
    seen_rows: set[tuple[tuple[str, str], ...]] = set()
    page_guard = 0

    while True:
        current_headers, current_rows = extract_table_rows_sync(table)
        if current_headers and not headers:
            headers = current_headers
        for row in current_rows:
            row_key = tuple(sorted(row.items()))
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)
            rows.append(row)

        page_info = get_table_page_info_sync(container, table.get_attribute("id"))
        if page_info and page_info[0] >= page_info[1]:
            break
        if page_info is None and not go_to_next_table_page_sync(page, table, container, deadline):
            break
        if page_info is not None and not go_to_next_table_page_sync(page, table, container, deadline):
            break

        page_guard += 1
        if page_guard >= 100:
            break

    return headers, rows


# Extrai as linhas da tabela de recebimentos.
def extract_recebimento_rows_sync(page: SyncPage, deadline: float) -> list[dict[str, str]]:
    accordion = page.locator("#accordion-recebimentos-recursos").first
    accordion.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    table = accordion.locator("table").first
    table.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    _, rows = extract_table_rows_sync(table)
    return rows


# Resume NIS e valor recebido a partir da primeira linha.
def extract_recebimento_summary_sync(page: SyncPage, deadline: float) -> dict[str, str | None]:
    rows = extract_recebimento_rows_sync(page, deadline)
    first_row = rows[0] if rows else {}
    return get_recebimento_summary_from_row(first_row)


# Coleta os links de detalhamento de beneficios.
def extract_beneficio_links_sync(page: SyncPage, deadline: float) -> list[dict[str, str | None]]:
    accordion = page.locator("#accordion-recebimentos-recursos").first
    accordion.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    detail_link = wait_for_any_visible_sync(
        page,
        [
            "#accordion-recebimentos-recursos a#btnDetalharBpc",
            "#accordion-recebimentos-recursos a#btnDetalharBolsaFamilia",
            "#accordion-recebimentos-recursos a.br-button.secondary.mt-3[href*='/beneficios/']",
            "#accordion-recebimentos-recursos a[href*='/beneficios/']",
        ],
        deadline,
    )
    detail_link.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))

    links = accordion.locator("a.br-button.secondary.mt-3[href*='/beneficios/'], a[href*='/beneficios/']")
    link_count = links.count()
    beneficios: list[dict[str, str | None]] = []

    for index in range(link_count):
        link = links.nth(index)
        href = link.get_attribute("href") or ""
        if not href:
            continue
        beneficios.append(
            {
                "id": link.get_attribute("id"),
                "texto": normalize_space(link.inner_text()),
                "url": href if href.startswith("http") else f"{BASE_URL}{href}",
            }
        )

    if not beneficios:
        raise RuntimeError("Nenhum link de detalhe de beneficio foi encontrado.")

    return beneficios


# Localiza a tabela de detalhe do beneficio na pagina.
def find_detail_table_sync(page: SyncPage, deadline: float) -> SyncLocator:
    wait_for_any_visible_sync(page, BENEFICIO_DETAIL_READY_SELECTORS, deadline)

    while True:
        for selector in BENEFICIO_DETAIL_TABLE_SELECTORS:
            locator = page.locator(selector)
            count = locator.count()
            for index in range(count):
                table = locator.nth(index)
                try:
                    header_count = table.locator("thead th").count()
                    row_count = table.locator("tbody tr").count()
                    if header_count or row_count:
                        return table
                except SyncError:
                    continue

        page.wait_for_timeout(min(150, remaining_timeout_ms(deadline, 150)))


# Extrai cabecalhos e linhas da tabela detalhada.
def extract_detail_table_sync(page: SyncPage, deadline: float) -> dict[str, object]:
    table = find_detail_table_sync(page, deadline)
    headers, rows = extract_all_table_rows_sync(page, table, deadline)
    return {"cabecalhos": headers, "linhas": rows}


# Fecha todas as paginas abertas no contexto.
def close_all_pages_sync(page: SyncPage) -> None:
    for opened_page in list(page.context.pages):
        try:
            opened_page.close()
        except SyncError:
            continue


# Abre o detalhe do beneficio e extrai a tabela detalhada.
def extract_beneficio_detail_sync(
    page: SyncPage,
    detail_url: str,
    deadline: float,
) -> dict[str, object]:
    page.goto(
        detail_url,
        wait_until="domcontentloaded",
        timeout=remaining_timeout_ms(deadline),
    )
    wait_for_any_visible_sync(page, BENEFICIO_DETAIL_READY_SELECTORS, deadline)
    if detail_url not in page.url and "/beneficios/" not in page.url:
        raise RuntimeError("A navegacao para o detalhe do beneficio nao ocorreu.")
    tabela_detalhada = extract_detail_table_sync(page, deadline)
    return {
        "url_detalhe": page.url,
        "tabela_detalhada": tabela_detalhada,
    }


# Executa o fluxo completo de consulta usando Playwright sync!
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
            # Tenta fechar o banner de cookies se existir.
            dismiss_cookie_banner_sync(page, deadline)
            # Aplica o filtro de beneficiario de programa social na busca.
            apply_programa_social_filter_sync(page, deadline)

            # Detecta e retorna a quantidade de resultados da busca.
            resultados = wait_for_results_sync(page, deadline)
            if resultados == 0:
                return ConsultaScriptResultado(
                    status="sem_resultados",
                    nome_busca=request.identificador,
                    url_busca=search_url,
                    evidencia_base64=capture_screenshot_base64_sync(page),
                )

            nome_resultado = click_first_result_sync(page, deadline)
            person_summary = extract_person_summary_sync(page)
            open_recebimentos_sync(page, deadline)
            recebimento_rows = extract_recebimento_rows_sync(page, deadline)
            beneficio_links = extract_beneficio_links_sync(page, deadline)
            evidencia_base64 = capture_screenshot_base64_sync(page)
            beneficios_resumo = build_beneficio_resumos(
                rows=recebimento_rows,
                detail_links=beneficio_links,
                nome=nome_resultado,
            )
            beneficios_detalhados: list[dict[str, object]] = []
            for beneficio in beneficios_resumo:
                beneficios_detalhados.append(
                    {
                        **beneficio,
                        **extract_beneficio_detail_sync(page, beneficio["url_detalhe"], deadline),
                    }
                )

            return ConsultaScriptResultado(
                status="sucesso",
                nome=nome_resultado,
                cpf=person_summary["cpf"],
                localidade=person_summary["localidade"],
                nome_busca=request.identificador,
                resultado_clicado=nome_resultado,
                url_busca=search_url,
                evidencia_base64=evidencia_base64,
                beneficios=beneficios_detalhados,
            )
        except SyncPlaywrightTimeoutError as exc:
            raise TimeoutError("Não foi possível retornar os dados no tempo de resposta solicitado") from exc
        finally:
            close_all_pages_sync(page)
            try:
                context.close()
            finally:
                browser.close()
