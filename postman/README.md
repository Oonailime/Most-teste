# Postman

Collection pronta para importação:

- [most-transparencia-bot.postman_collection.json](/mnt/c/Most/Most-teste/postman/most-transparencia-bot.postman_collection.json)

## Como usar

1. Inicie a API local:

```bash
python -m uvicorn app.main:app --reload
```

2. No Postman, importe a collection JSON.
3. Confirme a variável `base_url` com `http://127.0.0.1:8000`.
4. Execute os requests individualmente ou use o Collection Runner.
5. Para testar a VM Oracle, use a pasta `Servidor Oracle`, que aponta para `http://137.131.226.149:8000`.

## Variáveis incluídas

- `base_url`
- `base_url_server = http://137.131.226.149:8000`
- `nome_comum_1 = A Anne Christine Silva Ribeiro`
- `nome_comum_2 = Jose Santos`
- `nome_comum_3 = Ana Souza`
- `nome_inexistente = NOME INEXISTENTE XYZ TESTE`

Se quiser, altere esses nomes no próprio Postman antes de rodar a collection.

## Requests incluídos

- `Healthcheck`
- `Consulta - Sucesso por Nome`
- `Consulta - Sucesso por Nome 2`
- `Consulta - Modo Visível`
- `Consulta - Erro Nome Inexistente`
- `Consulta - Validação de Filtro Inválido`
- pasta `Servidor Oracle` com requests para a API publicada

## Como usar o modo assistido

1. Execute `Consulta - Modo Visível`.
2. O navegador será aberto de forma visível.
3. O robô abrirá a URL de busca já preenchida pelo nome.
4. O resultado será aberto automaticamente no próprio navegador visível.
5. O robô continua sozinho e retorna o JSON final.
