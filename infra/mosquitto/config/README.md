# Mosquitto — configuração do eyeWatcher

Esta pasta contém o `mosquitto.conf` usado pelos dois caminhos de execução do projeto:

| Caminho | Como o arquivo é usado |
|---|---|
| Docker (`infra/docker-compose.yml`) | montado em `/mosquitto/config/mosquitto.conf` |
| Windows nativo (`scripts/install-windows.ps1`) | copiado para o diretório de instalação, com os caminhos de `persistence_location` e `log_dest file` reescritos automaticamente para caminhos Windows |

Portas (conforme `docs/CONTRACT.md`):

- **1883** — MQTT sobre TCP (ESP32 e backend Python)
- **9001** — MQTT sobre WebSocket (depuração pelo navegador)

---

## Por que `allow_anonymous true`?

O `mosquitto.conf` deste repositório libera acesso anônimo. Isso é uma decisão
consciente **de ambiente de laboratório**:

- o broker roda em `localhost`, na máquina do desenvolvedor;
- o "ESP32" é um simulador no Wokwi, sem gestão de segredos;
- o objetivo é a apresentação acadêmica, não um deployment real.

**Em produção isso não se sustenta.** Sem autenticação, qualquer um na mesma
rede pode publicar telemetria falsa em `eyewatcher/rack01/telemetry` (poluindo o
histórico e disparando alertas falsos) ou assinar os tópicos e ler os dados do
rack. As instruções abaixo mostram como fechar isso.

---

## Como endurecer: usuário e senha com `mosquitto_passwd`

### 1. Gerar o arquivo de senhas

O utilitário `mosquitto_passwd` vem junto com a instalação do Mosquitto.

**Windows (nativo)** — abra um PowerShell **como Administrador**:

```powershell
cd "C:\Program Files\mosquitto"

# -c CRIA um arquivo novo (apaga o anterior!). Use só no primeiro usuário.
.\mosquitto_passwd.exe -c .\config\passwd eyewatcher

# Para ADICIONAR outros usuários depois, NÃO use -c:
.\mosquitto_passwd.exe .\config\passwd backend
.\mosquitto_passwd.exe .\config\passwd esp32
```

O comando pede a senha duas vezes e grava o hash no arquivo — a senha em texto
puro nunca é armazenada.

**Docker** — gere o arquivo dentro do container e ele fica na pasta do repositório:

```bash
docker compose exec mosquitto mosquitto_passwd -c /mosquitto/config/passwd eyewatcher
```

> Se o container ainda não estiver rodando, dá para usar um container efêmero:
> ```bash
> docker run --rm -it -v "${PWD}/mosquitto/config:/mosquitto/config" \
>   eclipse-mosquitto:2 mosquitto_passwd -c /mosquitto/config/passwd eyewatcher
> ```

### 2. Ativar no `mosquitto.conf`

Edite `mosquitto.conf` e troque:

```conf
allow_anonymous true
```

por:

```conf
allow_anonymous false
password_file /mosquitto/config/passwd
```

No Windows nativo, o caminho é o do diretório de instalação:

```conf
allow_anonymous false
password_file C:\Program Files\mosquitto\config\passwd
```

### 3. Reiniciar o broker

```powershell
# Windows (serviço)
Restart-Service mosquitto

# Docker
docker compose restart mosquitto
```

### 4. Atualizar os clientes

Depois de fechar o broker, **todos** os clientes precisam autenticar:

- **Firmware (ESP32):** `mqttClient.connect(clientId, MQTT_USER, MQTT_PASS)`
- **Backend (paho-mqtt):** `client.username_pw_set(user, password)` antes do `connect()`
- **Scripts de teste:** `mosquitto_pub -u eyewatcher -P <senha> ...`

---

## Opcional: ACLs por tópico

Para ir além de "autenticado pode tudo", crie um `acl` file restringindo cada
identidade ao que ela realmente precisa:

```conf
# infra/mosquitto/config/acl

# O dispositivo só publica nos seus próprios tópicos
user esp32
topic write eyewatcher/rack01/telemetry
topic write eyewatcher/rack01/status

# O backend só lê
user backend
topic read eyewatcher/+/telemetry
topic read eyewatcher/+/status
```

E referencie no `mosquitto.conf`:

```conf
acl_file /mosquitto/config/acl
```

---

## Verificando que funcionou

Com o broker no ar, use o script do repositório:

```powershell
.\scripts\test-mqtt.ps1
```

Ele publica uma telemetria de teste em `eyewatcher/rack01/telemetry` e assina o
tópico para provar que a mensagem trafegou ponta a ponta. Se você tiver ativado
autenticação, rode com as credenciais:

```powershell
.\scripts\test-mqtt.ps1 -Username eyewatcher -Password <senha>
```
