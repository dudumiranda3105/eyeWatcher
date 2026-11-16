#!/usr/bin/env bash
# eyeWatcher - sobe tudo com um comando (Linux, macOS e Git Bash).
#
#   ./iniciar.sh
#
# Confere o Docker, roda `docker compose up -d --build`, espera a aplicacao
# responder, mostra os logins e abre o navegador. Nao precisa configurar chave
# nenhuma: as senhas sao geradas sozinhas na primeira subida e ficam em
# secrets/CREDENCIAIS.txt.
set -euo pipefail
cd "$(dirname "$0")"

URL="http://localhost:8080"

abrir() {
  if command -v open >/dev/null 2>&1; then
    open "$1"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$1" >/dev/null 2>&1 || true
  elif command -v cmd.exe >/dev/null 2>&1; then
    cmd.exe /c start "" "$1"
  fi
}

echo
echo "===== eyeWatcher: iniciando ====="
echo

if ! command -v docker >/dev/null 2>&1; then
  echo "O Docker nao foi encontrado neste computador."
  echo "Instale o Docker Desktop, abra ele uma vez e rode este script de novo:"
  echo "  https://www.docker.com/products/docker-desktop/"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  if [ "$(uname)" = "Darwin" ]; then
    echo "O Docker Desktop esta fechado. Abrindo..."
    open -a Docker
    for i in $(seq 1 48); do
      docker info >/dev/null 2>&1 && break
      echo "Aguardando o Docker ficar pronto... $i/48"
      sleep 5
    done
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "O Docker nao esta rodando. Abra o Docker Desktop (ou inicie o servico do Docker)"
    echo "e rode este script de novo."
    exit 1
  fi
fi

echo "Docker pronto. Subindo os servicos..."
echo "Na primeira vez demora: compila as imagens e baixa o modelo de IA, cerca de 2 GB."
echo
if ! docker compose up -d --build; then
  echo
  echo "Algo deu errado ao subir os servicos. Leia as mensagens acima."
  echo "Para ver os detalhes: docker compose logs"
  exit 1
fi

echo
echo "Aguardando a aplicacao responder em $URL ..."
for i in $(seq 1 120); do
  if curl -s -f -o /dev/null "$URL/"; then
    pronto=1
    break
  fi
  sleep 3
done

if [ "${pronto:-0}" != "1" ]; then
  echo
  echo "A aplicacao ainda nao respondeu. Os containers continuam subindo em segundo plano."
  echo "Confira com: docker compose ps"
  echo "e abra $URL quando todos estiverem healthy."
  exit 1
fi

echo
echo "===== Pronto! ====="
echo
[ -f secrets/CREDENCIAIS.txt ] && cat secrets/CREDENCIAIS.txt
echo
echo "Abrindo $URL no navegador..."
abrir "$URL"
echo
echo 'Obs.: o Assistente (IA) pode levar alguns minutos ate mostrar "Modelo pronto".'
echo "Para desligar tudo: ./parar.sh"
