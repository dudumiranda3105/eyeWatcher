#!/usr/bin/env bash
# eyeWatcher - sobe tudo com um comando (Linux, macOS e Git Bash).
#
#   ./iniciar.sh
#
# 1. confere o que o computador precisa ter e avisa o que falta instalar
# 2. abre o Docker Desktop (macOS) se ele estiver fechado
# 3. roda `docker compose up -d --build`
# 4. espera a aplicacao responder, mostra os logins e abre o navegador
#
# Nao precisa configurar chave nenhuma: as senhas sao geradas sozinhas na
# primeira subida e ficam em secrets/CREDENCIAIS.txt.
#
# EYEWATCHER_SEM_NAVEGADOR=1 evita abrir o navegador (usado nos testes).
set -euo pipefail
cd "$(dirname "$0")"

URL="http://localhost:8080"
DOCKER_URL="https://www.docker.com/products/docker-desktop/"

ok() { echo "[ok] $*"; }
aviso() { echo "[!!] $*"; }

abrir() {
  [ -n "${EYEWATCHER_SEM_NAVEGADOR:-}" ] && return 0
  if command -v open >/dev/null 2>&1; then
    open "$1"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$1" >/dev/null 2>&1 || true
  elif command -v cmd.exe >/dev/null 2>&1; then
    cmd.exe /c start "" "$1"
  fi
}

porta_em_uso() {
  # Em bash, abrir /dev/tcp so funciona se alguem estiver escutando na porta.
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

sem_docker() {
  echo
  echo "============================================================"
  echo " FALTA INSTALAR: Docker"
  echo "============================================================"
  echo
  echo " O eyeWatcher roda dentro do Docker, e ele nao esta instalado"
  echo " neste computador. Faca isto uma vez so:"
  echo
  echo "  1. Instale o Docker Desktop (Windows e macOS):"
  echo "     $DOCKER_URL"
  echo "     No Linux, instale o Docker Engine com o plugin Compose:"
  echo "     https://docs.docker.com/engine/install/"
  echo "  2. Abra o Docker Desktop, aceite os termos e espere ele ficar pronto."
  echo "  3. Rode ./iniciar.sh de novo."
  echo
  echo " Requisitos: 8 GB de RAM ou mais e uns 15 GB livres no disco."
  echo
  abrir "$DOCKER_URL"
  exit 1
}

echo
echo "===== eyeWatcher: iniciando ====="
echo
echo "Conferindo o que o computador precisa ter..."
echo

# ---- 1. Docker instalado? ---------------------------------------------------
command -v docker >/dev/null 2>&1 || sem_docker
ok "Docker instalado"

# ---- 2. Docker aberto? ------------------------------------------------------
if ! docker info >/dev/null 2>&1; then
  if [ "$(uname)" = "Darwin" ]; then
    aviso "O Docker Desktop esta fechado. Abrindo para voce..."
    open -a Docker
    for i in $(seq 1 48); do
      docker info >/dev/null 2>&1 && break
      echo "     aguardando o Docker ficar pronto... $i/48"
      sleep 5
    done
  fi
  if ! docker info >/dev/null 2>&1; then
    echo
    echo "============================================================"
    echo " O Docker esta instalado, mas nao esta rodando"
    echo "============================================================"
    echo
    echo " - Windows ou macOS: abra o Docker Desktop, aceite os termos se ele"
    echo "   pedir e espere o icone parar de animar."
    echo " - Linux: inicie o servico (sudo systemctl start docker) e confira se"
    echo "   seu usuario esta no grupo docker."
    echo " - Se ele nao abre: a virtualizacao pode estar desligada na BIOS, ou"
    echo "   o WSL2 nao esta instalado (Windows: wsl --install no PowerShell"
    echo "   como administrador, depois reinicie)."
    echo
    echo " Resolva e rode ./iniciar.sh de novo."
    exit 1
  fi
fi
ok "Docker aberto e funcionando"

# ---- 3. Docker Compose ------------------------------------------------------
if ! docker compose version >/dev/null 2>&1; then
  echo
  echo "============================================================"
  echo " FALTA ATUALIZAR: Docker Compose"
  echo "============================================================"
  echo
  echo " O Docker esta instalado, mas sem o comando \"docker compose\" ou numa"
  echo " versao antiga. Atualize o Docker Desktop (ou instale o pacote"
  echo " docker-compose-plugin no Linux) e rode ./iniciar.sh de novo."
  exit 1
fi
ok "Docker Compose disponivel"

# ---- 4. Memoria que o Docker enxerga ----------------------------------------
mem_bytes="$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0)"
mem_mb=$((mem_bytes / 1000000))
if [ "$mem_mb" -gt 0 ] && [ "$mem_mb" -lt 7500 ]; then
  aviso "AVISO: o Docker so enxerga cerca de ${mem_mb} MB de memoria."
  echo "     O projeto precisa de uns 8 GB. Com menos, o Assistente de IA pode"
  echo "     travar ou falhar. Aumente em Docker Desktop > Settings > Resources"
  echo "     (no Windows com WSL2, use o arquivo .wslconfig com memory=8GB)."
elif [ "$mem_mb" -gt 0 ]; then
  ok "Memoria para o Docker: cerca de ${mem_mb} MB"
fi

# ---- 5. Espaco em disco -----------------------------------------------------
livre_gb="$(df -Pk . 2>/dev/null | awk 'NR==2 {print int($4 / 1048576)}' || true)"
if [ -n "$livre_gb" ]; then
  if [ "$livre_gb" -lt 15 ]; then
    aviso "AVISO: so ha ${livre_gb} GB livres no disco."
    echo "     A primeira subida baixa e guarda cerca de 10 GB entre imagens e o"
    echo "     modelo de IA. Libere espaco se o download falhar."
  else
    ok "Espaco em disco: ${livre_gb} GB livres"
  fi
fi

# ---- 6. curl (usado para esperar a aplicacao) -------------------------------
sem_curl=""
if ! command -v curl >/dev/null 2>&1; then
  sem_curl=1
  aviso "AVISO: curl nao encontrado. Nao vou conseguir esperar a aplicacao responder."
fi

# ---- 7. Portas livres -------------------------------------------------------
# So confere se o eyeWatcher ainda nao esta rodando; senao as portas ocupadas
# seriam as dele mesmo.
if [ -z "$(docker compose ps -q 2>/dev/null)" ]; then
  ocupadas=""
  for porta in 8080 15672 8086 8081; do
    if porta_em_uso "$porta"; then ocupadas="$ocupadas $porta"; fi
  done
  if [ -n "$ocupadas" ]; then
    echo
    echo "============================================================"
    echo " PORTA JA EM USO por outro programa:$ocupadas"
    echo "============================================================"
    echo
    echo " O eyeWatcher usa estas portas: 8080 aplicacao, 15672 RabbitMQ,"
    echo " 8086 InfluxDB e 8081 Adminer. Feche o programa que esta usando"
    echo " as portas acima e rode ./iniciar.sh de novo."
    echo
    echo " Para descobrir quem usa uma porta, por exemplo a 8080:"
    echo "   lsof -i :8080"
    exit 1
  fi
  ok "Portas 8080, 15672, 8086 e 8081 livres"
fi

echo
echo "Tudo certo. Subindo os servicos..."
echo "Na primeira vez demora: compila as imagens e baixa o modelo de IA, cerca de 2 GB."
echo "E precisa de internet nessa primeira vez."
echo
if ! docker compose up -d --build; then
  echo
  echo "============================================================"
  echo " Algo deu errado ao subir os servicos"
  echo "============================================================"
  echo
  echo " Leia as mensagens acima. Causas comuns:"
  echo "  - Sem internet: na primeira vez o Docker baixa imagens e o modelo de IA."
  echo "  - Pouco espaco em disco."
  echo "  - Docker travado: feche, abra de novo e rode ./iniciar.sh."
  echo
  echo " Para ver os detalhes: docker compose logs"
  exit 1
fi

echo
pronto=""
if [ -n "$sem_curl" ]; then
  pronto=1
else
  echo "Aguardando a aplicacao responder em $URL ..."
  for _ in $(seq 1 120); do
    if curl -s -f -o /dev/null "$URL/"; then
      pronto=1
      break
    fi
    sleep 3
  done
fi

if [ -z "$pronto" ]; then
  echo
  echo "A aplicacao ainda nao respondeu. Os containers continuam subindo em segundo plano."
  echo "Confira com: docker compose ps"
  echo "e abra $URL quando todos estiverem healthy."
  exit 1
fi

echo
echo "===== Pronto ====="
echo
[ -f secrets/CREDENCIAIS.txt ] && cat secrets/CREDENCIAIS.txt
echo
echo "Aplicacao: $URL"
abrir "$URL"
echo
echo 'Obs.: o Assistente (IA) pode levar alguns minutos ate mostrar "Modelo pronto".'
echo "Para desligar tudo: ./parar.sh"
