# Desafio Full Stack Developer - Python (RPA e Hiperautomação)

Implementação da **Parte 1** do desafio com:

- robô em **Python + Playwright** para consulta no Portal da Transparência;
- **API FastAPI** para disparar o robô e expor documentação Swagger/OpenAPI;
- captura de screenshot do fluxo em base64;
- coleta dos dados principais do beneficiário e da tabela detalhada do benefício.

Também incluí um desenho objetivo da **Parte 2 (bônus)** em [docs/bonus-workflow.md](/mnt/c/Most/Most-teste/docs/bonus-workflow.md).

Guia de deploy na Oracle Cloud em [docs/deploy-oracle.md](/mnt/c/Most/Most-teste/docs/deploy-oracle.md).

## Decisões técnicas

- **Playwright** foi escolhido por ser robusto em navegação headless, melhor com páginas dinâmicas e adequado para execuções simultâneas com contexts isolados.
- **FastAPI** entrega API simples, validação de payload com Pydantic e Swagger automático em `/docs`.
- A automação foi escrita com **seletores defensivos e fallbacks**, porque o Portal da Transparência pode variar discretamente na estrutura HTML.
- O fluxo usa **esperas por estado visível e navegação**, com um jitter curto entre ações em vez de sleeps longos fixos.
- O processo reutiliza um browser Playwright por modo (`headless=true` e, localmente, `headless=false`) e isola cada requisição em seu próprio `context/page`.
- No Windows com Python 3.14, o app usa um fallback local com Playwright síncrono por requisição para contornar a incompatibilidade do runtime assíncrono.
- A API limita a concorrência local a **6 consultas simultâneas por processo** por pool de browser. O valor pode ser alterado via `MAX_CONCURRENT_CONSULTAS`.

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

- Python 3.11, 3.12 ou 3.13
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
uvicorn app.main:app --reload --port 8001
```

Com configuração explícita:

```bash
MAX_CONCURRENT_CONSULTAS=6 BROWSER_CHANNEL=chromium uvicorn app.main:app --reload --port 8001
```

Endpoints:

- `GET /health`
- `POST /consulta-script`
- `GET /docs`

## Exemplo de requisição

```bash
curl -X POST http://127.0.0.1:8001/consulta-script \
  -H "Content-Type: application/json" \
  -d '{
    "identificador": "A Anne Christine Silva Ribeiro"
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

O campo aceito pela API é `identificador` e pode receber nome, CPF ou NIS. O alias `nome` não é mais aceito.

Se a requisição enviar apenas `identificador`, o app usa os fallbacks:

- `timeout_ms`: `60000`
- `headless`: `true`
- `browser_channel`: `chromium`

Se qualquer um desses campos for enviado na requisição, o valor informado prevalece sobre o fallback.

O navegador padrão é `chromium`, que também é o browser instalado na imagem Docker. Como o browser agora e compartilhado por processo, o canal efetivo vem da variavel `BROWSER_CHANNEL` no startup. A requisição deve usar o mesmo valor configurado no processo.

`headless=false` fica bloqueado por padrao. Para permitir navegador visivel, inicie o processo com `ALLOW_HEADFUL_BROWSER=true`.

Para depurar localmente com navegador visivel:

```bash
MAX_CONCURRENT_CONSULTAS=2 BROWSER_CHANNEL=chromium ALLOW_HEADFUL_BROWSER=true uvicorn app.main:app --reload --port 8001
```

Depois envie uma requisicao com:

```json
{
  "identificador": "A Anne Christine Silva Ribeiro",
  "headless": false
}
```

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
- Como o portal pode sofrer mudanças de marcação HTML, os seletores foram escritos com heurísticas. O ideal em um ambiente real é validar com testes contra o portal ativo.
- O timeout informado na requisição agora é propagado para a navegação e para as esperas internas do Playwright.
- O nome retornado em `nome` é o próprio texto clicado em `link-busca-nome`.
- `cpf` e `localidade` são extraídos da área `dados-tabelados` da tela intermediária.
- `nis` e `valor_recebido` são extraídos da tabela exibida após abrir `accordion-recebimentos-recursos`.
- `tabela_detalhada` é extraída apenas após o clique em `Detalhar`.

## Async e Sync

O projeto hoje possui dois caminhos internos de execução do Playwright:

- `async`: caminho principal, usado em Docker, WSL e ambientes compatíveis. E o fluxo otimizado com browser compartilhado, pool de `context/page` e melhor uso de concorrencia.
- `sync`: caminho de compatibilidade local para Windows com Python 3.14. Ele existe porque, nesse ambiente, o Playwright assíncrono falhou ao inicializar subprocessos no runtime testado.

Resumo pratico:

- se voce rodar em Docker/WSL, o esperado e usar o caminho `async`
- se voce rodar localmente no Windows com Python 3.14, o app cai no fallback `sync`

O caminho `sync` nao e a arquitetura preferida; ele foi mantido para compatibilidade local. Se o ambiente for padronizado em Docker/WSL ou Python 3.11 a 3.13 no Windows, o projeto pode voltar a operar apenas com o fluxo `async`.

## Execução com Docker

```bash
docker build -t most-transparencia-bot .
docker run --rm -p 8000:8000 most-transparencia-bot
```

Ou com Compose:

```bash
docker compose up --build
```

Convencao recomendada:

- Docker em `http://127.0.0.1:8000`
- API local em `http://127.0.0.1:8001`

Se quiser rodar Docker e API local ao mesmo tempo, use:

```bash
HOST_PORT=8000 docker compose up --build
```

e localmente:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

O `--reload` nao fixa a porta `8000`. Ele apenas habilita recarga automatica. Se voce nao informar `--port`, o Uvicorn usa `8000` por padrao.

O container sobe com tudo que a API precisa, incluindo Python, dependencias e Chromium do Playwright. Isso permite testar do mesmo jeito no Windows ou no WSL, desde que o Docker esteja funcionando no host.

No Windows nativo com Python 3.14, a API agora funciona em modo local por um fallback síncrono do Playwright. Esse caminho existe para compatibilidade local e pode consumir mais recursos do que o fluxo assíncrono com browser compartilhado usado em Docker/WSL e em Python 3.11 a 3.13.

Teste rapido apos subir o container:

```bash
curl -X POST http://127.0.0.1:8000/consulta-script \
  -H "Content-Type: application/json" \
  -d '{
    "identificador": "Maria"
  }'
```

Configuracoes uteis no container:

- `MAX_CONCURRENT_CONSULTAS`: controla o tamanho do pool de consultas simultaneas
- `BROWSER_CHANNEL`: canal do browser compartilhado pelo processo; padrao `chromium`
- `ALLOW_HEADFUL_BROWSER`: permite requisicoes com `headless=false`; padrao `false`
- `HOST_PORT`: porta publicada no host para acessar o container; padrao `8000`

No `docker-compose.yml`, `ALLOW_HEADFUL_BROWSER` fica definido como `false`.

Na collection do Postman:

- `base_url_docker`: `http://127.0.0.1:8000`
- `base_url_local`: `http://127.0.0.1:8001`
- `base_url`: variavel ativa usada pelas requests

Para testar Docker, deixe `base_url={{base_url_docker}}`. Para testar local, troque para `base_url={{base_url_local}}`.

## Benchmark de memoria

Com a API no ar via Docker, voce pode medir o consumo do container em repouso, por requisicao e em paralelo com:

```bash
chmod +x scripts/benchmark-memory.sh
./scripts/benchmark-memory.sh
```

O script usa os 6 identificadores padrao e reporta:

- memoria em repouso do container
- pico por requisicao em execucao sequencial
- media estimada por requisicao sequencial
- pico total com todas as requisicoes em paralelo
- estimativa por requisicao no cenario paralelo

Exemplo com nomes customizados:

```bash
./scripts/benchmark-memory.sh Maria Jose Joao Joaquim Rosa "A Anne Christine Silva Ribeiro"
```

Para salvar em arquivo:

```bash
OUTPUT_FILE=benchmark-memory.txt ./scripts/benchmark-memory.sh
```

Observacao: os valores sao estimativas de memoria no nivel do container. O script nao mede memoria por thread/processo individual dentro do Chromium.

## Melhorias recomendadas

- testes automatizados com mocks de HTML para cenários previsíveis;
- observabilidade com correlation id por consulta;
- fila assíncrona ou worker dedicado para escalar além do limite por processo;
- implementação prática da Parte 2 em Activepieces com Google Drive e Sheets.
