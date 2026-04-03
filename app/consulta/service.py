from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from playwright.async_api import Browser, BrowserContext, Page, Playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from app.consulta.async_flow import apply_stealth, run_consulta_script
from app.consulta.common import (
    BROWSER_CHANNEL,
    DEFAULT_WINDOWS_UA,
    MAX_CONCURRENT_CONSULTAS,
    USE_LOCAL_SYNC_FALLBACK,
)
from app.consulta.sync_flow import run_consulta_script_sync
from app.consulta.validation import validate_browser_channel, validate_browser_mode
from app.models import ConsultaScriptRequest, ConsultaScriptResultado


@dataclass(slots=True)
class BrowserLease:
    context: BrowserContext
    page: Page
    release: Callable[[], Awaitable[None]]


@dataclass(slots=True)
class BrowserRuntime:
    browser: Browser
    pool: "BrowserPagePool"


class BrowserPagePool:
    def __init__(self, browser: Browser, max_slots: int) -> None:
        self._browser = browser
        self._slots: asyncio.Queue[None] = asyncio.Queue(maxsize=max_slots)
        for _ in range(max_slots):
            self._slots.put_nowait(None)

    async def acquire(self, timeout_ms: int) -> BrowserLease:
        timeout_s = timeout_ms / 1000
        try:
            await asyncio.wait_for(self._slots.get(), timeout=timeout_s)
        except TimeoutError as exc:
            raise TimeoutError("Nao foi possivel alocar slot para a consulta no tempo solicitado") from exc

        context = await self._browser.new_context(
            viewport={"width": 1600, "height": 2200},
            locale="pt-BR",
            user_agent=DEFAULT_WINDOWS_UA,
        )
        page = await context.new_page()

        try:
            await apply_stealth(page)
            page.set_default_timeout(timeout_ms)
        except Exception:
            await context.close()
            self._slots.put_nowait(None)
            raise

        async def release() -> None:
            try:
                await context.close()
            finally:
                self._slots.put_nowait(None)

        return BrowserLease(context=context, page=page, release=release)


class ScriptConsultaService:
    def __init__(self, max_concurrent_consultas: int = MAX_CONCURRENT_CONSULTAS) -> None:
        self._max_concurrent_consultas = max_concurrent_consultas
        self._semaphore = asyncio.Semaphore(max_concurrent_consultas)
        self._playwright: Playwright | None = None
        self._runtimes: dict[bool, BrowserRuntime] = {}
        self._startup_lock = asyncio.Lock()

    async def _ensure_playwright(self) -> Playwright:
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        return self._playwright

    async def _ensure_runtime(self, *, headless: bool) -> BrowserRuntime:
        async with self._startup_lock:
            runtime = self._runtimes.get(headless)
            if runtime is not None:
                return runtime

            playwright = await self._ensure_playwright()
            browser = await playwright.chromium.launch(
                channel=BROWSER_CHANNEL,
                headless=headless,
                args=[
                    "--start-maximized",
                    "--disable-notifications",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            runtime = BrowserRuntime(
                browser=browser,
                pool=BrowserPagePool(browser, self._max_concurrent_consultas),
            )
            self._runtimes[headless] = runtime
            return runtime

    async def startup(self) -> None:
        if USE_LOCAL_SYNC_FALLBACK:
            return
        await self._ensure_runtime(headless=True)

    async def shutdown(self) -> None:
        if USE_LOCAL_SYNC_FALLBACK:
            return

        async with self._startup_lock:
            runtimes = list(self._runtimes.values())
            self._runtimes.clear()

            for runtime in runtimes:
                await runtime.browser.close()

            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None

    async def run(self, request: ConsultaScriptRequest) -> ConsultaScriptResultado:
        validate_browser_mode(request)
        validate_browser_channel(request)

        if USE_LOCAL_SYNC_FALLBACK:
            async with self._semaphore:
                return await asyncio.to_thread(run_consulta_script_sync, request)

        runtime = await self._ensure_runtime(headless=request.headless)
        lease = await runtime.pool.acquire(request.timeout_ms)
        try:
            return await run_consulta_script(lease.page, request)
        except PlaywrightTimeoutError as exc:
            raise TimeoutError("Não foi possível retornar os dados no tempo de resposta solicitado") from exc
        finally:
            await lease.release()
