# Deploy na Oracle Cloud (OCI)

Este projeto pode ser publicado na Oracle Cloud Infrastructure usando uma VM Compute Always Free e o `docker compose`.

Estado do deploy usado na entrega:

- IP publico da API: `http://137.131.226.149:8000`
- hostname da VM: `robo-dados-transparencia-gov`
- usuario SSH: `ubuntu`
- diretorio de deploy na VM: `/home/ubuntu/api-deploy`
- servico Docker Compose: `api`
- container observado no deploy: `api-deploy-api-1`

# Observacao importante da entrega:

- o ambiente publicado do teste tecnico foi operado com **uma requisicao por vez**
- o motivo foi a VM gratuita efetivamente disponivel no momento, com **1 GB de RAM**
- o Docker foi mantido no deploy por reproducibilidade e facilidade operacional

# Criar a VM na OCI

Recomendacao:

- na camada Always Free, a OCI oferece ate `4 OCPUs` e `24 GB` de memoria no shape `VM.Standard.A1.Flex`
- no momento da producao desta entrega, a opcao gratuita mais robusta nao estava disponivel, entao o deploy precisou ser feito em uma VM menor

