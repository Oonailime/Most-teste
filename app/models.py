from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class ConsultaScriptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identificador: str = Field(
        ...,
        min_length=3,
        description="Nome, CPF ou NIS utilizado na busca.",
        examples=["Clarice Amanda Barbosa Paim"],
        validation_alias=AliasChoices("identificador", "nome"),
    )
    timeout_ms: int = Field(
        default=90000,
        ge=10000,
        le=180000,
        description="Tempo máximo da automação em milissegundos.",
    )
    headless: bool = Field(default=True, description="Executa o navegador em modo headless.")
    browser_channel: Literal["chromium", "msedge"] = Field(
        default="chromium",
        description="Canal do navegador. Use `msedge` apenas se o Microsoft Edge estiver instalado.",
    )

    @field_validator("identificador")
    @classmethod
    def strip_identificador(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("identificador não pode ser vazio")
        return cleaned


class ConsultaScriptTable(BaseModel):
    cabecalhos: list[str] = Field(default_factory=list)
    linhas: list[dict[str, str]] = Field(default_factory=list)


class ConsultaScriptResultado(BaseModel):
    status: str
    nome: str | None = None
    nis: str | None = None
    cpf: str | None = None
    localidade: str | None = None
    valor_recebido: str | None = None
    nome_busca: str
    resultado_clicado: str | None = None
    url_busca: str
    url_detalhe: str | None = None
    mensagem: str | None = None
    detalhe_portal: str | None = None
    tabela_detalhada: ConsultaScriptTable | None = None
    evidencia_base64: str | None = None
