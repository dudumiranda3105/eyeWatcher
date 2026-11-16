#!/usr/bin/env bash
# eyeWatcher - desliga os servicos mantendo os dados.
# Para apagar tudo (dados, modelos treinados e modelo do Ollama): docker compose down -v
set -euo pipefail
cd "$(dirname "$0")"

docker compose stop

echo
echo "eyeWatcher parado. Os dados foram mantidos."
echo "Para subir de novo: ./iniciar.sh"
