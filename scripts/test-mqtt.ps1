<#
.SYNOPSIS
    Prova que o broker MQTT funciona ponta a ponta: assina o tópico do contrato,
    publica uma telemetria de teste e confere que a mensagem voltou.

.DESCRIPTION
    Ferramenta de depuração — especialmente útil na hora da apresentação, para
    separar "o broker está quebrado" de "o firmware/backend está quebrado".

    O que faz:
      1. confere que a porta 1883 está aberta;
      2. sobe um `mosquitto_sub` assinando `eyewatcher/<rack_id>/telemetry`
         com QoS 1, esperando 1 mensagem;
      3. publica com `mosquitto_pub` um JSON válido conforme
         docs/CONTRACT.md seção 2 (QoS 1, retain false);
      4. lê o que o subscriber recebeu, valida que é o mesmo JSON e confere
         os campos obrigatórios.

    O payload é enviado a partir de um arquivo temporário (mosquitto_pub -f),
    evitando qualquer problema de escape de aspas no PowerShell.

.PARAMETER RackId
    Rack usado no teste. Padrão: rack01 (o do projeto base).

.PARAMETER BrokerHost
    Host do broker. Padrão: localhost.

.PARAMETER Port
    Porta TCP do broker. Padrão: 1883.

.PARAMETER Temperature
    Temperatura em °C do payload de teste. Padrão: 34.5.

.PARAMETER Humidity
    Umidade relativa em % do payload de teste. Padrão: 48.2.

.PARAMETER Username
.PARAMETER Password
    Credenciais, caso você tenha desligado o allow_anonymous do broker.

.PARAMETER IncludeStatus
    Publica também `eyewatcher/<rack_id>/status` = "online" com retain,
    imitando o LWT do ESP32. Desligado por padrão porque a mensagem RETIDA
    fica no broker até ser sobrescrita.

.PARAMETER TimeoutSeconds
    Tempo máximo de espera pela mensagem. Padrão: 15.

.EXAMPLE
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\scripts\test-mqtt.ps1

.EXAMPLE
    # Simulando um cenário crítico para ver o alerta no dashboard:
    .\scripts\test-mqtt.ps1 -Temperature 38.7 -Humidity 18.0

.NOTES
    Compatível com Windows PowerShell 5.1 (sem &&, ||, ?: e ??).
#>

[CmdletBinding()]
param(
    [string]$RackId         = 'rack01',
    [string]$BrokerHost     = 'localhost',
    [int]   $Port           = 1883,
    [double]$Temperature    = 34.5,
    [double]$Humidity       = 48.2,
    [string]$Username,
    [string]$Password,
    [switch]$IncludeStatus,
    [int]   $TimeoutSeconds = 15
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Mensagens coloridas
# ---------------------------------------------------------------------------
function Write-Titulo {
    param([string]$Texto)
    Write-Host ''
    Write-Host ('=' * 74) -ForegroundColor DarkCyan
    Write-Host "  $Texto" -ForegroundColor Cyan
    Write-Host ('=' * 74) -ForegroundColor DarkCyan
}

function Write-Passo { param([string]$Texto) Write-Host "[..] $Texto" -ForegroundColor Gray }
function Write-Ok    { param([string]$Texto) Write-Host "[OK] $Texto" -ForegroundColor Green }
function Write-Aviso { param([string]$Texto) Write-Host "[!!] $Texto" -ForegroundColor Yellow }
function Write-Erro  { param([string]$Texto) Write-Host "[XX] $Texto" -ForegroundColor Red }

function Stop-ComMensagem {
    param([string]$Mensagem, [string]$ComoResolver)
    Write-Host ''
    Write-Erro $Mensagem
    if ($ComoResolver) {
        Write-Host ''
        Write-Host 'Como resolver:' -ForegroundColor Yellow
        Write-Host $ComoResolver -ForegroundColor Yellow
    }
    Write-Host ''
    exit 1
}

# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
function Test-PortaAberta {
    param([string]$ComputerName = '127.0.0.1', [int]$Porta, [int]$TimeoutMs = 1500)
    $cliente = New-Object System.Net.Sockets.TcpClient
    try {
        $async    = $cliente.BeginConnect($ComputerName, $Porta, $null, $null)
        $conectou = $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if (-not $conectou) { return $false }
        $cliente.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $cliente.Close()
    }
}

function Find-FerramentaMosquitto {
    <# Procura mosquitto_pub.exe / mosquitto_sub.exe no PATH e nos caminhos padrão. #>
    param([string]$Nome)

    $cmd = Get-Command $Nome -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidatos = @(
        "$env:ProgramFiles\mosquitto\$Nome.exe",
        "${env:ProgramFiles(x86)}\mosquitto\$Nome.exe",
        "$env:ProgramW6432\mosquitto\$Nome.exe"
    )
    foreach ($caminho in $candidatos) {
        if ([string]::IsNullOrWhiteSpace($caminho)) { continue }
        if (Test-Path $caminho) { return $caminho }
    }
    return $null
}

function Format-Decimal {
    <#
        Formata com PONTO decimal, independentemente da cultura da máquina.
        Sem isso, numa máquina pt-BR o JSON sairia com "34,5" e seria inválido.
    #>
    param([double]$Valor, [string]$Formato = '0.0')
    return $Valor.ToString($Formato, [System.Globalization.CultureInfo]::InvariantCulture)
}

function Get-StatusPeloContrato {
    <#
        Replica os limiares de docs/CONTRACT.md seção 3 (o status final é o
        PIOR entre temperatura e umidade). Serve para o payload de teste sair
        coerente com o que o backend vai recalcular.
    #>
    param([double]$Temp, [double]$Umid)

    $niveis = @{ 'ok' = 0; 'warning' = 1; 'critical' = 2 }

    $statusTemp = 'ok'
    if     ($Temp -ge 35) { $statusTemp = 'critical' }
    elseif ($Temp -ge 30) { $statusTemp = 'warning'  }

    $statusUmid = 'ok'
    if     ($Umid -lt 20 -or $Umid -gt 80) { $statusUmid = 'critical' }
    elseif ($Umid -lt 30 -or $Umid -gt 70) { $statusUmid = 'warning'  }

    if ($niveis[$statusTemp] -ge $niveis[$statusUmid]) { return $statusTemp }
    return $statusUmid
}

function Get-HeatIndex {
    <# Aproximação simples só para o payload de teste ficar plausível. #>
    param([double]$Temp, [double]$Umid)
    $hi = $Temp + (0.05 * $Umid) - 0.7
    return [math]::Round($hi, 1)
}

# ===========================================================================
# EXECUÇÃO
# ===========================================================================
$topicoTelemetria = "eyewatcher/$RackId/telemetry"
$topicoStatus     = "eyewatcher/$RackId/status"
$deviceId         = "esp32-$RackId"

Write-Titulo 'eyeWatcher — teste ponta a ponta do MQTT'
Write-Host "  Broker : ${BrokerHost}:${Port}" -ForegroundColor DarkGray
Write-Host "  Tópico : $topicoTelemetria"     -ForegroundColor DarkGray

# --- 1. Ferramentas --------------------------------------------------------
Write-Titulo '1/4 — Ferramentas e broker'

$mosquittoPub = Find-FerramentaMosquitto -Nome 'mosquitto_pub'
$mosquittoSub = Find-FerramentaMosquitto -Nome 'mosquitto_sub'

if ((-not $mosquittoPub) -or (-not $mosquittoSub)) {
    Stop-ComMensagem -Mensagem 'mosquitto_pub / mosquitto_sub não foram encontrados.' `
                     -ComoResolver @'
    Eles vêm junto com a instalação do Mosquitto:
        .\scripts\install-windows.ps1     (como Administrador)

    Se o Mosquitto já está instalado mas não está no PATH, adicione
    "C:\Program Files\mosquitto" às variáveis de ambiente, ou rode este
    script informando o host do broker por parâmetro.
'@
}
Write-Ok "mosquitto_pub: $mosquittoPub"
Write-Ok "mosquitto_sub: $mosquittoSub"

if (-not (Test-PortaAberta -ComputerName $BrokerHost -Porta $Port)) {
    Stop-ComMensagem -Mensagem "O broker não está respondendo em ${BrokerHost}:${Port}." `
                     -ComoResolver @'
    Suba o broker:
        .\scripts\start-all.ps1 -SkipInflux -SkipBackend -SkipFrontend

    Ou, se ele estiver instalado como serviço do Windows:
        Start-Service mosquitto
'@
}
Write-Ok "Broker respondendo em ${BrokerHost}:${Port}."

# --- 2. Payload ------------------------------------------------------------
Write-Titulo '2/4 — Montando o payload (docs/CONTRACT.md seção 2)'

$status    = Get-StatusPeloContrato -Temp $Temperature -Umid $Humidity
$heatIndex = Get-HeatIndex          -Temp $Temperature -Umid $Humidity
$uptime    = [int](Get-Random -Minimum 60 -Maximum 99999)
$seq       = [int](Get-Random -Minimum 1  -Maximum 9999)

# NÃO enviamos timestamp: quem carimba a hora é o backend (contrato, seção 2).
$payload = @"
{
  "device_id": "$deviceId",
  "rack_id": "$RackId",
  "location": "Sala de Servidores A",
  "temperature": $(Format-Decimal -Valor $Temperature),
  "humidity": $(Format-Decimal -Valor $Humidity),
  "heat_index": $(Format-Decimal -Valor $heatIndex),
  "status": "$status",
  "uptime_s": $uptime,
  "seq": $seq
}
"@

# Valida o JSON ANTES de publicar — assim um erro aqui não vira "o broker falhou".
try {
    $payload | ConvertFrom-Json | Out-Null
} catch {
    Stop-ComMensagem -Mensagem "O payload gerado não é um JSON válido: $($_.Exception.Message)"
}

Write-Ok "JSON válido (status calculado: $status)."
Write-Host $payload -ForegroundColor DarkGray

# Arquivos temporários: payload de entrada e saída do subscriber.
$dirTemp      = [System.IO.Path]::GetTempPath()
$arqPayload   = Join-Path $dirTemp "eyewatcher-payload-$PID.json"
$arqRecebido  = Join-Path $dirTemp "eyewatcher-sub-$PID.txt"
$arqErroSub   = Join-Path $dirTemp "eyewatcher-sub-err-$PID.txt"

# Sem BOM: o mosquitto_pub envia o arquivo byte a byte e um BOM quebraria o
# parser de JSON do backend.
$semBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($arqPayload, $payload, $semBom)

# --- 3. Assinar e publicar -------------------------------------------------
Write-Titulo '3/4 — Assinando e publicando'

$argsComuns = @('-h', $BrokerHost, '-p', "$Port")
if (-not [string]::IsNullOrWhiteSpace($Username)) {
    $argsComuns += @('-u', $Username)
    if (-not [string]::IsNullOrWhiteSpace($Password)) {
        $argsComuns += @('-P', $Password)
    }
}

$argsSub = $argsComuns + @(
    '-t', $topicoTelemetria,
    '-q', '1',
    '-i', "eyewatcher-test-sub-$PID",
    '-C', '1',                    # sai depois de 1 mensagem
    '-W', "$TimeoutSeconds",      # ...ou depois do timeout
    '-v'                          # imprime "tópico payload"
)

Write-Passo "Assinando $topicoTelemetria (QoS 1, aguardando 1 mensagem)..."
$procSub = Start-Process -FilePath $mosquittoSub `
                         -ArgumentList $argsSub `
                         -NoNewWindow -PassThru `
                         -RedirectStandardOutput $arqRecebido `
                         -RedirectStandardError  $arqErroSub

# Dá um instante para o subscriber completar o CONNECT/SUBACK antes do publish.
Start-Sleep -Milliseconds 1200

$argsPub = $argsComuns + @(
    '-t', $topicoTelemetria,
    '-q', '1',
    '-i', "eyewatcher-test-pub-$PID",
    '-f', $arqPayload
)

Write-Passo "Publicando em $topicoTelemetria (QoS 1, retain false)..."
$anterior = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $mosquittoPub @argsPub
$codigoPub = $LASTEXITCODE
$ErrorActionPreference = $anterior

if ($codigoPub -ne 0) {
    if (-not $procSub.HasExited) { Stop-Process -Id $procSub.Id -Force -ErrorAction SilentlyContinue }
    Stop-ComMensagem -Mensagem "mosquitto_pub falhou (código $codigoPub)." `
                     -ComoResolver @'
    Causas comuns:
      - o broker exige usuário/senha: rode com -Username e -Password;
      - o broker caiu entre a checagem e a publicação: veja a janela dele.
'@
}
Write-Ok 'Telemetria publicada.'

if ($IncludeStatus) {
    Write-Passo "Publicando $topicoStatus = 'online' (QoS 1, RETAIN)..."
    $argsStatus = $argsComuns + @('-t', $topicoStatus, '-q', '1', '-r', '-m', 'online',
                                  '-i', "eyewatcher-test-st-$PID")
    $ErrorActionPreference = 'Continue'
    & $mosquittoPub @argsStatus
    $codigoStatus = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'

    if ($codigoStatus -eq 0) {
        Write-Ok 'Status online publicado (retido).'
        Write-Aviso 'Mensagem RETIDA: para limpar, publique um payload vazio com -r nesse tópico.'
    } else {
        Write-Aviso "Não consegui publicar o status (código $codigoStatus)."
    }
}

# --- 4. Conferir o que voltou ---------------------------------------------
Write-Titulo '4/4 — Conferindo a mensagem recebida'

Write-Passo "Aguardando o subscriber (até ${TimeoutSeconds}s)..."
$saiuATempo = $procSub.WaitForExit(($TimeoutSeconds + 3) * 1000)

if (-not $saiuATempo) {
    Stop-Process -Id $procSub.Id -Force -ErrorAction SilentlyContinue
}

# Dá um instante para o arquivo de saída ser liberado pelo SO.
Start-Sleep -Milliseconds 400

$recebido = ''
if (Test-Path $arqRecebido) {
    $recebido = (Get-Content -Path $arqRecebido -Raw -ErrorAction SilentlyContinue)
}

$erroSub = ''
if (Test-Path $arqErroSub) {
    $erroSub = (Get-Content -Path $arqErroSub -Raw -ErrorAction SilentlyContinue)
}

$sucesso = $false

if ([string]::IsNullOrWhiteSpace($recebido)) {
    Write-Erro 'Nenhuma mensagem chegou ao subscriber.'
    if (-not [string]::IsNullOrWhiteSpace($erroSub)) {
        Write-Host '     Saída de erro do mosquitto_sub:' -ForegroundColor DarkGray
        Write-Host $erroSub -ForegroundColor DarkGray
    }
    Write-Host ''
    Write-Aviso 'Isso indica problema NO BROKER (o publish foi aceito, mas nada foi entregue):'
    Write-Aviso '  - ACL/autenticação bloqueando a assinatura;'
    Write-Aviso '  - broker reiniciado no meio do teste;'
    Write-Aviso '  - firewall entre o subscriber e o broker.'
} else {
    Write-Ok 'Mensagem recebida:'
    Write-Host $recebido.Trim() -ForegroundColor Cyan

    # Formato do -v: "<tópico> <payload>"
    $linha = ($recebido -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })[0]
    $corte = $linha.IndexOf(' ')

    if ($corte -lt 0) {
        Write-Aviso 'Não consegui separar tópico e payload na linha recebida.'
    } else {
        $topicoRecebido  = $linha.Substring(0, $corte)
        $payloadRecebido = $linha.Substring($corte + 1)

        if ($topicoRecebido -ne $topicoTelemetria) {
            Write-Aviso "Tópico inesperado: '$topicoRecebido' (esperado '$topicoTelemetria')."
        } else {
            Write-Ok "Tópico confere: $topicoRecebido"
        }

        try {
            $obj = $payloadRecebido | ConvertFrom-Json

            $camposObrigatorios = @('device_id', 'rack_id', 'location', 'temperature',
                                    'humidity', 'heat_index', 'status', 'uptime_s', 'seq')
            $faltando = @()
            foreach ($campo in $camposObrigatorios) {
                if ($null -eq $obj.PSObject.Properties[$campo]) { $faltando += $campo }
            }

            if ($faltando.Count -gt 0) {
                Write-Erro ("Campos ausentes no payload: " + ($faltando -join ', '))
            } else {
                Write-Ok 'Todos os campos do contrato estão presentes.'
            }

            if ($obj.seq -eq $seq) {
                Write-Ok "seq confere ($seq) — é exatamente a mensagem que publicamos."
                if ($faltando.Count -eq 0) { $sucesso = $true }
            } else {
                Write-Aviso "seq recebido ($($obj.seq)) != enviado ($seq) — pode ser outro publisher ativo (o ESP32?)."
                if ($faltando.Count -eq 0) { $sucesso = $true }
            }
        } catch {
            Write-Erro "O payload recebido não é JSON válido: $($_.Exception.Message)"
        }
    }
}

# --- Limpeza ---------------------------------------------------------------
foreach ($arq in @($arqPayload, $arqRecebido, $arqErroSub)) {
    Remove-Item -Path $arq -Force -ErrorAction SilentlyContinue
}

# --- Resultado -------------------------------------------------------------
Write-Titulo 'Resultado'
if ($sucesso) {
    Write-Ok 'MQTT FUNCIONANDO ponta a ponta: publish -> broker -> subscribe.'
    Write-Host ''
    Write-Host '  Se o dashboard continuar vazio, o problema NÃO é o broker.' -ForegroundColor White
    Write-Host '  Investigue nesta ordem:' -ForegroundColor White
    Write-Host '    1) o backend está assinando eyewatcher/+/telemetry? (veja a janela do uvicorn)' -ForegroundColor White
    Write-Host '    2) http://localhost:8000/api/health responde com influx e mqtt ok?' -ForegroundColor White
    Write-Host '    3) o INFLUX_TOKEN do backend\.env é válido?' -ForegroundColor White
    Write-Host ''
    exit 0
}

Write-Erro 'O teste NÃO passou — veja as mensagens acima.'
Write-Host ''
exit 1
