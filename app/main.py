from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

try:
    from app.models import ConsultaScriptRequest, ConsultaScriptResultado
    from app.script_consulta import ScriptConsultaService
except ModuleNotFoundError:
    from models import ConsultaScriptRequest, ConsultaScriptResultado
    from script_consulta import ScriptConsultaService

TIMEOUT_MESSAGE = "Não foi possível retornar os dados no tempo de resposta solicitado"

app = FastAPI(
    title="Most Transparencia Bot",
    version="0.1.0",
    description=(
        "API para executar o robô Playwright no Portal da Transparência e retornar "
        "os dados estruturados da consulta."
    ),
)

script_consulta_service = ScriptConsultaService()
logger = logging.getLogger(__name__)


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/consulta-script",
    response_model=ConsultaScriptResultado,
    response_model_exclude_none=True,
    summary="Executa a consulta usando o fluxo do script local",
)
async def consultar_pessoa_script(request: ConsultaScriptRequest) -> ConsultaScriptResultado:
    try:
        return await script_consulta_service.run(request)
    except (TimeoutError, PlaywrightTimeoutError) as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "status": "erro",
                "mensagem": str(exc).strip() or TIMEOUT_MESSAGE,
            },
        ) from exc
    except Exception as exc:
        logger.exception(
            "Falha no fluxo do script para identificador=%s", request.identificador
        )
        message = str(exc).strip() or "Falha inesperada na automação"
        if "Executable doesn't exist" in message or "browserType.launch" in message:
            message = (
                "Playwright/Chromium não instalado. Execute: "
                "python -m playwright install chromium"
            )
        raise HTTPException(
            status_code=500,
            detail={
                "status": "erro",
                "mensagem": TIMEOUT_MESSAGE if "Timeout" in str(exc) else message,
            },
        ) from exc
