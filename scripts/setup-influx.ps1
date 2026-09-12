<#
.SYNOPSIS
    Provisiona o InfluxDB 2.x para o eyeWatcher: org `eyewatcher`, bucket
    `rack_metrics` (retenção 30d) e um token de leitura/escrita, gravado em
    backend/.env.

.DESCRIPTION
    Conforme docs/CONTRACT.md seção 4. O script é idempotente: se a org ou o
    bucket já existirem, ele reaproveita em vez de falhar.

    Passos:
      1. localiza o CLI `influx` (se não existir, explica o setup pela UI);
      2. confere se o InfluxDB está respondendo em http://localhost:8086;
      3. roda o `influx setup` inicial se a instância ainda estiver virgem
         (a senha é digitada por você, o script nunca a recebe por parâmetro);
      4. garante a org `eyewatcher` e o bucket `rack_metrics` com 30d;
      5. cria um token com permissão de leitura E escrita apenas nesse bucket;
      6. grava/atualiza backend/.env — avisando antes de sobrescrever.

.PARAMETER InfluxUrl
    URL do InfluxDB. Padrão: http://localhost:8086 (contrato).

.PARAMETER Username
    Usuário administrador criado no setup inicial. Padrão: eyewatcher.

.PARAMETER TokenDescription
    Descrição do token gerado. Padrão: eyewatcher-backend.

.PARAMETER Force
    Sobrescreve backend/.env sem perguntar (um backup é criado mesmo assim).

.EXAMPLE
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\scripts\setup-influx.ps1

.NOTES
    Compatível com Windows PowerShell 5.1 (sem &&, ||, ?: e ??).
#>

[CmdletBinding()]
param(
    [string]$InfluxUrl        = 'http://localhost:8086',
    [string]$Username         = 'eyewatcher',
    [string]$TokenDescription = 'eyewatcher-backend',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

# Valores fixados pelo contrato — não mude sem mudar docs/CONTRACT.md.
$ORG       = 'eyewatcher'
$BUCKET    = 'rack_metrics'
$RETENCAO  = '30d'

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
    param([string]$ComputerName = 'localhost', [int]$Porta, [int]$TimeoutMs = 1500)
    $cliente = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $cliente.BeginConnect($ComputerName, $Porta, $null, $null)
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

function Invoke-Influx {
    <#
        Executa o CLI influx e devolve { ExitCode, Output }.
        Usamos o código de saída (e não exceções) para controlar o fluxo,
        porque o CLI escreve avisos benignos no stderr.
    #>
    param([string[]]$Argumentos)

    $anterior = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $saida  = & influx @Argumentos 2>&1 | Out-String
    $codigo = $LASTEXITCODE
    $ErrorActionPreference = $anterior

    return [pscustomobject]@{ ExitCode = $codigo; Output = $saida }
}

function ConvertFrom-InfluxJson {
    param([string]$Texto)
    # O CLI às vezes imprime avisos antes do JSON; pegamos do primeiro
    # '[' ou '{' em diante.
    $inicio = $Texto.IndexOfAny([char[]]@('[', '{'))
    if ($inicio -lt 0) { return $null }
    try {
        return ($Texto.Substring($inicio) | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Show-InstrucoesUI {
    Write-Host @"

  Faça o setup manualmente pela interface web:

    1) Garanta que o InfluxDB está rodando:
           influxd
       (ou use .\scripts\start-all.ps1)

    2) Abra no navegador:
           $InfluxUrl

    3) Clique em "Get Started" e preencha EXATAMENTE:
           Username         : $Username
           Password         : (escolha uma, mínimo 8 caracteres)
           Organization Name: $ORG
           Bucket Name      : $BUCKET

    4) Em Load Data > Buckets > $BUCKET > Settings, ajuste
       a retenção (Delete Data) para 30 days.

    5) Em Load Data > API Tokens > Generate API Token >
       Custom API Token, marque READ e WRITE no bucket "$BUCKET",
       descreva como "$TokenDescription" e COPIE o token
       (ele só aparece uma vez).

    6) Crie o arquivo backend\.env com:

           INFLUX_URL=$InfluxUrl
           INFLUX_ORG=$ORG
           INFLUX_BUCKET=$BUCKET
           INFLUX_TOKEN=<cole o token aqui>
           MQTT_HOST=localhost
           MQTT_PORT=1883
           TEMP_WARN=30
           TEMP_CRIT=35
           HUM_MIN_WARN=30
           HUM_MIN_CRIT=20
           HUM_MAX_WARN=70
           HUM_MAX_CRIT=80

"@ -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Escrita do backend/.env
# ---------------------------------------------------------------------------
function Write-BackendEnv {
    param(
        [string]$CaminhoEnv,
        [string]$Token,
        [switch]$Sobrescrever
    )

    if (Test-Path $CaminhoEnv) {
        Write-Host ''
        Write-Aviso "O arquivo já existe: $CaminhoEnv"
        Write-Aviso 'Ele será SOBRESCRITO (um backup com data/hora será criado antes).'

        if (-not $Sobrescrever) {
            $resposta = Read-Host '     Continuar? [s/N]'
            if ($resposta -notmatch '^[sSyY]$') {
                Write-Host ''
                Write-Aviso 'backend\.env NÃO foi alterado. Guarde o token manualmente:'
                Write-Host  "     INFLUX_TOKEN=$Token" -ForegroundColor Cyan
                Write-Host ''
                return $false
            }
        }

        $carimbo = Get-Date -Format 'yyyyMMdd-HHmmss'
        $backup  = "$CaminhoEnv.bak-$carimbo"
        Copy-Item -Path $CaminhoEnv -Destination $backup -Force
        Write-Ok "Backup criado: $backup"
    }

    $dirEnv = Split-Path -Parent $CaminhoEnv
    if (-not (Test-Path $dirEnv)) {
        New-Item -ItemType Directory -Path $dirEnv -Force | Out-Null
    }

    $conteudo = @"
# Gerado por scripts\setup-influx.ps1 em $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')
# Valores conforme docs/CONTRACT.md. NÃO versione este arquivo.

# --- InfluxDB 2.x (contrato, seção 4) ---
INFLUX_URL=$InfluxUrl
INFLUX_ORG=$ORG
INFLUX_BUCKET=$BUCKET
INFLUX_TOKEN=$Token

# --- MQTT (contrato, seção 2) ---
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_CLIENT_ID=eyewatcher-backend
MQTT_TOPIC_TELEMETRY=eyewatcher/+/telemetry
MQTT_TOPIC_STATUS=eyewatcher/+/status

# --- Limiares (contrato, seção 3) ---
TEMP_WARN=30
TEMP_CRIT=35
HUM_MIN_WARN=30
HUM_MIN_CRIT=20
HUM_MAX_WARN=70
HUM_MAX_CRIT=80

# --- API HTTP (contrato, seção 5) ---
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:5173
"@

    # UTF-8 SEM BOM: um BOM faria o python-dotenv ler a primeira chave como
    # "﻿INFLUX_URL" e o backend não acharia a variável.
    $semBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($CaminhoEnv, $conteudo, $semBom)
    Write-Ok "backend\.env gravado: $CaminhoEnv"
    return $true
}

# ===========================================================================
# EXECUÇÃO
# ===========================================================================
$raizRepo   = Split-Path -Parent $PSScriptRoot
$caminhoEnv = Join-Path $raizRepo 'backend\.env'

Write-Titulo 'eyeWatcher — provisionamento do InfluxDB 2.x'
Write-Host "  URL     : $InfluxUrl"  -ForegroundColor DarkGray
Write-Host "  Org     : $ORG"        -ForegroundColor DarkGray
Write-Host "  Bucket  : $BUCKET ($RETENCAO)" -ForegroundColor DarkGray

# --- 1. CLI influx ---------------------------------------------------------
Write-Titulo '1/5 — Verificando o CLI influx'
$cliInflux = Get-Command 'influx' -ErrorAction SilentlyContinue
if ($null -eq $cliInflux) {
    Write-Erro 'O CLI `influx` não foi encontrado no PATH.'
    Write-Aviso 'Sem ele não dá para provisionar por linha de comando.'
    Write-Host ''
    Write-Host '  Opção A — instalar o CLI:' -ForegroundColor Yellow
    Write-Host '      .\scripts\install-windows.ps1     (como Administrador)' -ForegroundColor Yellow
    Write-Host '      ou baixe em https://docs.influxdata.com/influxdb/v2/tools/influx-cli/' -ForegroundColor Yellow
    Write-Host ''
    Write-Host '  Opção B — fazer o setup pela interface web:' -ForegroundColor Yellow
    Show-InstrucoesUI
    exit 1
}
Write-Ok "CLI encontrado: $($cliInflux.Source)"

# --- 2. Servidor no ar -----------------------------------------------------
Write-Titulo '2/5 — Verificando se o InfluxDB está no ar'
$uri = [Uri]$InfluxUrl
if (-not (Test-PortaAberta -ComputerName $uri.Host -Porta $uri.Port)) {
    Stop-ComMensagem -Mensagem "Nada respondendo em $InfluxUrl (porta $($uri.Port) fechada)." `
                     -ComoResolver @'
    Suba o servidor em outra janela:
        influxd

    Ou use o script que sobe tudo:
        .\scripts\start-all.ps1

    Depois rode este script novamente.
'@
}

$ping = Invoke-Influx @('ping', '--host', $InfluxUrl)
if ($ping.ExitCode -ne 0) {
    Write-Aviso 'A porta está aberta, mas o comando "influx ping" falhou:'
    Write-Host $ping.Output -ForegroundColor DarkGray
} else {
    Write-Ok 'InfluxDB respondendo.'
}

# --- 3. Setup inicial ------------------------------------------------------
Write-Titulo '3/5 — Setup inicial (usuário administrador)'
$orgs = Invoke-Influx @('org', 'list', '--host', $InfluxUrl, '--json')

if ($orgs.ExitCode -ne 0) {
    Write-Passo 'A instância parece não estar configurada (ou não há credenciais salvas).'
    Write-Host ''
    Write-Host '  Vou chamar `influx setup`. Você vai digitar a SENHA do usuário' -ForegroundColor Yellow
    Write-Host "  administrador `"$Username`" (mínimo 8 caracteres)." -ForegroundColor Yellow
    Write-Host '  A senha é lida diretamente pelo CLI — este script não a armazena.' -ForegroundColor Yellow
    Write-Host ''

    $anterior = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    influx setup --host $InfluxUrl `
                 --username $Username `
                 --org $ORG `
                 --bucket $BUCKET `
                 --retention $RETENCAO `
                 --name eyewatcher `
                 --force | Out-Host
    $codigoSetup = $LASTEXITCODE
    $ErrorActionPreference = $anterior

    if ($codigoSetup -ne 0) {
        Write-Aviso 'O `influx setup` não concluiu.'
        Write-Aviso 'Se a instância JÁ tinha sido configurada antes, você precisa apenas'
        Write-Aviso 'apontar o CLI para ela com um token de admin, por exemplo:'
        Write-Host '      influx config create --config-name eyewatcher \' -ForegroundColor Yellow
        Write-Host "        --host-url $InfluxUrl --org $ORG --token <TOKEN_ADMIN> --active" -ForegroundColor Yellow
        Show-InstrucoesUI
        exit 1
    }
    Write-Ok 'Setup inicial concluído.'

    $orgs = Invoke-Influx @('org', 'list', '--host', $InfluxUrl, '--json')
} else {
    Write-Ok 'Instância já configurada e CLI autenticado.'
}

# --- 4. Org e bucket -------------------------------------------------------
Write-Titulo '4/5 — Garantindo org e bucket'

$listaOrgs = ConvertFrom-InfluxJson $orgs.Output
$orgExiste = $false
foreach ($o in $listaOrgs) {
    if ($o.name -eq $ORG) { $orgExiste = $true }
}

if ($orgExiste) {
    Write-Ok "Org '$ORG' já existe."
} else {
    Write-Passo "Criando a org '$ORG'..."
    $criaOrg = Invoke-Influx @('org', 'create', '--host', $InfluxUrl, '--name', $ORG)
    if ($criaOrg.ExitCode -ne 0) {
        Write-Erro "Falha ao criar a org '$ORG':"
        Write-Host $criaOrg.Output -ForegroundColor DarkGray
        exit 1
    }
    Write-Ok "Org '$ORG' criada."
}

$buckets     = Invoke-Influx @('bucket', 'list', '--host', $InfluxUrl, '--org', $ORG, '--json')
$listaBuckets = ConvertFrom-InfluxJson $buckets.Output
$bucketId    = $null
foreach ($b in $listaBuckets) {
    if ($b.name -eq $BUCKET) { $bucketId = $b.id }
}

if ($bucketId) {
    Write-Ok "Bucket '$BUCKET' já existe (id: $bucketId)."
    Write-Passo "Reaplicando a retenção de $RETENCAO..."
    $upd = Invoke-Influx @('bucket', 'update', '--host', $InfluxUrl, '--id', $bucketId, '--retention', $RETENCAO)
    if ($upd.ExitCode -eq 0) {
        Write-Ok "Retenção do bucket ajustada para $RETENCAO."
    } else {
        Write-Aviso "Não consegui ajustar a retenção automaticamente (ajuste na UI se necessário)."
    }
} else {
    Write-Passo "Criando o bucket '$BUCKET' com retenção de $RETENCAO..."
    $criaBucket = Invoke-Influx @('bucket', 'create', '--host', $InfluxUrl, '--org', $ORG,
                                  '--name', $BUCKET, '--retention', $RETENCAO, '--json')
    if ($criaBucket.ExitCode -ne 0) {
        Write-Erro "Falha ao criar o bucket '$BUCKET':"
        Write-Host $criaBucket.Output -ForegroundColor DarkGray
        exit 1
    }
    $novo = ConvertFrom-InfluxJson $criaBucket.Output
    if ($novo) { $bucketId = $novo.id }
    Write-Ok "Bucket '$BUCKET' criado (id: $bucketId)."
}

if (-not $bucketId) {
    Stop-ComMensagem -Mensagem 'Não consegui descobrir o ID do bucket — sem ele não dá para criar um token com escopo.' `
                     -ComoResolver '    Verifique com: influx bucket list --org eyewatcher'
}

# --- 5. Token + backend/.env ----------------------------------------------
Write-Titulo '5/5 — Criando o token de leitura/escrita'
Write-Passo "Gerando token com READ + WRITE no bucket '$BUCKET'..."

$auth = Invoke-Influx @('auth', 'create', '--host', $InfluxUrl, '--org', $ORG,
                        '--description', $TokenDescription,
                        '--read-bucket',  $bucketId,
                        '--write-bucket', $bucketId,
                        '--json')

if ($auth.ExitCode -ne 0) {
    Write-Erro 'Falha ao criar o token:'
    Write-Host $auth.Output -ForegroundColor DarkGray
    Show-InstrucoesUI
    exit 1
}

$dadosAuth = ConvertFrom-InfluxJson $auth.Output
$token = $null
if ($dadosAuth) { $token = $dadosAuth.token }

if ([string]::IsNullOrWhiteSpace($token)) {
    Write-Erro 'O token foi criado, mas não consegui extraí-lo da resposta do CLI.'
    Write-Host $auth.Output -ForegroundColor DarkGray
    Write-Aviso 'Copie o token manualmente para backend\.env como INFLUX_TOKEN.'
    exit 1
}

Write-Ok 'Token criado.'
Write-Host "     $token" -ForegroundColor Cyan
Write-Aviso 'Guarde este valor: o InfluxDB não mostra o token de novo depois.'

Write-BackendEnv -CaminhoEnv $caminhoEnv -Token $token -Sobrescrever:$Force | Out-Null

# ---------------------------------------------------------------------------
Write-Titulo 'Pronto'
Write-Host @"
  Org    : $ORG
  Bucket : $BUCKET (retenção $RETENCAO)
  Env    : $caminhoEnv

  Próximos passos:
      .\scripts\start-all.ps1     # sobe broker, banco, backend e frontend
      .\scripts\test-mqtt.ps1     # prova que o MQTT funciona ponta a ponta

  UI do InfluxDB: $InfluxUrl
"@ -ForegroundColor White
Write-Host ''
