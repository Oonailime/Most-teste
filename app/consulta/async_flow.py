from __future__ import annotations

import base64
import re
from urllib.parse import quote_plus

from playwright.async_api import Error, Locator, Page

from app.consulta.common import (
    BASE_URL,
    BENEFICIO_DETAIL_READY_SELECTORS,
    BENEFICIO_DETAIL_TABLE_SELECTORS,
    build_beneficio_resumos,
    DEFAULT_WINDOWS_UA,
    RESULT_POLL_INTERVAL_MS,
    SEARCH_URL_TEMPLATE,
    clean_table_cell,
    find_summary_value,
    get_first_present,
    get_recebimento_summary_from_row,
    human_delay_ms,
    monotonic_deadline,
    normalize_space,
    remaining_timeout_ms,
    slugify_label,
)
from app.models import ConsultaScriptRequest, ConsultaScriptResultado


async def apply_stealth(page: Page) -> None:
    await page.add_init_script(
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


async def wait_delay(page: Page, deadline: float, delay_ms: int | None = None) -> None:
    effective_delay_ms = human_delay_ms() if delay_ms is None else delay_ms
    await page.wait_for_timeout(min(effective_delay_ms, remaining_timeout_ms(deadline, effective_delay_ms)))


async def wait_for_locator_visible(locator: Locator, deadline: float) -> None:
    await locator.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))


async def click_with_stealth_pause(page: Page, locator: Locator, deadline: float) -> None:
    await wait_for_locator_visible(locator, deadline)
    await wait_delay(page, deadline)
    await locator.click(timeout=remaining_timeout_ms(deadline))


async def wait_for_any_visible(page: Page, selectors: list[str], deadline: float) -> Locator:
    while True:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if await locator.is_visible(timeout=min(300, remaining_timeout_ms(deadline, 300))):
                    return locator
            except Error:
                continue
        await page.wait_for_timeout(min(150, remaining_timeout_ms(deadline, 150)))


async def wait_for_checkbox_state(
    page: Page,
    checkbox: Locator,
    checked: bool,
    deadline: float,
) -> None:
    while True:
        try:
            if await checkbox.is_checked() == checked:
                return
        except Error:
            pass
        await page.wait_for_timeout(min(150, remaining_timeout_ms(deadline, 150)))


async def dismiss_cookie_banner(page: Page, deadline: float) -> None:
    for selector in [
        "button:has-text('Aceitar')",
        "button:has-text('Concordo')",
        "button:has-text('Continuar')",
    ]:
        try:
            locator = page.locator(selector).first
            if await locator.count():
                await click_with_stealth_pause(page, locator, deadline)
                return
        except Error:
            continue


async def apply_programa_social_filter(page: Page, deadline: float) -> None:
    refine_button = page.locator("button.header[aria-controls='box-busca-refinada']").first
    refine_box = page.locator("#box-busca-refinada").first
    checkbox = page.locator("#beneficiarioProgramaSocial").first
    checkbox_label = page.locator("label[for='beneficiarioProgramaSocial']").first

    await wait_for_locator_visible(refine_button, deadline)
    if not await refine_box.is_visible(timeout=300):
        await click_with_stealth_pause(page, refine_button, deadline)
        await wait_for_locator_visible(refine_box, deadline)

    await wait_for_locator_visible(checkbox, deadline)
    if not await checkbox.is_checked():
        await wait_delay(page, deadline)
        await checkbox.scroll_into_view_if_needed(timeout=remaining_timeout_ms(deadline))
        try:
            await click_with_stealth_pause(page, checkbox_label, deadline)
        except Error:
            await checkbox.check(force=True, timeout=remaining_timeout_ms(deadline))
        await wait_for_checkbox_state(page, checkbox, True, deadline)

    consult_button = page.locator("#btnConsultarPF").first
    async with page.expect_navigation(
        wait_until="domcontentloaded",
        timeout=remaining_timeout_ms(deadline),
    ):
        await click_with_stealth_pause(page, consult_button, deadline)

    await wait_for_any_visible(
        page,
        [
            "#countResultados",
            "a.link-busca-nome",
            "a[href*='/busca/pessoa-fisica/']",
            "text=Foram encontrados",
        ],
        deadline,
    )


async def wait_for_results(page: Page, deadline: float) -> int:
    while True:
        remaining_ms = remaining_timeout_ms(deadline)
        try:
            count_locator = page.locator("#countResultados").first
            if await count_locator.count():
                count_text = (await count_locator.inner_text()).strip()
                if count_text.isdigit():
                    return int(count_text)
        except Error:
            pass

        try:
            body_text = normalize_space(await page.locator("body").inner_text())
            count_matches = re.findall(r"Foram encontrados\s+(\d+)\s+resultados", body_text)
            if count_matches:
                return int(count_matches[0])

            if re.search(r"Foram encontrados\s+0\s+resultados", body_text, flags=re.IGNORECASE):
                return 0
        except Error:
            pass

        try:
            result_links = page.locator("a.link-busca-nome, a[href*='/busca/pessoa-fisica/']")
            count = await result_links.count()
            if count:
                return count
        except Error:
            pass

        await page.wait_for_timeout(min(RESULT_POLL_INTERVAL_MS, remaining_ms))


async def click_first_result(page: Page, deadline: float) -> str:
    result_link = page.locator("a.link-busca-nome, a[href*='/busca/pessoa-fisica/']").first
    await wait_for_locator_visible(result_link, deadline)
    result_name = normalize_space(await result_link.inner_text())
    await click_with_stealth_pause(page, result_link, deadline)
    await wait_for_any_visible(
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


async def open_recebimentos(page: Page, deadline: float) -> None:
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
                if await page.locator(selector).first.is_visible(
                    timeout=min(250, remaining_timeout_ms(deadline, 250))
                ):
                    return
            except Error:
                continue

        await wait_for_locator_visible(button, deadline)
        try:
            await button.scroll_into_view_if_needed(timeout=remaining_timeout_ms(deadline))
        except Error:
            pass

        try:
            await click_with_stealth_pause(page, button, deadline)
        except Error:
            try:
                await wait_delay(page, deadline)
                await button.click(force=True, timeout=remaining_timeout_ms(deadline))
            except Error:
                if attempt == 2:
                    raise

        try:
            await wait_for_any_visible(page, content_selectors, deadline)
            return
        except TimeoutError:
            if attempt == 2:
                raise


async def capture_screenshot_base64(page: Page) -> str:
    image_bytes = await page.screenshot(full_page=True, type="png")
    return base64.b64encode(image_bytes).decode("utf-8")


async def extract_person_summary(page: Page) -> dict[str, str | None]:
    sections = page.locator("section.dados-tabelados")
    count = await sections.count()
    data: dict[str, str] = {}
    section_texts: list[str] = []

    for index in range(count):
        section = sections.nth(index)
        try:
            section_texts.append(normalize_space(await section.inner_text()))
        except Error:
            pass
        rows = section.locator("li, tr, .row, .col, .dados-tabelados__item")
        row_count = await rows.count()
        for row_index in range(row_count):
            row = rows.nth(row_index)
            texts = [normalize_space(text) for text in await row.locator(":scope *").all_inner_texts()]
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


async def extract_table_rows(table: Locator) -> tuple[list[str], list[dict[str, str]]]:
    headers = [
        normalize_space(item)
        for item in await table.locator("thead th").all_inner_texts()
        if normalize_space(item)
    ]

    rows_locator = table.locator("tbody tr")
    row_count = await rows_locator.count()
    rows: list[dict[str, str]] = []

    for index in range(row_count):
        row = rows_locator.nth(index)
        values = [
            clean_table_cell(item, headers)
            for item in await row.locator("td").all_inner_texts()
        ]
        if not values:
            continue

        if headers and len(headers) == len(values):
            rows.append({header: value for header, value in zip(headers, values, strict=False)})
        else:
            rows.append({f"coluna_{position + 1}": value for position, value in enumerate(values)})

    return headers, rows


def get_table_container(table: Locator) -> Locator:
    return table.locator("xpath=ancestor::div[contains(@class,'wrapper-table')][1]").first


async def get_table_state(table: Locator, container: Locator) -> tuple[str | None, int, str]:
    table_id = await table.get_attribute("id")
    info_text = ""
    row_count = 0
    try:
        if table_id:
            info = container.locator(f"#{table_id}_info").first
            if await info.count():
                info_text = normalize_space(await info.inner_text())
    except Error:
        info_text = ""

    try:
        row_count = await table.locator("tbody tr").count()
    except Error:
        row_count = 0

    first_row_text = ""
    if row_count:
        try:
            first_row_text = normalize_space(await table.locator("tbody tr").first.inner_text())
        except Error:
            first_row_text = ""

    return info_text or None, row_count, first_row_text


async def wait_for_table_state_change(
    page: Page,
    table: Locator,
    container: Locator,
    previous_state: tuple[str | None, int, str],
    deadline: float,
) -> None:
    while True:
        current_state = await get_table_state(table, container)
        if current_state != previous_state:
            return
        await page.wait_for_timeout(min(150, remaining_timeout_ms(deadline, 150)))


async def maybe_click_full_pagination(
    page: Page,
    table: Locator,
    container: Locator,
    deadline: float,
) -> None:
    button = container.locator("#btnPaginacaoCompleta, button:has-text('Paginação completa')").first
    try:
        if await button.count() and await button.is_visible(timeout=min(300, remaining_timeout_ms(deadline, 300))):
            previous_state = await get_table_state(table, container)
            await click_with_stealth_pause(page, button, deadline)
            await wait_for_table_state_change(page, table, container, previous_state, deadline)
    except Error:
        return


async def maybe_expand_table_page_size(
    page: Page,
    table: Locator,
    container: Locator,
    deadline: float,
) -> None:
    table_id = await table.get_attribute("id")
    if not table_id:
        return

    select = container.locator(
        f"select[name='{table_id}_length'], select[aria-controls='{table_id}']"
    ).first
    try:
        if not await select.count():
            return
        option_values = [
            int(value)
            for value in (
                await select.locator("option").evaluate_all(
                    "(options) => options.map((option) => option.value)"
                )
            )
            if str(value).isdigit()
        ]
        if not option_values:
            return
        max_value = str(max(option_values))
        if await select.input_value() != max_value:
            previous_state = await get_table_state(table, container)
            await select.select_option(value=max_value, timeout=remaining_timeout_ms(deadline))
            await wait_for_table_state_change(page, table, container, previous_state, deadline)
    except Error:
        return


async def get_table_page_info(container: Locator, table_id: str | None) -> tuple[int, int] | None:
    selectors = []
    if table_id:
        selectors.append(f"#{table_id}_info")
    selectors.append(".dataTables_info")

    for selector in selectors:
        info = container.locator(selector).first
        try:
            if not await info.count():
                continue
            text = normalize_space(await info.inner_text())
        except Error:
            continue
        match = re.search(r"Página\s+(\d+)\s+de\s+(\d+)", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


async def go_to_next_table_page(
    page: Page,
    table: Locator,
    container: Locator,
    deadline: float,
) -> bool:
    table_id = await table.get_attribute("id")
    next_candidates = []
    if table_id:
        next_candidates.append(f"#{table_id}_next")
    next_candidates.append(".paginate_button.next")

    next_item: Locator | None = None
    for selector in next_candidates:
        candidate = container.locator(selector).first
        try:
            if await candidate.count():
                next_item = candidate
                break
        except Error:
            continue

    if next_item is None:
        return False

    try:
        class_name = ((await next_item.get_attribute("class")) or "").lower()
        if "disabled" in class_name:
            return False
    except Error:
        return False

    next_button = next_item.locator("button, a").first
    try:
        previous_state = await get_table_state(table, container)
        await click_with_stealth_pause(page, next_button, deadline)
        await wait_for_table_state_change(page, table, container, previous_state, deadline)
        return True
    except Error:
        return False


async def extract_all_table_rows(
    page: Page,
    table: Locator,
    deadline: float,
) -> tuple[list[str], list[dict[str, str]]]:
    container = get_table_container(table)
    await maybe_click_full_pagination(page, table, container, deadline)
    await maybe_expand_table_page_size(page, table, container, deadline)

    headers: list[str] = []
    rows: list[dict[str, str]] = []
    seen_rows: set[tuple[tuple[str, str], ...]] = set()
    page_guard = 0

    while True:
        current_headers, current_rows = await extract_table_rows(table)
        if current_headers and not headers:
            headers = current_headers
        for row in current_rows:
            row_key = tuple(sorted(row.items()))
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)
            rows.append(row)

        table_id = await table.get_attribute("id")
        page_info = await get_table_page_info(container, table_id)
        if page_info and page_info[0] >= page_info[1]:
            break
        if page_info is None and not await go_to_next_table_page(page, table, container, deadline):
            break
        if page_info is not None and not await go_to_next_table_page(page, table, container, deadline):
            break

        page_guard += 1
        if page_guard >= 100:
            break

    return headers, rows


async def extract_recebimento_rows(page: Page, deadline: float) -> list[dict[str, str]]:
    accordion = page.locator("#accordion-recebimentos-recursos").first
    await accordion.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    table = accordion.locator("table").first
    await table.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    _, rows = await extract_table_rows(table)
    return rows


async def extract_recebimento_summary(page: Page, deadline: float) -> dict[str, str | None]:
    rows = await extract_recebimento_rows(page, deadline)
    first_row = rows[0] if rows else {}
    return get_recebimento_summary_from_row(first_row)


async def extract_beneficio_links(page: Page, deadline: float) -> list[dict[str, str | None]]:
    accordion = page.locator("#accordion-recebimentos-recursos").first
    await accordion.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    detail_link = await wait_for_any_visible(
        page,
        [
            "#accordion-recebimentos-recursos a#btnDetalharBpc",
            "#accordion-recebimentos-recursos a#btnDetalharBolsaFamilia",
            "#accordion-recebimentos-recursos a.br-button.secondary.mt-3[href*='/beneficios/']",
            "#accordion-recebimentos-recursos a[href*='/beneficios/']",
        ],
        deadline,
    )
    await detail_link.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))

    links = accordion.locator("a.br-button.secondary.mt-3[href*='/beneficios/'], a[href*='/beneficios/']")
    link_count = await links.count()
    beneficios: list[dict[str, str | None]] = []

    for index in range(link_count):
        link = links.nth(index)
        href = await link.get_attribute("href") or ""
        if not href:
            continue
        beneficios.append(
            {
                "id": await link.get_attribute("id"),
                "texto": normalize_space(await link.inner_text()),
                "url": href if href.startswith("http") else f"{BASE_URL}{href}",
            }
        )

    if not beneficios:
        raise RuntimeError("Nenhum link de detalhe de beneficio foi encontrado.")

    return beneficios


async def find_detail_table(page: Page, deadline: float) -> Locator:
    await wait_for_any_visible(page, BENEFICIO_DETAIL_READY_SELECTORS, deadline)

    while True:
        for selector in BENEFICIO_DETAIL_TABLE_SELECTORS:
            locator = page.locator(selector)
            count = await locator.count()
            for index in range(count):
                table = locator.nth(index)
                try:
                    header_count = await table.locator("thead th").count()
                    row_count = await table.locator("tbody tr").count()
                    if header_count or row_count:
                        return table
                except Error:
                    continue

        await page.wait_for_timeout(min(150, remaining_timeout_ms(deadline, 150)))


async def extract_detail_table(page: Page, deadline: float) -> dict[str, object]:
    table = await find_detail_table(page, deadline)
    headers, rows = await extract_all_table_rows(page, table, deadline)

    return {"cabecalhos": headers, "linhas": rows}


async def close_extra_pages(main_page: Page) -> None:
    for extra_page in list(main_page.context.pages):
        if extra_page is main_page:
            continue
        try:
            await extra_page.close()
        except Error:
            continue


async def close_all_pages(page: Page) -> None:
    for opened_page in list(page.context.pages):
        try:
            await opened_page.close()
        except Error:
            continue


async def extract_beneficio_detail(
    page: Page,
    detail_url: str,
    deadline: float,
) -> dict[str, object]:
    detail_page = await page.context.new_page()
    try:
        await apply_stealth(detail_page)
        await detail_page.goto(
            detail_url,
            wait_until="domcontentloaded",
            timeout=remaining_timeout_ms(deadline),
        )
        await wait_for_any_visible(detail_page, BENEFICIO_DETAIL_READY_SELECTORS, deadline)
        if detail_url not in detail_page.url and "/beneficios/" not in detail_page.url:
            raise RuntimeError("A navegacao para o detalhe do beneficio nao ocorreu.")
        tabela_detalhada = await extract_detail_table(detail_page, deadline)
        return {
            "url_detalhe": detail_page.url,
            "tabela_detalhada": tabela_detalhada,
        }
    finally:
        await detail_page.close()


async def run_consulta_script(page: Page, request: ConsultaScriptRequest) -> ConsultaScriptResultado:
    deadline = monotonic_deadline(request.timeout_ms)
    termo = quote_plus(request.identificador)
    search_url = SEARCH_URL_TEMPLATE.format(termo=termo)

    await page.goto(
        search_url,
        wait_until="domcontentloaded",
        timeout=remaining_timeout_ms(deadline),
    )
    await dismiss_cookie_banner(page, deadline)
    await apply_programa_social_filter(page, deadline)

    resultados = await wait_for_results(page, deadline)
    if resultados == 0:
        return ConsultaScriptResultado(
            status="sem_resultados",
            nome_busca=request.identificador,
            url_busca=search_url,
            evidencia_base64=await capture_screenshot_base64(page),
            mensagem=(
                f'O identificador pesquisado "{request.identificador}" '
                "não possui nenhum benefício registrado."
            ),
            detalhe_portal=(
                f'Foram encontrados 0 resultados para o termo "{request.identificador}".'
            ),
        )

    nome_resultado = await click_first_result(page, deadline)
    person_summary = await extract_person_summary(page)
    await open_recebimentos(page, deadline)
    recebimento_rows = await extract_recebimento_rows(page, deadline)
    recebimento_summary = get_recebimento_summary_from_row(
        recebimento_rows[0] if recebimento_rows else {}
    )
    beneficio_links = await extract_beneficio_links(page, deadline)
    evidencia_base64 = await capture_screenshot_base64(page)
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
                **(await extract_beneficio_detail(page, beneficio["url_detalhe"], deadline)),
            }
        )
        await close_extra_pages(page)

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
