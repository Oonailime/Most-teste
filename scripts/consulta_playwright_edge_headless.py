from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import Error, Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_WINDOWS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0"
)

for path in (str(ROOT), str(SCRIPTS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import consulta_playwright_edge as playwright_edge


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


def wait_for_results_headless(page: Page) -> int:
    for _ in range(playwright_edge.DEFAULT_TIMEOUT_MS // 1000):
        try:
            count_locator = page.locator("#countResultados").first
            if count_locator.count():
                count_text = count_locator.inner_text().strip()
                if count_text.isdigit():
                    page.wait_for_timeout(playwright_edge.RESULT_WAIT_MS)
                    return int(count_text)
        except Error:
            pass

        try:
            body_text = playwright_edge.normalize_space(page.locator("body").inner_text())
            count_matches = re.findall(r"Foram encontrados\s+(\d+)\s+resultados", body_text)
            if count_matches:
                page.wait_for_timeout(playwright_edge.RESULT_WAIT_MS)
                return int(count_matches[0])

            if re.search(r"Foram encontrados\s+0\s+resultados", body_text, flags=re.IGNORECASE):
                page.wait_for_timeout(playwright_edge.RESULT_WAIT_MS)
                return 0
        except Error:
            pass

        try:
            result_links = page.locator("a.link-busca-nome, a[href*='/busca/pessoa-fisica/']")
            if result_links.count():
                page.wait_for_timeout(playwright_edge.RESULT_WAIT_MS)
                return result_links.count()
        except Error:
            pass

        page.wait_for_timeout(playwright_edge.RESULT_POLL_INTERVAL_MS)

    raise TimeoutError("Tempo excedido aguardando resultados da busca em modo headless.")


def main() -> int:
    nome = input("Escreva o nome: ").strip()
    if not nome:
        raise SystemExit("Nome vazio.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel="msedge",
            headless=True,
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
        page.set_default_timeout(playwright_edge.DEFAULT_TIMEOUT_MS)

        try:
            termo = playwright_edge.quote_plus(nome)
            search_url = playwright_edge.SEARCH_URL_TEMPLATE.format(termo=termo)
            search_slug = playwright_edge.slugify_filename(nome)
            search_output_dir = playwright_edge.OUTPUT_DIR
            search_screenshot_path = search_output_dir / f"{search_slug}_busca.png"

            print(f"Abrindo busca: {search_url}")
            page.goto(search_url, wait_until="domcontentloaded")
            playwright_edge.dismiss_cookie_banner(page)

            resultados = wait_for_results_headless(page)
            playwright_edge.save_screenshot(page, search_screenshot_path)
            print(f"Resultados encontrados: {resultados}")
            print(f"Screenshot da busca salva em: {search_screenshot_path}")

            if resultados == 0:
                mensagem = f'O nome pesquisado "{nome}" não possui nenhum benefício registrado.'
                data_path = search_output_dir / f"{search_slug}_dados.json"
                payload = {
                    "status": "sem_resultados",
                    "nome_busca": nome,
                    "url_busca": search_url,
                    "mensagem": mensagem,
                    "detalhe_portal": f'Foram encontrados 0 resultados para o termo "{nome}".',
                    "screenshot_busca": str(search_screenshot_path.relative_to(playwright_edge.ROOT_DIR)),
                }
                playwright_edge.write_data_file(data_path, payload)
                print(mensagem)
                print(f"Arquivo salvo em: {data_path}")
                return 0

            nome_resultado = playwright_edge.click_first_result(page)
            print(f"Primeiro resultado clicado: {nome_resultado}")

            person_dir = playwright_edge.OUTPUT_DIR / search_slug
            detail_screenshot_path = person_dir / "detalhe.png"
            data_path = person_dir / "dados.json"

            playwright_edge.open_recebimentos(page)
            playwright_edge.save_screenshot(page, detail_screenshot_path)
            print(f"Screenshot do detalhe salva em: {detail_screenshot_path}")

            url_detalhe = playwright_edge.click_detail(page)
            print(f"Página de detalhe aberta: {url_detalhe}")

            dados = playwright_edge.extract_section_data(page)
            tabela_detalhada = playwright_edge.extract_detail_table(page)
            payload = {
                "status": "sucesso",
                "nome_busca": nome,
                "resultado_clicado": nome_resultado,
                "url_busca": search_url,
                "url_detalhe": url_detalhe,
                "screenshot_busca": str(search_screenshot_path.relative_to(playwright_edge.ROOT_DIR)),
                "screenshot_detalhe": str(detail_screenshot_path.relative_to(playwright_edge.ROOT_DIR)),
                "dados_detalhados": dados,
                "tabela_detalhada": tabela_detalhada,
            }
            playwright_edge.write_data_file(data_path, payload)
            print(f"Dados salvos em: {data_path}")
            return 0
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
