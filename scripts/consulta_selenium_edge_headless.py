from __future__ import annotations

import re
import sys
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service
from selenium.webdriver.support.ui import WebDriverWait

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

import consulta_selenium_edge as selenium_edge


def apply_stealth(driver: webdriver.Edge) -> None:
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
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
        },
    )


def build_headless_driver(headless: bool = False) -> webdriver.Edge:
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(f"--user-agent={DEFAULT_WINDOWS_UA}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1600,2200")
    service = Service()
    driver = webdriver.Edge(service=service, options=options)
    driver.set_page_load_timeout(selenium_edge.DEFAULT_TIMEOUT)
    apply_stealth(driver)
    return driver


def wait_for_results_headless(driver: webdriver.Edge) -> int:
    def condition(current_driver: webdriver.Edge) -> str | bool:
        try:
            count_text = current_driver.find_element(By.ID, "countResultados").text.strip()
            if count_text.isdigit():
                return count_text
        except Exception:
            pass

        try:
            body_text = selenium_edge.normalize_space(
                current_driver.find_element(By.TAG_NAME, "body").text
            )
        except Exception:
            return False

        count_matches = re.findall(r"Foram encontrados\s+(\d+)\s+resultados", body_text)
        if count_matches:
            return count_matches[0]

        if re.search(r"Foram encontrados\s+0\s+resultados", body_text, flags=re.IGNORECASE):
            return "0"

        try:
            result_links = current_driver.find_elements(
                By.CSS_SELECTOR,
                "a.link-busca-nome, a[href*='/busca/pessoa-fisica/']",
            )
            visible_links = [link for link in result_links if link.is_displayed()]
            if visible_links:
                return str(len(visible_links))
        except Exception:
            pass

        return False

    count = WebDriverWait(driver, selenium_edge.DEFAULT_TIMEOUT).until(condition)
    selenium_edge.wait_delay(selenium_edge.RESULT_WAIT_SECONDS)
    return int(count)


if __name__ == "__main__":
    selenium_edge.build_driver = build_headless_driver
    selenium_edge.wait_for_results = wait_for_results_headless
    raise SystemExit(selenium_edge.main(headless=True))
