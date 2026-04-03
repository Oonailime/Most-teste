# Desafio Full Stack Developer - Python (RPA e Hiperautomação)

Implementação da **Parte 1** do desafio com:

- robô em **Python + Playwright** para consulta no Portal da Transparência;
- **API FastAPI** para disparar o robô e expor documentação Swagger/OpenAPI;
- captura de screenshot do fluxo em base64;
- coleta dos dados principais do beneficiário e da tabela detalhada do benefício.

Também incluí um desenho objetivo da **Parte 2 (bônus)** em [docs/bonus-workflow.md](/mnt/c/Most/Most-teste/docs/bonus-workflow.md).

## Decisões técnicas

- **Playwright** foi escolhido por ser robusto em navegação headless, melhor com páginas dinâmicas e adequado para execuções simultâneas com contexts isolados.
- **FastAPI** entrega API simples, validação de payload com Pydantic e Swagger automático em `/docs`.
- A automação foi escrita com **seletores defensivos e fallbacks**, porque o Portal da Transparência pode variar discretamente na estrutura HTML.
- O fluxo usa **esperas por estado visível e navegação**, com um jitter curto entre ações em vez de sleeps longos fixos.
- Cada requisição cria seu próprio browser/context no fluxo ativo.
- A API limita a concorrência local a **2 consultas simultâneas por processo** para evitar abrir browsers sem controle.

## Estrutura

```text
app/
  main.py        # API FastAPI
  models.py      # contratos de entrada e saída
  script_consulta.py  # automação Playwright usada pela API
docs/
  bonus-workflow.md
Dockerfile
pyproject.toml
```

## Requisitos

- Python 3.11+
- Chromium do Playwright

## Instalação

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install .
python3 -m playwright install chromium
```

## Execução local

```bash
uvicorn app.main:app --reload
```

Endpoints:

- `GET /health`
- `POST /consulta-script`
- `GET /docs`

## Exemplo de requisição

```bash
curl -X POST http://127.0.0.1:8000/consulta-script \
  -H "Content-Type: application/json" \
  -d '{
    "identificador": "A Anne Christine Silva Ribeiro",
  }'
```

## Exemplo de resposta

```json
{
  "status": "sucesso",
  "nome": "A ANNE CHRISTINE SILVA RIBEIRO",
  "nis": "123.45678.90-1",
  "cpf": "***.734.995-**",
  "localidade": "PROPRIÁ - SE",
  "valor_recebido": "R$ 3.900,00",
  "nome_busca": "A Anne Christine Silva Ribeiro",
  "resultado_clicado": "A ANNE CHRISTINE SILVA RIBEIRO",
  "url_busca": "https://portaldatransparencia.gov.br/pessoa-fisica/busca/lista?termo=A+Anne+Christine+Silva+Ribeiro&pagina=1&tamanhoPagina=10",
  "url_detalhe": "https://portaldatransparencia.gov.br/beneficios/auxilio-emergencial/187235083?ordenarPor=numeroParcela&direcao=desc",
  "tabela_detalhada": {
    "cabecalhos": ["coluna_1", "coluna_2", "coluna_3", "coluna_4"],
    "linhas": [
      {
        "coluna_1": "valor_1",
        "coluna_2": "valor_2",
        "coluna_3": "valor_3",
        "coluna_4": "valor_4"
      }
    ]
  },
  "evidencia_base64": "<imagem_png_em_base64>"
}
```

O campo aceito pela API é `identificador` e pode receber nome, CPF ou NIS. Por compatibilidade, `nome` continua sendo aceito como alias de entrada.

O navegador padrão é `chromium`, que também é o browser instalado na imagem Docker. Se quiser usar Microsoft Edge em ambiente local, envie `browser_channel: "msedge"`.

## Regras implementadas para os cenários do desafio

- busca por **nome, CPF ou NIS** via `identificador`;
- na tela inicial, o fluxo abre **Refine a Busca**, marca **Beneficiário de Programa Social** e consulta novamente para forçar o que o filtro seja aplicado;
- caso a busca tenha 0 retornos, o print de evidência base64 é feito nessa tela.
- o screenshot retornado em `evidencia_base64` é capturado **após abrir `accordion-recebimentos-recursos`;
- os campos principais retornados no topo do JSON são:
  - `nome`
  - `nis`
  - `cpf`
  - `localidade`
  - `valor_recebido`
- em caso de busca sem resultados, retorna erro com a mensagem:
  - `Foram encontrados 0 resultados para o termo "...".`
- em caso de timeout, retorna:
  - `Não foi possível retornar os dados no tempo de resposta solicitado`

## Observações importantes

- O fluxo usa a busca direta da pessoa física no Portal da Transparência.
- A seleção do primeiro resultado compatível é intencional, alinhada ao critério do desafio.
- O timeout informado na requisição agora é propagado para a navegação e para as esperas internas do Playwright.
- O nome retornado em `nome` é o próprio texto clicado em `link-busca-nome`.
- `cpf` e `localidade` são extraídos da área `dados-tabelados` da tela intermediária.
- `nis` e `valor_recebido` são extraídos da tabela exibida após abrir `accordion-recebimentos-recursos`.
- `tabela_detalhada` é extraída apenas após o clique em `Detalhar`.

## Execução com Docker

```bash
docker build -t most-transparencia-bot .
docker run --rm -p 8000:8000 most-transparencia-bot
```

## Benchmark de latência

Com a API já no ar, você pode medir o tempo total de lotes paralelos com 6 e 12 requisições:

```bash
chmod +x scripts/benchmark-latency.sh
./scripts/benchmark-latency.sh
```

Para salvar a saída:

```bash
OUTPUT_FILE=benchmark-latency.txt ./scripts/benchmark-latency.sh
```

## Melhorias recomendadas

- testes automatizados com mocks de HTML para cenários previsíveis;
- observabilidade com correlation id por consulta;
- fila assíncrona ou worker dedicado para escalar além do limite por processo;
- implementação prática da Parte 2 em Activepieces com Google Drive e Sheets.
