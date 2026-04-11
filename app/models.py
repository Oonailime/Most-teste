from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ConsultaScriptRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "identificador": "NOME EXEMPLO",
                }
            ]
        },
    )

    identificador: str = Field(
        ...,
        min_length=3,
        description="Nome, CPF ou NIS utilizado na busca.",
        examples=["NOME EXEMPLO"],
    )
    timeout_ms: int = Field(
        default=240000,
        ge=10000,
        le=600000,
        description="Tempo máximo da automação em milissegundos. Padrão: 240000.",
    )
    headless: bool = Field(
        default=True,
        description="Executa o navegador em modo headless. Padrão: true.",
    )
    browser_channel: Literal["chromium", "msedge"] = Field(
        default="chromium",
        description=(
            "Canal do navegador. Padrão: `chromium`. "
            "Use `msedge` apenas se o Microsoft Edge estiver instalado."
        ),
    )

    @field_validator("identificador")
    @classmethod
    def strip_identificador(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("identificador não pode ser vazio")
        return cleaned

    @model_validator(mode="before")
    @classmethod
    def reject_nome_alias(cls, data: Any) -> Any:
        if not isinstance(data, dict) or "nome" not in data:
            return data

        nome = data.get("nome")
        if isinstance(nome, str) and not nome.strip():
            raise ValueError("nome não pode ser vazio; use `identificador`")

        raise ValueError("o campo `nome` não é mais aceito; use `identificador`")


class ConsultaScriptTable(BaseModel):
    cabecalhos: list[str] = Field(default_factory=list)
    linhas: list[dict[str, str]] = Field(default_factory=list)


class ConsultaScriptBeneficioResultado(BaseModel):
    nome: str | None = None
    nis: str | None = None
    valor_recebido: str | None = None
    tipo_beneficio: str | None = None
    url_detalhe: str
    tabela_detalhada: ConsultaScriptTable


class ConsultaScriptResultado(BaseModel):
    status: str
    nome: str | None = None
    cpf: str | None = None
    localidade: str | None = None
    nome_busca: str
    resultado_clicado: str | None = None
    url_busca: str
    beneficios: list[ConsultaScriptBeneficioResultado] | None = None
    evidencia_base64: str | None = None
