<#
.SYNOPSIS
    Instala as dependências de infraestrutura do eyeWatcher no Windows
    (Mosquitto + InfluxDB 2.x) sem usar Docker.

.DESCRIPTION
    Este é o CAMINHO PRINCIPAL do projeto: a máquina de desenvolvimento não tem
    Docker instalado. O script:

      1. verifica se está rodando como Administrador;
      2. verifica se o winget está disponível;
      3. instala o Mosquitto (broker MQTT), o servidor InfluxDB 2.x e o CLI
         `influx` — pulando o que já estiver instalado (é idempotente);
      4. copia infra/mosquitto/config/mosquitto.conf para o diretório de
         instalação do Mosquitto, reescrevendo os caminhos de persistência e de
         log (que no repositório são caminhos de container Docker) para
         caminhos Windows;
      5. imprime os próximos passos.

    Se algum pacote não estiver disponível no winget, o script NÃO falha em
    silêncio: ele mostra o link de download manual e segue adiante.

.PARAMETER SkipMosquitto
    Não instala o Mosquitto (só reaproveita o que já existe).

.PARAMETER SkipInflux
    Não instala o InfluxDB nem o CLI `influx`.

.PARAMETER SkipConfig
    Não copia o mosquitto.conf para o diretório de instalação.

.PARAMETER Force
    Sobrescreve o mosquitto.conf já existente sem perguntar (um backup com
    data/hora é criado de qualquer forma).

.EXAMPLE
    # No PowerShell COMO ADMINISTRADOR:
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\scripts\install-windows.ps1

.NOTES
    Compatível com Windows PowerShell 5.1 (sem os operadores &&, ||, ?: e ??).
#>

[CmdletBinding()]
param(
    [switch]$SkipMosquitto,
    [switch]$SkipInflux,
    [switch]$SkipConfig,
    [switch]$Force
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

function Write-Passo  { param([string]$Texto) Write-Host "[..] $Texto" -ForegroundColor Gray }
function Write-Ok     { param([string]$Texto) Write-Host "[OK] $Texto" -ForegroundColor Green }
function Write-Aviso  { param([string]$Texto) Write-Host "[!!] $Texto" -ForegroundColor Yellow }
function Write-Erro   { param([string]$Texto) Write-Host "[XX] $Texto" -ForegroundColor Red }

function Stop-ComMensagem {
    param([string]$Mensagem, [string]$ComoResolver)
    Write-Host ''
    Write-Erro $Mensagem
    if ($ComoResolver) {
        Write-Host ''
        Write-Host 'Como resolver:' -ForegroundColor Yellow
        Write-Host "  $ComoResolver" -ForegroundColor Yellow
    }
    Write-Host ''
    exit 1
}

# ---------------------------------------------------------------------------
# Verificações de ambiente
# ---------------------------------------------------------------------------
function Test-Administrador {
    $identidade = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal  = New-Object Security.Principal.WindowsPrincipal($identidade)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-Comando {
    param([string]$Nome)
    $cmd = Get-Command $Nome -ErrorAction SilentlyContinue
    if ($null -eq $cmd) { return $false }
    return $true
}

function Get-CaminhoComando {
    param([string]$Nome)
    $cmd = Get-Command $Nome -ErrorAction SilentlyContinue
    if ($null -eq $cmd) { return $null }
    return $cmd.Source
}

# ---------------------------------------------------------------------------
# Descoberta de instalações já existentes
# ---------------------------------------------------------------------------
function Find-DiretorioMosquitto {
    # Procura o mosquitto.exe nos caminhos padrão e no PATH.
    $candidatos = @(
        "$env:ProgramFiles\mosquitto",
        "${env:ProgramFiles(x86)}\mosquitto",
        "$env:ProgramW6432\mosquitto"
    )
    foreach ($dir in $candidatos) {
        if ([string]::IsNullOrWhiteSpace($dir)) { continue }
        if (Test-Path (Join-Path $dir 'mosquitto.exe')) { return $dir }
    }
    $viaPath = Get-CaminhoComando 'mosquitto'
    if ($viaPath) { return (Split-Path -Parent $viaPath) }
    return $null
}

function Find-ExecutavelInfluxd {
    $viaPath = Get-CaminhoComando 'influxd'
    if ($viaPath) { return $viaPath }

    $candidatos = @(
        "$env:ProgramFiles\InfluxData\influxdb\influxd.exe",
        "$env:ProgramFiles\InfluxDB\influxd.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\influxd.exe"
    )
    foreach ($exe in $candidatos) {
        if ([string]::IsNullOrWhiteSpace($exe)) { continue }
        if (Test-Path $exe) { return $exe }
    }
    return $null
}

# ---------------------------------------------------------------------------
# Instalação via winget
# ---------------------------------------------------------------------------
function Install-ViaWinget {
    <#
        Tenta instalar um pacote testando uma lista de IDs candidatos (os IDs
        do winget mudam de tempos em tempos). Devolve $true se conseguiu.
    #>
    param(
        [string]  $NomeAmigavel,
        [string[]]$IdsCandidatos,
        [string]  $LinkManual
    )

    foreach ($id in $IdsCandidatos) {
        Write-Passo "Tentando instalar $NomeAmigavel via winget (id: $id)..."

        # winget devolve códigos != 0 quando o id não existe; por isso
        # controlamos o fluxo pelo $LASTEXITCODE em vez de exceções.
        $anterior = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        winget install --id $id --exact --source winget `
                       --accept-package-agreements --accept-source-agreements `
                       --disable-interactivity | Out-Host
        $codigo = $LASTEXITCODE
        $ErrorActionPreference = $anterior

        if ($codigo -eq 0) {
            Write-Ok "$NomeAmigavel instalado."
            return $true
        }

        # 0x8A15002B = "nenhum pacote aplicável" / já instalado em algumas versões
        if ($codigo -eq -1978335189) {
            Write-Ok "$NomeAmigavel já está instalado (winget não tinha nada a fazer)."
            return $true
        }

        Write-Aviso "winget não instalou com o id '$id' (código $codigo). Tentando o próximo..."
    }

    Write-Aviso "Não foi possível instalar $NomeAmigavel pelo winget."
    Write-Host  "     Faça o download manual em: $LinkManual" -ForegroundColor Yellow
    return $false
}

# ---------------------------------------------------------------------------
# Cópia e adaptação do mosquitto.conf
# ---------------------------------------------------------------------------
function Install-ConfiguracaoMosquitto {
    <#
        Copia infra/mosquitto/config/mosquitto.conf para o diretório de
        instalação, trocando os caminhos de container (/mosquitto/data/ e
        /mosquitto/log/mosquitto.log) pelos caminhos Windows equivalentes.
    #>
    param(
        [string]$ConfOrigem,
        [string]$DiretorioMosquitto,
        [switch]$Sobrescrever
    )

    if (-not (Test-Path $ConfOrigem)) {
        Stop-ComMensagem -Mensagem "Não encontrei o arquivo de configuração do repositório: $ConfOrigem" `
                         -ComoResolver 'Rode este script a partir do repositório eyeWatcher completo.'
    }

    $dirConfig = Join-Path $DiretorioMosquitto 'config'
    $dirDados  = Join-Path $DiretorioMosquitto 'data'
    $dirLog    = Join-Path $DiretorioMosquitto 'log'

    foreach ($dir in @($dirConfig, $dirDados, $dirLog)) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
            Write-Ok "Diretório criado: $dir"
        }
    }

    $confDestino = Join-Path $DiretorioMosquitto 'mosquitto.conf'

    # Backup do que já existe (inclusive o conf que vem com o instalador).
    if (Test-Path $confDestino) {
        if (-not $Sobrescrever) {
            Write-Host ''
            Write-Aviso "Já existe um mosquitto.conf em: $confDestino"
            $resposta = Read-Host '     Sobrescrever com a configuração do eyeWatcher? (um backup será criado) [s/N]'
            if ($resposta -notmatch '^[sSyY]$') {
                Write-Aviso 'Configuração NÃO substituída — o broker vai continuar com o conf atual.'
                Write-Host  "     Para aplicar depois: .\scripts\install-windows.ps1 -SkipMosquitto -SkipInflux -Force" -ForegroundColor Yellow
                return $false
            }
        }
        $carimbo = Get-Date -Format 'yyyyMMdd-HHmmss'
        $backup  = "$confDestino.bak-$carimbo"
        Copy-Item -Path $confDestino -Destination $backup -Force
        Write-Ok "Backup do conf anterior: $backup"
    }

    # Lê o conf do repositório e adapta os caminhos para Windows.
    # Leitura em UTF-8 explícito: o Get-Content do PowerShell 5.1 assumiria a
    # codepage ANSI e estragaria os acentos dos comentários.
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $conteudo = [System.IO.File]::ReadAllText($ConfOrigem, $utf8)

    $caminhoDados = $dirDados
    if (-not $caminhoDados.EndsWith('\')) { $caminhoDados = $caminhoDados + '\' }
    $caminhoLog   = Join-Path $dirLog 'mosquitto.log'

    $conteudo = $conteudo -replace 'persistence_location\s+/mosquitto/data/', "persistence_location $caminhoDados"
    $conteudo = $conteudo -replace 'log_dest\s+file\s+/mosquitto/log/mosquitto\.log', "log_dest file $caminhoLog"

    $cabecalho = @"
# ATENÇÃO: arquivo GERADO por scripts/install-windows.ps1 em $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss').
# A fonte da verdade é infra/mosquitto/config/mosquitto.conf no repositório.
# Edite o arquivo do repositório e rode o script de novo — edições feitas aqui
# serão perdidas na próxima execução.

"@

    # UTF-8 SEM BOM: o Mosquitto lê o arquivo byte a byte e um BOM na primeira
    # linha pode ser interpretado como diretiva inválida.
    $semBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($confDestino, ($cabecalho + $conteudo), $semBom)
    Write-Ok "Configuração instalada em: $confDestino"
    Write-Host "     persistência -> $caminhoDados" -ForegroundColor DarkGray
    Write-Host "     log          -> $caminhoLog"   -ForegroundColor DarkGray
    return $true
}

# ===========================================================================
# EXECUÇÃO
# ===========================================================================
$raizRepo  = Split-Path -Parent $PSScriptRoot
$confRepo  = Join-Path $raizRepo 'infra\mosquitto\config\mosquitto.conf'

Write-Titulo 'eyeWatcher — instalação da infraestrutura no Windows'
Write-Host "Repositório: $raizRepo" -ForegroundColor DarkGray

# --- 1. Administrador ------------------------------------------------------
Write-Titulo '1/5 — Verificando privilégios'
if (-not (Test-Administrador)) {
    Stop-ComMensagem -Mensagem 'Este script precisa ser executado COMO ADMINISTRADOR.' `
                     -ComoResolver @'
Feche este PowerShell e abra um novo com "Executar como administrador", depois:
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    cd "C:\Users\Dudu\Documents\eyeWatcher"
    .\scripts\install-windows.ps1
(O winget instala em C:\Program Files e a cópia do mosquitto.conf também
 precisa de permissão de escrita nesse diretório.)
'@
}
Write-Ok 'Rodando como Administrador.'

# --- 2. winget -------------------------------------------------------------
Write-Titulo '2/5 — Verificando o winget'
$temWinget = Test-Comando 'winget'
if ($temWinget) {
    Write-Ok "winget encontrado: $(Get-CaminhoComando 'winget')"
} else {
    Write-Aviso 'winget NÃO encontrado nesta máquina.'
    Write-Host @'
     O winget vem no "Instalador de Aplicativo" da Microsoft Store.
     Instale-o pela Store ou baixe os programas manualmente:
       Mosquitto : https://mosquitto.org/download/
       InfluxDB  : https://www.influxdata.com/downloads/  (OSS 2.x, Windows Binaries)
     Depois rode este script de novo para copiar o mosquitto.conf.
'@ -ForegroundColor Yellow
}

# --- 3. Mosquitto ----------------------------------------------------------
Write-Titulo '3/5 — Mosquitto (broker MQTT)'
$dirMosquitto = Find-DiretorioMosquitto

if ($SkipMosquitto) {
    Write-Aviso 'Instalação do Mosquitto pulada (-SkipMosquitto).'
} elseif ($dirMosquitto) {
    Write-Ok "Mosquitto já instalado em: $dirMosquitto (nada a fazer)."
} elseif (-not $temWinget) {
    Write-Aviso 'Sem winget: instale o Mosquitto manualmente em https://mosquitto.org/download/'
} else {
    $instalou = Install-ViaWinget -NomeAmigavel 'Mosquitto' `
                                  -IdsCandidatos @('EclipseFoundation.Mosquitto') `
                                  -LinkManual 'https://mosquitto.org/download/'
    if ($instalou) {
        # O PATH do processo atual não enxerga a instalação recém-feita;
        # recarregamos a variável a partir do registro.
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                    [Environment]::GetEnvironmentVariable('Path', 'User')
        $dirMosquitto = Find-DiretorioMosquitto
    }
}

if ($dirMosquitto) {
    Write-Ok "Diretório do Mosquitto: $dirMosquitto"
} else {
    Write-Aviso 'Mosquitto não localizado — a cópia da configuração será pulada.'
}

# --- 4. InfluxDB -----------------------------------------------------------
Write-Titulo '4/5 — InfluxDB 2.x (servidor + CLI)'
if ($SkipInflux) {
    Write-Aviso 'Instalação do InfluxDB pulada (-SkipInflux).'
} else {
    $influxd = Find-ExecutavelInfluxd
    if ($influxd) {
        Write-Ok "Servidor InfluxDB já instalado: $influxd"
    } elseif (-not $temWinget) {
        Write-Aviso 'Sem winget: baixe o InfluxDB OSS 2.x em https://www.influxdata.com/downloads/'
    } else {
        Install-ViaWinget -NomeAmigavel 'InfluxDB (servidor)' `
                          -IdsCandidatos @('InfluxData.InfluxDB', 'InfluxData.influxdb') `
                          -LinkManual 'https://www.influxdata.com/downloads/' | Out-Null
    }

    if (Test-Comando 'influx') {
        Write-Ok "CLI influx já instalado: $(Get-CaminhoComando 'influx')"
    } elseif (-not $temWinget) {
        Write-Aviso 'Sem winget: baixe o influx CLI em https://docs.influxdata.com/influxdb/v2/tools/influx-cli/'
    } else {
        Install-ViaWinget -NomeAmigavel 'influx CLI' `
                          -IdsCandidatos @('InfluxData.InfluxCLI', 'InfluxData.influx-cli') `
                          -LinkManual 'https://docs.influxdata.com/influxdb/v2/tools/influx-cli/' | Out-Null
    }

    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

# --- 5. Configuração do Mosquitto -----------------------------------------
Write-Titulo '5/5 — Configuração do broker'
if ($SkipConfig) {
    Write-Aviso 'Cópia da configuração pulada (-SkipConfig).'
} elseif (-not $dirMosquitto) {
    Write-Aviso 'Mosquitto não encontrado: não há para onde copiar o mosquitto.conf.'
} else {
    Install-ConfiguracaoMosquitto -ConfOrigem $confRepo `
                                  -DiretorioMosquitto $dirMosquitto `
                                  -Sobrescrever:$Force | Out-Null
}

# ---------------------------------------------------------------------------
# Próximos passos
# ---------------------------------------------------------------------------
Write-Titulo 'Próximos passos'
Write-Host @'
  1) Se o winget instalou algo agora, FECHE e reabra o PowerShell para que o
     PATH seja atualizado.

  2) Confirme que os comandos respondem:
         mosquitto -h
         influxd version
         influx version

  3) Provisione o InfluxDB (org "eyewatcher", bucket "rack_metrics", 30d) e
     gere o token para o backend:
         .\scripts\setup-influx.ps1

  4) Suba tudo (broker, banco, backend e frontend):
         .\scripts\start-all.ps1

  5) Prove que o MQTT funciona ponta a ponta:
         .\scripts\test-mqtt.ps1

  Observação: o Mosquitto costuma se registrar como SERVIÇO do Windows.
  Se o serviço estiver ativo, ele usa o mosquitto.conf do diretório de
  instalação (o que acabamos de copiar). Para aplicar mudanças:
         Restart-Service mosquitto
'@ -ForegroundColor White

Write-Host ''
Write-Ok 'Instalação concluída.'
Write-Host ''
