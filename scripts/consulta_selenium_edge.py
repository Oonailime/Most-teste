from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


BASE_URL = "https://portaldatransparencia.gov.br"
SEARCH_URL_TEMPLATE = (
    f"{BASE_URL}/pessoa-fisica/busca/lista?termo={{termo}}&pagina=1&tamanhoPagina=10"
)
ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "resultados_portal_transparencia"
ACTION_DELAY_SECONDS = 1.0
RESULT_WAIT_SECONDS = 5.0
DEFAULT_TIMEOUT = 60


def normalize_space(value: str) -> str:
    return " ".join(value.split())


def slugify_filename(value: str) -> str:
    sanitized = re.sub(r'[\\/:*?"<>|]+', "", normalize_space(value))
    sanitized = sanitized.replace(" ", "_")
    return sanitized or "resultado"


def wait_delay(seconds: float = ACTION_DELAY_SECONDS) -> None:
    time.sleep(seconds)


def build_driver(headless: bool = False) -> webdriver.Edge:
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1600,2200")
    service = Service()
    driver = webdriver.Edge(service=service, options=options)
    driver.set_page_load_timeout(DEFAULT_TIMEOUT)
    return driver


def dismiss_cookie_banner(driver: webdriver.Edge) -> None:
    selectors = [
        (By.XPATH, "//button[contains(., 'Aceitar')]"),
        (By.XPATH, "//button[contains(., 'Concordo')]"),
        (By.XPATH, "//button[contains(., 'Continuar')]"),
    ]
    for by, selector in selectors:
        try:
            button = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((by, selector)))
            wait_delay()
            button.click()
            wait_delay()
            return
        except TimeoutException:
            continue


def wait_for_results(driver: webdriver.Edge) -> int:
    def condition(current_driver: webdriver.Edge) -> str | bool:
        try:
            count_text = current_driver.find_element(By.ID, "countResultados").text.strip()
            if count_text.isdigit():
                return count_text
        except Exception:
            pass

        try:
            body_text = normalize_space(current_driver.find_element(By.TAG_NAME, "body").text)
        except Exception:
            return False

        count_matches = re.findall(r"Foram encontrados\s+(\d+)\s+resultados", body_text)
        if count_matches:
            return count_matches[0]

        return False

    count = WebDriverWait(driver, DEFAULT_TIMEOUT).until(condition)
    wait_delay(RESULT_WAIT_SECONDS)
    return int(count)


def click_first_result(driver: webdriver.Edge) -> str:
    result_link = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "a.link-busca-nome"))
    )
    result_name = normalize_space(result_link.text)
    wait_delay()
    result_link.click()
    wait_delay()
    WebDriverWait(driver, DEFAULT_TIMEOUT).until(
        lambda current_driver: "/busca/pessoa-fisica/" in current_driver.current_url
    )
    return result_name


def open_recebimentos(driver: webdriver.Edge) -> None:
    recebimentos_button = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "button.header[aria-controls='accordion-recebimentos-recursos']")
        )
    )
    wait_delay()
    recebimentos_button.click()
    wait_delay()


def save_screenshot(driver: webdriver.Edge, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    driver.save_screenshot(str(path))


def click_detail(driver: webdriver.Edge) -> str:
    detail_link = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
        EC.element_to_be_clickable(
            (
                By.CSS_SELECTOR,
                "a#btnDetalharBpc, a.br-button.secondary.mt-3[href*='/beneficios/']",
            )
        )
    )
    href = detail_link.get_attribute("href") or ""
    wait_delay()
    detail_link.click()
    wait_delay()
    if href:
        WebDriverWait(driver, DEFAULT_TIMEOUT).until(
            lambda current_driver: current_driver.current_url.startswith(href)
            or "/beneficios/" in current_driver.current_url
        )
    return driver.current_url


def extract_section_data(driver: webdriver.Edge) -> dict[str, object]:
    section = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "section.dados-detalhados"))
    )
    raw_text = normalize_space(section.text)
    lines = [line.strip() for line in section.text.splitlines() if line.strip()]

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
        "url": driver.current_url,
        "texto_bruto": raw_text,
        "campos": structured_rows,
    }


def extract_detail_table(driver: webdriver.Edge) -> dict[str, object]:
    table = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#tabelaDetalheDisponibilizado"))
    )

    header_elements = table.find_elements(By.CSS_SELECTOR, "thead th")
    headers = [normalize_space(item.text) for item in header_elements if normalize_space(item.text)]

    body_rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
    rows: list[dict[str, str]] = []

    for row in body_rows:
        cell_elements = row.find_elements(By.CSS_SELECTOR, "td")
        values = [normalize_space(cell.text) for cell in cell_elements]
        if not values:
            continue

        if headers and len(headers) == len(values):
            rows.append({header: value for header, value in zip(headers, values, strict=False)})
        else:
            rows.append({f"coluna_{index + 1}": value for index, value in enumerate(values)})

    return {
        "cabecalhos": headers,
        "linhas": rows,
    }


def write_data_file(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(headless: bool = False) -> int:
    nome = input("Escreva o nome: ").strip()
    if not nome:
        raise SystemExit("Nome vazio.")

    driver = build_driver(headless=headless)
    try:
        termo = quote_plus(nome)
        search_url = SEARCH_URL_TEMPLATE.format(termo=termo)
        search_slug = slugify_filename(nome)
        search_output_dir = OUTPUT_DIR
        search_screenshot_path = search_output_dir / f"{search_slug}_busca.png"
        print(f"Abrindo busca: {search_url}")
        driver.get(search_url)
        dismiss_cookie_banner(driver)

        resultados = wait_for_results(driver)
        save_screenshot(driver, search_screenshot_path)
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
                "screenshot_busca": str(search_screenshot_path.relative_to(ROOT_DIR)),
            }
            write_data_file(data_path, payload)
            print(mensagem)
            print(f"Arquivo salvo em: {data_path}")
            return 0

        nome_resultado = click_first_result(driver)
        print(f"Primeiro resultado clicado: {nome_resultado}")

        person_dir = OUTPUT_DIR / search_slug
        detail_screenshot_path = person_dir / "detalhe.png"
        data_path = person_dir / "dados.json"

        open_recebimentos(driver)
        save_screenshot(driver, detail_screenshot_path)
        print(f"Screenshot do detalhe salva em: {detail_screenshot_path}")

        url_detalhe = click_detail(driver)
        print(f"Página de detalhe aberta: {url_detalhe}")

        dados = extract_section_data(driver)
        tabela_detalhada = extract_detail_table(driver)
        payload = {
            "status": "sucesso",
            "nome_busca": nome,
            "resultado_clicado": nome_resultado,
            "url_busca": search_url,
            "url_detalhe": url_detalhe,
            "screenshot_busca": str(search_screenshot_path.relative_to(ROOT_DIR)),
            "screenshot_detalhe": str(detail_screenshot_path.relative_to(ROOT_DIR)),
            "dados_detalhados": dados,
            "tabela_detalhada": tabela_detalhada,
        }
        write_data_file(data_path, payload)
        print(f"Dados salvos em: {data_path}")
        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    raise SystemExit(main())
