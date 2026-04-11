# Desafio Full Stack Developer - Python (RPA e Hiperautomação)

Implementação da **Parte 1** do desafio com:

- robô em **Python + Playwright** para consulta no Portal da Transparência;
- **API FastAPI** para disparar o robô e expor documentação Swagger/OpenAPI em /docs;
- captura de screenshot do fluxo em base64;
- coleta dos dados principais do beneficiário e da tabela detalhada do benefício.

Também incluí o desenho e a configuração final da **Parte 2 (bônus)** em [docs/bonus-workflow.md](docs/bonus-workflow.md), incluindo:

- formulário web publicado no Activepieces: https://cloud.activepieces.com/forms/RLSVQlGIDcQj4jJZVhSE5;
- pasta pública do Google Drive com os JSONs gerados: <https://drive.google.com/drive/folders/1EK8W9fshaogdNz6oylq7zkAxE2h4Ci-V?usp=sharing>.
- planilha pública do google sheets: https://docs.google.com/spreadsheets/d/1jP-pSZr5nLiRWRTEhshemGPGzEUhqnHtbY0_mEiHTdE/edit?gid=102423035#gid=102423035
## Algoritmo da automação

O robô da Parte 1 segue este fluxo:

1. recebe `identificador` pela API;
2. monta a URL de busca de pessoa física no Portal da Transparência;
3. abre a tela de resultados;
4. tenta dispensar o banner de cookies, se existir;
5. abre `Refine a Busca`;
6. marca `Beneficiário de Programa Social`;
7. dispara novamente a consulta;
8. detecta a contagem de resultados ou a lista de links;
9. se não houver resultado, captura evidência e retorna `sem_resultados`;
10. se houver resultado, clica no primeiro nome retornado;
11. extrai os dados principais da tela intermediária da pessoa;
12. abre o accordion de recebimentos;
13. extrai `nis` e `valor_recebido` da primeira linha da tabela;
14. captura screenshot em base64 com a seção de recebimentos aberta;
15. clica em `Detalhar`;
16. extrai a tabela detalhada final;
17. devolve o JSON consolidado pela API.

## Referências do site usadas para clicar, preencher e copiar

### Busca inicial

A automação não preenche um formulário na home. Ela monta a URL de busca diretamente:

- rota: `/pessoa-fisica/busca/lista`
- parâmetros:
  - `termo={{identificador}}`
  - `pagina=1`
  - `tamanhoPagina=10`

Implementação:

- [app/consulta/common.py](/mnt/c/Most/Most-teste/app/consulta/common.py)

### Banner de cookies

Se houver banner, o robô tenta clicar em botões com estes textos:

- `Aceitar`
- `Concordo`
- `Continuar`

Seletores:

- `button:has-text('Aceitar')`
- `button:has-text('Concordo')`
- `button:has-text('Continuar')`

### Busca refinada

Para abrir a área correta de filtros, usa:

- botão:
  - `button.header[aria-controls='box-busca-refinada']`
- container:
  - `#box-busca-refinada`

### Filtro de programa social

Para cumprir o cenário do desafio, usa:

- checkbox:
  - `#beneficiarioProgramaSocial`
- label do checkbox:
  - `label[for='beneficiarioProgramaSocial']`
- botão de consultar:
  - `#btnConsultarPF`

Fluxo:

- abre a busca refinada;
- garante que o checkbox de beneficiário esteja marcado;
- clica no botão de consultar;
- aguarda nova navegação.

### Leitura dos resultados

O robô considera como referência de resultado qualquer um destes sinais:

- contador:
  - `#countResultados`
- links do nome:
  - `a.link-busca-nome`
- fallback de link:
  - `a[href*='/busca/pessoa-fisica/']`
- fallback textual no corpo da página:
  - `Foram encontrados X resultados`

### Clique no beneficiário

O primeiro resultado compatível é clicado por:

- `a.link-busca-nome, a[href*='/busca/pessoa-fisica/']`

Depois disso, a automação valida se entrou numa URL contendo:

- `/busca/pessoa-fisica/`

### Extração dos dados principais

Na tela intermediária da pessoa, usa como referência:

- `section.dados-tabelados`

Dentro dessas seções, percorre:

- `li`
- `tr`
- `.row`
- `.col`
- `.dados-tabelados__item`

Estratégia:

- lê os textos dos blocos;
- normaliza rótulos;
- monta pares `campo -> valor`;
- tenta extrair:
  - `cpf`
  - `localidade`

Se a leitura estruturada falhar, aplica fallback por regex no texto da seção.

### Recebimentos de recursos

Para abrir a seção do benefício, usa:

- `button.header[aria-controls='accordion-recebimentos-recursos']`

Depois aguarda:

- `#accordion-recebimentos-recursos table`
- `#accordion-recebimentos-recursos a#btnDetalharBpc`
- `#accordion-recebimentos-recursos a[href*='/beneficios/']`

### Extração de NIS e valor recebido

Com o accordion aberto, lê:

- `#accordion-recebimentos-recursos table`

Na tabela:

- cabeçalhos em `thead th`
- linhas em `tbody tr`

Da primeira linha, procura os campos:

- `NIS`
- `Valor Recebido`
- `Valor`
- `Valor do benefício`
- `Valor do beneficio`

### Screenshot de evidência

O screenshot é gerado em:

- página inteira;
- formato `png`;
- retorno em `base64`

Ele é capturado depois da abertura do accordion `accordion-recebimentos-recursos`, para registrar visualmente o beneficiário e os dados do recebimento.

### Clique em Detalhar

Para navegar ao detalhe final do benefício, usa:

- `a#btnDetalharBpc`
- fallback:
  - `a.br-button.secondary.mt-3[href*='/beneficios/']`

Depois valida navegação para URL contendo:

- `/beneficios/`

### Tabela detalhada final

Na última tela, lê:

- `#tabelaDetalheDisponibilizado`

Estratégia:

- cabeçalhos em `thead th`
- linhas em `tbody tr`
- células em `td`

Se o número de colunas não bater com os cabeçalhos, usa fallback:

- `coluna_1`
- `coluna_2`
- ...

## Estratégia de robustez

Para reduzir a chance de quebra por variação do portal, a automação usa:

- espera por visibilidade antes dos cliques;
- `expect_navigation` nas mudanças de página;
- mais de um seletor para a mesma etapa;
- fallback por texto da página para detectar quantidade de resultados;
- delays curtos com jitter;
- script de stealth no Playwright para reduzir sinais diretos de automação.

## Decisões técnicas

- **Playwright** foi escolhido por ser robusto em navegação headless, melhor com páginas dinâmicas e adequado para execuções simultâneas com contexts isolados.
- **FastAPI** entrega API simples, validação de payload com Pydantic e Swagger automático em `/docs`.
- A automação foi escrita com **seletores defensivos e fallbacks**, porque o Portal da Transparência pode variar discretamente na estrutura HTML.
- O fluxo usa **esperas por estado visível e navegação**, com um jitter curto entre ações em vez de sleeps longos fixos.
- Cada requisição cria sua própria aba do browser/context.
- O código foi preparado para execução concorrente, mas o ambiente publicado deste teste técnico ficou limitado pela VM disponível.
- Na publicação usada na entrega, a execução foi configurada para **1 requisição por vez**, porque a VM obtida na Oracle Free Tier tem apenas **1 GB de RAM** e não sustenta com estabilidade múltiplas abas do browser simultâneas.

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
  "cpf": "***.734.995-**",
  "localidade": "PROPRI? - SE",
  "nome_busca": "A Anne Christine Silva Ribeiro",
  "resultado_clicado": "A ANNE CHRISTINE SILVA RIBEIRO",
  "url_busca": "https://portaldatransparencia.gov.br/pessoa-fisica/busca/lista?termo=A+Anne+Christine+Silva+Ribeiro&pagina=1&tamanhoPagina=10",
  "beneficios": [
    {
      "nome": "A ANNE CHRISTINE SILVA RIBEIRO",
      "nis": "123.45678.90-1",
      "valor_recebido": "R$ 3.900,00",
      "tipo_beneficio": "auxilio-emergencial",
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
      }
    }
  ],
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
- os campos principais retornados no topo do JSON s?o:
  - `nome`
  - `cpf`
  - `localidade`
  - `nome_busca`
  - `resultado_clicado`
  - `url_busca`
  - `beneficios`
  - `evidencia_base64`
- em caso de busca sem resultados, retorna `status` = `sem_resultados`.
- em caso de timeout, retorna:
  - `N?o foi poss?vel retornar os dados no tempo de resposta solicitado`
## Observações importantes

- O fluxo usa a busca direta da pessoa física no Portal da Transparência.
- A seleção do primeiro resultado compatível é intencional, alinhada ao critério do desafio.
- O nome retornado em `nome` é o próprio texto clicado em `link-busca-nome`.
- `cpf` e `localidade` são extraídos da área `dados-tabelados` da tela intermediária.
- `nis` e `valor_recebido` são extraídos da tabela exibida após abrir `accordion-recebimentos-recursos`.
- `tabela_detalhada` é extraída apenas após o clique em `Detalhar`.

## Limitação operacional da entrega

- O fluxo de automação publicado na **Activepieces** para avaliação deve ser usado com **uma requisição por vez**.
- Essa limitação não é uma restrição conceitual do código, e sim do ambiente disponível para a entrega.
- A VM Oracle Free Tier disponível no momento da produção deste teste técnico tinha **1 GB de RAM**, o que inviabilizou manter múltiplas execuções simultâneas do navegador com estabilidade aceitável.
- Em benchmark controlado **em ambiente local**, foi possível validar lote com **6 requisições simultâneas** retornando em cerca de **13 segundos**.
- A intenção original era usar a opção gratuita mais robusta da Oracle com **24 GB de RAM**, o que provavelmente permitiria operar algo na faixa de **20 a 50 requisições simultâneas** sem custo.
- Isso não foi possível porque, no momento da execução deste teste técnico, **não havia máquinas disponíveis** nessa configuração gratuita dentro da Oracle Cloud.

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

Em uma VM com menos recursos, aumente o timeout da requisição:

```bash
REQUEST_TIMEOUT=600 OUTPUT_FILE=benchmark-latency.txt ./scripts/benchmark-latency.sh
```

## Benchmark de memória

Com a API já no ar e o container `api` ativo no `docker compose`:

```bash
chmod +x scripts/benchmark-memory.sh
./scripts/benchmark-memory.sh
```

Para aumentar o timeout e salvar a saída:

```bash
REQUEST_TIMEOUT=600 OUTPUT_FILE=benchmark-memory.txt ./scripts/benchmark-memory.sh
```

## Benchmark completo para servidor

Se quiser executar latência e memória em sequência, com timeout maior e arquivos separados:

```bash
chmod +x scripts/benchmark-server.sh
LATENCY_TIMEOUT=600 MEMORY_TIMEOUT=600 ./scripts/benchmark-server.sh
```
