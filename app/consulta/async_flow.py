from __future__ import annotations

import base64
import re
from urllib.parse import quote_plus

from playwright.async_api import Error, Locator, Page

from app.consulta.common import (
    BASE_URL,
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
    async with page.expect_navigation(
        wait_until="domcontentloaded",
        timeout=remaining_timeout_ms(deadline),
    ):
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
    await click_with_stealth_pause(page, button, deadline)
    await wait_for_any_visible(
        page,
        [
            "#accordion-recebimentos-recursos table",
            "#accordion-recebimentos-recursos a#btnDetalharBpc",
            "#accordion-recebimentos-recursos a[href*='/beneficios/']",
        ],
        deadline,
    )


async def capture_screenshot_base64(page: Page) -> str:
    image_bytes = await page.screenshot(full_page=True, type="png")
    return base64.b64encode(image_bytes).decode("utf-8")


async def click_detail(page: Page, deadline: float) -> str:
    detail_link = await wait_for_any_visible(
        page,
        [
            "a#btnDetalharBpc",
            "a.br-button.secondary.mt-3[href*='/beneficios/']",
        ],
        deadline,
    )
    href = await detail_link.get_attribute("href") or ""
    expected_url_part = href if href.startswith("http") else f"{BASE_URL}{href}"
    async with page.expect_navigation(
        wait_until="domcontentloaded",
        timeout=remaining_timeout_ms(deadline),
    ):
        await click_with_stealth_pause(page, detail_link, deadline)
    await wait_for_any_visible(
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


async def extract_recebimento_summary(page: Page, deadline: float) -> dict[str, str | None]:
    accordion = page.locator("#accordion-recebimentos-recursos").first
    await accordion.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    table = accordion.locator("table").first
    await table.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    _, rows = await extract_table_rows(table)
    first_row = rows[0] if rows else {}

    return {
        "nis": get_first_present(first_row, ["NIS"]),
        "valor_recebido": get_first_present(
            first_row,
            ["Valor Recebido", "Valor", "Valor do benefício", "Valor do beneficio"],
        ),
    }


async def extract_detail_table(page: Page, deadline: float) -> dict[str, object]:
    table = page.locator("#tabelaDetalheDisponibilizado").first
    await table.wait_for(state="visible", timeout=remaining_timeout_ms(deadline))
    headers, rows = await extract_table_rows(table)

    return {"cabecalhos": headers, "linhas": rows}


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
    recebimento_summary = await extract_recebimento_summary(page, deadline)
    evidencia_base64 = await capture_screenshot_base64(page)
    url_detalhe = await click_detail(page, deadline)
    tabela_detalhada = await extract_detail_table(page, deadline)

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
