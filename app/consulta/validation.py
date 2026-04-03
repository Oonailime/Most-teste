from __future__ import annotations

from app.consulta.common import ALLOW_HEADFUL_BROWSER, BROWSER_CHANNEL
from app.models import ConsultaScriptRequest


def validate_browser_mode(request: ConsultaScriptRequest) -> None:
    if request.headless or ALLOW_HEADFUL_BROWSER:
        return
    raise ValueError(
        "Modo visivel (headless=false) esta desabilitado neste processo. "
        "Defina ALLOW_HEADFUL_BROWSER=true para permitir esse modo."
    )


def validate_browser_channel(request: ConsultaScriptRequest) -> None:
    if request.browser_channel == BROWSER_CHANNEL:
        return
    raise ValueError(
        f"Este processo foi iniciado com browser_channel={BROWSER_CHANNEL!r}. "
        f"Recebido {request.browser_channel!r}. Reinicie a API com BROWSER_CHANNEL="
        f"{request.browser_channel!r} ou envie o canal configurado."
    )
