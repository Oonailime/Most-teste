# Deploy na Oracle Cloud (OCI)

Este projeto pode ser publicado na Oracle Cloud Infrastructure usando uma VM Compute Always Free e o `docker compose`.

Convencao deste guia:

- OCI VM publica
- Docker publicado na porta `8000`
- app acessivel em `http://IP_PUBLICO:8000`

## 1. Criar a VM na OCI

Recomendacao:

- shape: `VM.Standard.A1.Flex` se houver capacidade Always Free
- sistema: Ubuntu ou Oracle Linux
- rede: subnet publica com IP publico
- SSH key: informe sua chave publica na criacao

Observacao:

- na camada Always Free, a OCI oferece ate `4 OCPUs` e `24 GB` de memoria no shape `VM.Standard.A1.Flex`
- se der erro de capacidade, tente outra availability domain ou tente mais tarde

## 2. Liberar acesso de rede

Na OCI, adicione regra(s) de entrada para:

- TCP `22` para SSH
- TCP `8000` para a API

Se quiser restringir acesso, troque `0.0.0.0/0` pelo seu IP publico.

## 3. Conectar por SSH

Exemplo:

```bash
ssh -i /caminho/da/sua-chave.pem ubuntu@IP_PUBLICO
```

Em algumas imagens Oracle Linux, o usuario padrao pode ser `opc`.

## 4. Instalar Docker na VM

Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
newgrp docker
docker --version
docker compose version
```

## 5. Copiar o projeto para a VM

Via git:

```bash
git clone URL_DO_SEU_REPOSITORIO most-transparencia-bot
cd most-transparencia-bot
```

Ou envie os arquivos por `scp`/zip, se ainda nao tiver repositório remoto.

## 6. Subir a API

Na VM:

```bash
cd ~/most-transparencia-bot
HOST_PORT=8000 docker compose up --build -d
```

Verificacoes:

```bash
docker compose ps
docker compose logs --tail=200
curl http://127.0.0.1:8000/health
```

Teste externo, da sua maquina:

```bash
curl http://IP_PUBLICO:8000/health
```

Teste da API:

```bash
curl -X POST http://IP_PUBLICO:8000/consulta-script \
  -H "Content-Type: application/json" \
  -d '{"identificador":"Maria"}'
```

## 7. Operacao basica

Subir:

```bash
HOST_PORT=8000 docker compose up --build -d
```

Ver logs:

```bash
docker compose logs -f
```

Parar:

```bash
docker compose down
```

Atualizar:

```bash
git pull
HOST_PORT=8000 docker compose up --build -d
```

## 8. Observacoes

- o `docker-compose.yml` publica `8000` por padrao
- `ALLOW_HEADFUL_BROWSER` fica `false` no deploy
- se quiser expor em outra porta, altere `HOST_PORT`
- se a VM nao responder externamente, revise:
  - regra de ingress da OCI
  - firewall do sistema operacional
  - `docker compose ps`

## 9. Opcional: manter ligado apos reboot

Se quiser subir automaticamente no boot, crie um service systemd depois que o deploy manual estiver funcionando.
