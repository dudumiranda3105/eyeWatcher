# eyeWatcher

Monitoramento AIoT de salas de servidores: sensores, atuadores, gêmeo digital 3D,
manutenção preditiva e um assistente com LLM local, tudo subindo com um comando.

## O problema

Servidor caseiro, de laboratório ou de empresa pequena quase nunca fica numa sala
com climatização monitorada. O resultado é sempre o mesmo: a temperatura sobe
devagar, o processador reduz a frequência e em algum momento alguma coisa desliga
sozinha. Só aí alguém percebe que tinha um problema, e não sobra nenhum registro.

No 1º bimestre o eyeWatcher resolveu a parte de medir e guardar o histórico. Agora
ele também olha para quem causa o problema: os **ar-condicionados de precisão
(CRACs)** da sala. Eles se desgastam aos poucos, e a IA percebe isso pela vibração,
pela corrente, pela temperatura e pela rotação antes de a máquina parar e a sala
esquentar.

Tem mais detalhe em [docs/PROBLEMA.md](docs/PROBLEMA.md).

## Arquitetura

```mermaid
flowchart TB
    SIM["Simulador<br/>sensores e atuadores"] <-->|MQTT| MOS["Mosquitto<br/>broker MQTT"]
    MOS <-->|MQTT| GW["Gateway<br/>MQTT para RabbitMQ"]
    GW <--> RMQ["RabbitMQ (AMQP)<br/>exchange topic, filas de telemetria,<br/>eventos, comandos e jobs"]

    RMQ --> REC["Gravador"]
    REC --> INF[("InfluxDB<br/>séries temporais")]
    RMQ <--> IA["Inferência IA<br/>regressão ao vivo"]
    RMQ <--> LAB["Lab e treino<br/>dados e modelos"]
    LAB --> MOD[("Modelos<br/>volume compartilhado")]
    MOD --> IA
    RMQ <--> API["API FastAPI<br/>REST, WebSocket e regras"]
    API <--> PG[("PostgreSQL<br/>cadastros e regras")]
    API <--> LLM["LLM local<br/>Ollama, em CPU"]
    API <--> WEB["Frontend Web<br/>dashboard, 3D, insights e assistente"]
```

Todo dado passa pelo RabbitMQ. O detalhe de cada fluxo está em
[docs/ARQUITETURA.md](docs/ARQUITETURA.md).

## Rodando

### O que precisa estar instalado

| Item | Detalhe |
|---|---|
| **Docker Desktop** | É a única coisa para instalar: [baixar aqui](https://www.docker.com/products/docker-desktop/). Já inclui o Docker Compose. No Linux, use o Docker Engine com o plugin `docker-compose-plugin`. |
| Sistema | Windows 10 ou 11 de 64 bits, macOS ou Linux |
| Virtualização | Ligada na BIOS (no Windows também precisa do WSL2; o instalador do Docker cuida disso e pode pedir para reiniciar) |
| Memória | 8 GB livres para o Docker ou mais, por causa do modelo de IA |
| Disco | Uns 15 GB livres |
| Internet | Só na primeira subida, para baixar as imagens e o modelo de IA |
| Portas livres | 8080, 15672, 8086 e 8081 |

Não precisa instalar Python, Node, banco de dados nem nada além do Docker: tudo roda
dentro dos containers.

### Começo rápido (dois cliques)

1. Instale o Docker Desktop (tabela acima), abra ele uma vez e aceite os termos.
2. Baixe o projeto (**Code → Download ZIP** aqui no GitHub e extraia, ou `git clone`).
3. Dê dois cliques em **`iniciar.bat`** (Windows) ou rode `./iniciar.sh` (Linux e macOS).

O script primeiro confere o computador e **avisa o que falta**: Docker não instalado,
Docker Compose ausente ou antigo, Docker fechado, pouca memória ou disco, portas
ocupadas. Depois abre o Docker Desktop se ele estiver fechado, sobe os 16 serviços,
espera a aplicação responder, mostra os logins na tela e abre o navegador em
**http://localhost:8080**. Para desligar, use **`parar.bat`** ou `./parar.sh`; os dados
ficam guardados para a próxima vez.

**Não existe chave nem arquivo `.env` para configurar.** O serviço `bootstrap` gera
todas as senhas sozinho na primeira subida e as grava em `secrets/CREDENCIAIS.txt`,
que fica fora do Git. Nada de segredo está neste repositório.

A primeira subida demora (uns 10 a 20 minutos, dependendo da internet), porque
compila as imagens e baixa o modelo do Ollama (cerca de 2 GB). As próximas levam
poucos minutos.

### Se der erro

| O que aparece | O que fazer |
|---|---|
| `FALTA INSTALAR: Docker Desktop` | Instale pelo link da tabela acima, reinicie se o instalador pedir, abra o Docker Desktop e rode o script de novo |
| `O Docker Desktop nao ficou pronto a tempo` | Aceite os termos na janela do Docker; confira se a virtualização está ligada na BIOS; no PowerShell como administrador, rode `wsl --install` e reinicie |
| `FALTA ATUALIZAR: Docker Compose` | Atualize o Docker Desktop para a versão mais recente |
| `PORTA JA EM USO` | Feche o programa que usa a porta (`netstat -ano \| findstr :8080` mostra o PID) |
| `AVISO` de memória | Dê pelo menos 8 GB ao Docker (no WSL2, arquivo `.wslconfig` com `memory=8GB`) |
| `Algo deu errado ao subir` | Confira a internet (a primeira subida baixa tudo) e o espaço em disco; detalhes em `docker compose logs` |
| Assistente sem "Modelo pronto" | Espere alguns minutos: o modelo de IA ainda está carregando na memória |

### Pelo terminal

É o que os scripts fazem por baixo:

```bash
docker compose up -d --build
```

A aplicação fica em **http://localhost:8080**.

### Usuários de demonstração

| Usuário | Papel | O que pode |
|---|---|---|
| `visualizador` | Visualizador | Só vê |
| `operador` | Operador | Comanda atuadores e o simulador |
| `administrador` | Administrador | Também gera dados, treina modelos, cadastra dispositivos e vê a auditoria |

As senhas são geradas na primeira subida e ficam em `secrets/CREDENCIAIS.txt`.

## O que tem em cada página

| Página | O que faz |
|---|---|
| Dashboard | Leituras ao vivo, histórico, estatísticas, atuadores e alertas |
| Gêmeo digital | Sala em 3D movida só pelos dados do WebSocket |
| Insights | Saúde, vida útil restante, tendência, alertas e injeção de falha |
| Assistente | Chat com o LLM local sobre os dados da solução |
| Laboratório de dados | Geração configurável de dados sintéticos |
| Treinamento | Dispara o treino e mostra métricas, base simples e importância dos atributos |
| Dispositivos e regras | Cadastro de dispositivos e regras automáticas |
| Mensageria | Filas, taxas, consumidores, últimas mensagens e DLQ, ao vivo |
| Auditoria | Logins, comandos, jobs e perguntas ao assistente |
| Serviços | Links das interfaces do RabbitMQ, do InfluxDB e do PostgreSQL |

## Sensores, atuadores e equipamentos

| Tipo | Dispositivos |
|---|---|
| Sensores | Temperatura dos racks 01 e 02, umidade, luminosidade, corrente do rack, presença |
| Atuador por regra | Exaustor (liga em 35 °C, desliga em 31 °C), sirene (liga em 38 °C) |
| Atuador pela Web | Iluminação, e os dois CRACs |
| Equipamento monitorado | `crac-01` e `crac-02`: vibração, corrente, temperatura e rotação |

Os atuadores mudam a física da sala. Desligar os CRACs esquenta o ambiente, o que
aciona o exaustor pela regra. Ligar a luz sobe a luminosidade medida.

## O relógio simulado

Cada leitura sai a cada 2 segundos e representa **10 minutos** da vida da sala. Um
dia passa em cerca de 5 minutos, e uma falha de dias acontece durante a
apresentação. As horas de vida útil mostradas são horas simuladas.

## Como rodar cada parte da demonstração

O roteiro completo, na ordem da apresentação, está em
[docs/APRESENTACAO.md](docs/APRESENTACAO.md). Em resumo:

1. **Web para IoT:** no Dashboard, ligue a iluminação e veja a luminosidade subir.
2. **Regra automática:** desligue os dois CRACs. Em cerca de 30 segundos a
   temperatura passa de 35 °C e o exaustor liga sozinho.
3. **Consumidor parado:** rode `docker compose stop recorder` e olhe a fila
   `q.telemetry.influx` crescer na Mensageria. Com `docker compose start recorder`
   ela esvazia, e nenhum ponto se perde.
4. **DLQ:** na Mensageria, clique em "Publicar mensagem inválida".
5. **IA:** gere dados no Laboratório, treine em Treinamento e injete uma falha em
   Insights. A saúde cai em cerca de 1 minuto, e a cena 3D acompanha.
6. **Assistente:** pergunte "qual equipamento está com a pior saúde?".

## Tecnologias

| Camada | O que usamos |
|---|---|
| Frontend | Vue 3, TypeScript, Vite, Pinia |
| Gráficos | Chart.js |
| 3D | Three.js |
| Backend | Python, FastAPI, WebSocket |
| IoT | MQTT com Mosquitto, dispositivo simulado em Python |
| Mensageria | RabbitMQ |
| IA | scikit-learn (regressão com gradient boosting), numpy e pandas |
| LLM local | Ollama com `llama3.2:3b`, em CPU |
| Bancos | PostgreSQL e InfluxDB 2.x |
| Infra | Docker e Docker Compose |

## Organização das pastas

```
eyeWatcher/
├── docker-compose.yml   a solução inteira
├── backend/             todos os serviços Python, uma imagem só
│   ├── eyewatcher/
│   │   ├── api/         FastAPI, auth, regras, assistente
│   │   ├── services/    simulador, gateway, gravador, inferência, lab, treino
│   │   ├── physics.py   física da sala, usada pelo gerador e pelo simulador
│   │   └── features.py  features, usadas pelo treino e pela inferência
│   └── tests/
├── frontend/            Vue, cena 3D e nginx
├── infra/               Mosquitto, RabbitMQ e o gerador de segredos
├── firmware/            ESP32 do 1º bimestre, mantido como histórico
└── docs/                documentação do projeto
```

## Portas

| Porta | Serviço | Acesso |
|---|---|---|
| 8080 | Aplicação | Publicada |
| 15672 | RabbitMQ | Só 127.0.0.1 |
| 8086 | InfluxDB | Só 127.0.0.1 |
| 8081 | Adminer (PostgreSQL) | Só 127.0.0.1 |

## Testes

```bash
cd backend
pip install -r requirements.txt pytest
pytest
```

## Zerar tudo

Apaga os dados, os modelos treinados e o modelo do Ollama:

```bash
docker compose down -v
```

## Documentação

- [docs/PROBLEMA.md](docs/PROBLEMA.md): o problema e a proposta
- [docs/ARQUITETURA.md](docs/ARQUITETURA.md): fluxos e decisões técnicas
- [docs/CONTRACT.md](docs/CONTRACT.md): tópicos, filas, mensagens e rotas
- [docs/APRESENTACAO.md](docs/APRESENTACAO.md): roteiro da apresentação

## Autores

| Nome | GitHub |
|---|---|
| Eduardo Miranda | [@dudumiranda3105](https://github.com/dudumiranda3105) |
| Eduarda Roberta Borges da Silva | [@Eduarda-Borges-Silva](https://github.com/Eduarda-Borges-Silva) |
| Rebeca Souza Lúcio Chagas | [@RebecaSLChagas](https://github.com/RebecaSLChagas) |
| Edson Gabriel Klippel Pereira | - |
