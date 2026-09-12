# scripts/ — operação do eyeWatcher no Windows

Esta pasta é o **caminho principal** para colocar o eyeWatcher no ar.

A máquina de desenvolvimento do projeto **não tem Docker instalado**, então a
infraestrutura (broker MQTT + banco de séries temporais) roda **nativamente no
Windows**. O `infra/docker-compose.yml` existe como caminho alternativo, para
quem conseguir instalar o Docker Desktop depois — ele usa exatamente as mesmas
portas, org e bucket definidos em `docs/CONTRACT.md`.

---

## Antes de tudo: liberar a execução de scripts

Por padrão o Windows bloqueia a execução de arquivos `.ps1`. Abra o PowerShell e
rode:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

O escopo `Process` vale **só para aquela janela do PowerShell**: nada é alterado
permanentemente na máquina, e ao fechar a janela a política volta ao normal.
Repita o comando toda vez que abrir um PowerShell novo para rodar os scripts.

> Se aparecer "não pode ser carregado porque a execução de scripts foi
> desabilitada neste sistema", é exatamente disso que se trata.

Alguns scripts precisam de **PowerShell como Administrador** (instalar
programas, iniciar/parar serviços do Windows). A tabela abaixo indica quais.

---

## Ordem de execução

Na primeira vez, siga esta ordem:

```powershell
# 1. PowerShell COMO ADMINISTRADOR — instala Mosquitto e InfluxDB
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
cd C:\Users\Dudu\Documents\eyeWatcher
.\scripts\install-windows.ps1

# >>> FECHE e reabra o PowerShell (para o PATH ser atualizado) <<<

# 2. Sobe só o banco para poder provisioná-lo
.\scripts\start-all.ps1 -SkipMosquitto -SkipBackend -SkipFrontend

# 3. Cria org, bucket, token e grava backend\.env
.\scripts\setup-influx.ps1

# 4. Sobe a stack inteira
.\scripts\start-all.ps1

# 5. Confere que o MQTT funciona ponta a ponta
.\scripts\test-mqtt.ps1
```

No dia a dia, depois que tudo já está instalado, basta:

```powershell
.\scripts\start-all.ps1     # começar a trabalhar
.\scripts\stop-all.ps1      # terminar
```

---

## O que cada script faz

| Script | Precisa de Admin? | O que faz |
|---|---|---|
| `install-windows.ps1` | **Sim** | Instala Mosquitto, InfluxDB 2.x e o CLI `influx` via `winget`, e instala o `mosquitto.conf` do repositório |
| `setup-influx.ps1` | Não | Cria org `eyewatcher`, bucket `rack_metrics` (30d) e o token, gravando `backend\.env` |
| `start-all.ps1` | Depende¹ | Sobe broker, banco, backend e frontend, esperando cada porta ficar disponível |
| `stop-all.ps1` | Depende¹ | Derruba o que o `start-all.ps1` subiu |
| `test-mqtt.ps1` | Não | Publica e assina uma telemetria de teste para provar que o broker funciona |

¹ Só é necessário Admin se o Mosquitto estiver rodando como **serviço do
Windows** (o `start-all`/`stop-all` precisam de permissão para iniciar/parar
serviços). Se o broker for iniciado como processo normal, não precisa.

---

### `install-windows.ps1`

**Instala as dependências de infraestrutura.** É idempotente: rodar de novo não
duplica nada — o que já estiver instalado é detectado e pulado.

O que ele faz:

1. verifica que você está como Administrador (para em caso contrário, com
   instruções — não falha em silêncio);
2. verifica se o `winget` existe; se não existir, mostra os links de download
   manual e segue com o que dá para fazer;
3. instala **Mosquitto**, **InfluxDB 2.x (servidor)** e o **CLI `influx`**;
4. copia `infra/mosquitto/config/mosquitto.conf` para o diretório de instalação
   do Mosquitto, **reescrevendo automaticamente** os caminhos de persistência e
   de log (que no repositório apontam para caminhos de container Docker) para
   caminhos Windows, e criando as pastas `data\` e `log\`;
5. faz backup de qualquer `mosquitto.conf` que já existisse;
6. imprime os próximos passos.

```powershell
# Instalação completa (como Administrador)
.\scripts\install-windows.ps1

# Só reaplicar a configuração do broker, sem mexer nos pacotes
.\scripts\install-windows.ps1 -SkipMosquitto -SkipInflux -Force
```

Parâmetros: `-SkipMosquitto`, `-SkipInflux`, `-SkipConfig`, `-Force`.

> **Importante:** depois que o `winget` instala algo, **feche e reabra o
> PowerShell**. O `PATH` da janela atual não enxerga o que acabou de ser
> instalado.

---

### `setup-influx.ps1`

**Provisiona o InfluxDB** conforme `docs/CONTRACT.md` seção 4:

- org `eyewatcher`
- bucket `rack_metrics` com retenção **30d**
- um token com permissão de **leitura e escrita** apenas nesse bucket
- grava `backend\.env` com `INFLUX_TOKEN`, as variáveis do MQTT e os limiares
  (`TEMP_WARN`, `TEMP_CRIT`, `HUM_MIN_WARN`, ...)

```powershell
.\scripts\setup-influx.ps1
```

- Se o **InfluxDB não estiver rodando**, o script para com a instrução de subir
  (`influxd` ou `.\scripts\start-all.ps1`).
- Se a instância ainda for virgem, ele chama `influx setup` e **você digita a
  senha do administrador** — o script nunca recebe a senha por parâmetro.
- Se o **CLI `influx` não existir**, ele imprime o passo a passo completo para
  fazer o setup pela interface web em <http://localhost:8086>, incluindo o
  conteúdo exato que o `backend\.env` precisa ter.
- Se `backend\.env` **já existir**, o script **avisa e pede confirmação** antes
  de sobrescrever — e cria um backup com data/hora de qualquer forma.

Parâmetros: `-InfluxUrl`, `-Username`, `-TokenDescription`, `-Force`.

> O token aparece **uma única vez** na saída do script. Ele fica gravado no
> `backend\.env`, mas anote-o se for usar em outro lugar.

---

### `start-all.ps1`

**Sobe a stack completa**, cada componente em sua própria janela, esperando
cada porta ficar disponível antes de passar para o próximo:

| Ordem | Componente | Porta | Como é iniciado |
|---|---|---|---|
| 1 | Mosquitto | 1883 / 9001 | serviço do Windows, se existir; senão `mosquitto.exe -c ... -v` |
| 2 | InfluxDB | 8086 | `influxd` |
| 3 | Backend | 8000 | `backend\.venv\Scripts\python.exe -m uvicorn app.main:app --reload` |
| 4 | Frontend | 5173 | `npm run dev` dentro de `frontend\` |

```powershell
.\scripts\start-all.ps1

# Só a infraestrutura (útil quando você vai rodar o backend no debugger da IDE)
.\scripts\start-all.ps1 -SkipBackend -SkipFrontend

# Se o módulo da app FastAPI tiver outro caminho
.\scripts\start-all.ps1 -BackendApp pacote.modulo:app
```

Ele **avisa claramente** quando falta alguma dependência, em vez de falhar em
silêncio:

- Mosquitto não instalado → manda rodar o `install-windows.ps1`
- `influxd` fora do PATH → manda rodar o `install-windows.ps1`
- `backend\.venv` inexistente → mostra os comandos de `python -m venv` e `pip install`
- `backend\.env` inexistente → manda rodar o `setup-influx.ps1`
- `frontend\node_modules` inexistente → manda rodar `npm install`
- porta que não abre no tempo → manda olhar a janela daquele componente

Se alguma porta já estiver ocupada, o componente é considerado "já no ar" e
reaproveitado (não sobe duplicado).

No fim imprime um resumo com o estado de cada porta e os endereços úteis
(dashboard, `/docs`, `/api/health`, UI do InfluxDB).

Parâmetros: `-SkipMosquitto`, `-SkipInflux`, `-SkipBackend`, `-SkipFrontend`,
`-TimeoutSeconds`, `-BackendApp`.

> Os PIDs iniciados ficam em `scripts\.eyewatcher-run.json`, que é o que o
> `stop-all.ps1` lê. **Não versione esse arquivo.**

---

### `stop-all.ps1`

**Derruba o que o `start-all.ps1` subiu.** Encerra também os processos
**filhos** — o `npm run dev`, por exemplo, cria um processo `node` separado que
continuaria segurando a porta 5173.

```powershell
.\scripts\stop-all.ps1

# Quando o arquivo de estado sumiu ou está desatualizado:
.\scripts\stop-all.ps1 -ByPort

# Mantendo o banco de pé (ele demora para subir)
.\scripts\stop-all.ps1 -KeepInflux
```

O modo `-ByPort` ignora o arquivo de estado e descobre quem está ocupando as
portas 1883, 9001, 8086, 8000 e 5173 (via `Get-NetTCPConnection`, com `netstat`
como plano B). No fim, confere e lista o estado de cada porta.

Parâmetros: `-ByPort`, `-KeepInflux`, `-KeepMosquitto`.

---

### `test-mqtt.ps1`

**Prova que o broker funciona ponta a ponta** — a ferramenta mais útil na hora
da apresentação, porque separa "o broker está quebrado" de "o firmware/backend
está quebrado".

O que ele faz:

1. confere que a porta 1883 responde;
2. sobe um `mosquitto_sub` assinando `eyewatcher/rack01/telemetry` com QoS 1;
3. publica com `mosquitto_pub` um JSON **válido conforme o contrato**
   (`device_id`, `rack_id`, `location`, `temperature`, `humidity`, `heat_index`,
   `status`, `uptime_s`, `seq` — e **sem** timestamp, que é carimbado pelo
   backend);
4. confere que a mensagem voltou, que o tópico está certo, que todos os campos
   obrigatórios estão presentes e que o `seq` bate com o que foi enviado.

```powershell
.\scripts\test-mqtt.ps1

# Forçar um cenário crítico para ver o alerta no dashboard
.\scripts\test-mqtt.ps1 -Temperature 38.7 -Humidity 18.0

# Outro rack
.\scripts\test-mqtt.ps1 -RackId rack02

# Se você tiver desligado o allow_anonymous do broker
.\scripts\test-mqtt.ps1 -Username eyewatcher -Password <senha>
```

O `status` do payload é calculado com os **mesmos limiares do contrato**
(seção 3: status final = o pior entre temperatura e umidade), então o backend
deve chegar ao mesmo resultado ao revalidar.

Parâmetros: `-RackId`, `-BrokerHost`, `-Port`, `-Temperature`, `-Humidity`,
`-Username`, `-Password`, `-IncludeStatus`, `-TimeoutSeconds`.

> `-IncludeStatus` publica também `eyewatcher/<rack>/status` = `online` **com
> retain**, imitando o LWT do ESP32. Fica desligado por padrão porque mensagem
> retida permanece no broker até ser sobrescrita.

---

## Caminho alternativo: Docker

Se você conseguir instalar o Docker Desktop, dá para pular o
`install-windows.ps1` e o `setup-influx.ps1`:

```powershell
Copy-Item infra\.env.example infra\.env
# edite infra\.env: troque a senha e o token
cd infra
docker compose up -d
docker compose ps          # espere os dois ficarem "healthy"
```

Depois copie o `INFLUXDB_ADMIN_TOKEN` do `infra\.env` para `INFLUX_TOKEN` no
`backend\.env`, e suba só a aplicação:

```powershell
.\scripts\start-all.ps1 -SkipMosquitto -SkipInflux
```

---

## Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| "a execução de scripts foi desabilitada" | política de execução do PowerShell | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| `mosquitto`/`influxd` "não reconhecido" logo após instalar | o `PATH` da janela atual está velho | feche e reabra o PowerShell |
| Porta 9001 fechada, 1883 aberta | o broker está usando outro `mosquitto.conf` | `.\scripts\install-windows.ps1 -SkipMosquitto -SkipInflux -Force` e `Restart-Service mosquitto` |
| `start-all.ps1` não consegue iniciar o serviço | falta de privilégio | rode o PowerShell como Administrador |
| Backend sobe mas `/api/health` acusa influx fora | `INFLUX_TOKEN` inválido ou ausente | `.\scripts\setup-influx.ps1` |
| Porta 5173 continua ocupada após o `stop-all` | processo `node` órfão | `.\scripts\stop-all.ps1 -ByPort` |
| `test-mqtt.ps1` publica mas nada volta | ACL/autenticação no broker | veja `infra/mosquitto/config/README.md` |

---

## Portas usadas (docs/CONTRACT.md seção 7)

| Serviço | Porta |
|---|---|
| Mosquitto TCP | 1883 |
| Mosquitto WebSocket | 9001 |
| InfluxDB | 8086 |
| Backend FastAPI | 8000 |
| Frontend Vite | 5173 |
