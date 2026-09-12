<#
.SYNOPSIS
    Derruba tudo o que o start-all.ps1 subiu (Mosquitto, InfluxDB, backend e
    frontend).

.DESCRIPTION
    Lê scripts\.eyewatcher-run.json (gravado pelo start-all.ps1) e encerra cada
    processo registrado, inclusive os processos FILHOS — o `npm run dev`, por
    exemplo, cria um processo node separado que precisa ir junto.

    Se o arquivo de estado não existir (ou estiver desatualizado), use -ByPort:
    nesse modo o script descobre quem está ocupando as portas do contrato
    (1883, 8086, 8000, 5173) e encerra esses processos.

    O serviço do Windows "mosquitto", quando é ele quem está no ar, é parado
    com Stop-Service (exige PowerShell como Administrador).

.PARAMETER ByPort
    Ignora o arquivo de estado e encerra quem estiver ocupando as portas do
    projeto. Útil depois de reiniciar a máquina ou fechar janelas na mão.

.PARAMETER KeepInflux
    Deixa o InfluxDB rodando (ele demora para subir; às vezes vale manter).

.PARAMETER KeepMosquitto
    Deixa o broker rodando.

.EXAMPLE
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\scripts\stop-all.ps1

.EXAMPLE
    # Quando o arquivo de estado está furado:
    .\scripts\stop-all.ps1 -ByPort

.NOTES
    Compatível com Windows PowerShell 5.1 (sem &&, ||, ?: e ??).
#>

[CmdletBinding()]
param(
    [switch]$ByPort,
    [switch]$KeepInflux,
    [switch]$KeepMosquitto
)

$ErrorActionPreference = 'Stop'

$arquivoEstado = Join-Path $PSScriptRoot '.eyewatcher-run.json'

# Portas do contrato (docs/CONTRACT.md seção 7)
$PORTAS = @(
    [pscustomobject]@{ Porta = 1883; Nome = 'Mosquitto (MQTT/TCP)' },
    [pscustomobject]@{ Porta = 9001; Nome = 'Mosquitto (WebSocket)' },
    [pscustomobject]@{ Porta = 8086; Nome = 'InfluxDB'             },
    [pscustomobject]@{ Porta = 8000; Nome = 'Backend FastAPI'      },
    [pscustomobject]@{ Porta = 5173; Nome = 'Frontend Vite'        }
)

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

# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
function Test-PortaAberta {
    param([string]$ComputerName = '127.0.0.1', [int]$Porta, [int]$TimeoutMs = 600)
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

function Get-ProcessosFilhos {
    <# Devolve os PIDs descendentes (recursivo) de um PID. #>
    param([int]$ProcessId)

    $resultado = @()
    try {
        $filhos = Get-CimInstance -ClassName Win32_Process `
                                  -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    } catch {
        return $resultado
    }

    foreach ($f in $filhos) {
        $resultado += [int]$f.ProcessId
        $resultado += Get-ProcessosFilhos -ProcessId ([int]$f.ProcessId)
    }
    return $resultado
}

function Stop-ArvoreProcesso {
    <# Encerra o processo e toda a sua descendência. Devolve $true se matou algo. #>
    param([int]$ProcessId, [string]$Rotulo)

    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $proc) {
        Write-Aviso "$Rotulo (PID $ProcessId) já não estava rodando."
        return $false
    }

    # Os filhos primeiro, senão o node do Vite fica órfão e segurando a porta.
    $filhos = Get-ProcessosFilhos -ProcessId $ProcessId
    foreach ($pidFilho in $filhos) {
        try {
            Stop-Process -Id $pidFilho -Force -ErrorAction Stop
            Write-Host "     filho encerrado (PID $pidFilho)" -ForegroundColor DarkGray
        } catch {
            # O filho pode ter morrido junto com o pai — não é erro.
        }
    }

    try {
        Stop-Process -Id $ProcessId -Force -ErrorAction Stop
        Write-Ok "$Rotulo encerrado (PID $ProcessId)."
        return $true
    } catch {
        Write-Erro "Não consegui encerrar $Rotulo (PID $ProcessId): $($_.Exception.Message)"
        return $false
    }
}

function Get-PidsPorPorta {
    <# Descobre os PIDs que estão OUVINDO na porta informada. #>
    param([int]$Porta)

    $pids = @()

    # Caminho preferido: cmdlet nativo (Windows 8+/Server 2012+).
    $temCmdlet = Get-Command 'Get-NetTCPConnection' -ErrorAction SilentlyContinue
    if ($temCmdlet) {
        try {
            $conexoes = Get-NetTCPConnection -LocalPort $Porta -State Listen -ErrorAction SilentlyContinue
            foreach ($c in $conexoes) {
                if ($c.OwningProcess -and ($pids -notcontains [int]$c.OwningProcess)) {
                    $pids += [int]$c.OwningProcess
                }
            }
        } catch {
            # cai no netstat abaixo
        }
    }

    if ($pids.Count -eq 0) {
        # Plano B: netstat (funciona em qualquer Windows).
        $anterior = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $linhas = netstat -ano -p TCP | Select-String -Pattern "LISTENING"
        $ErrorActionPreference = $anterior

        foreach ($linha in $linhas) {
            $campos = ($linha.ToString() -split '\s+') | Where-Object { $_ -ne '' }
            if ($campos.Count -lt 5) { continue }
            $endereco = $campos[1]
            if ($endereco -match ":$Porta$") {
                $pidTexto = $campos[$campos.Count - 1]
                $valor = 0
                if ([int]::TryParse($pidTexto, [ref]$valor)) {
                    if ($valor -gt 0 -and ($pids -notcontains $valor)) { $pids += $valor }
                }
            }
        }
    }

    return $pids
}

function Stop-ServicoMosquitto {
    $servico = Get-Service -Name 'mosquitto' -ErrorAction SilentlyContinue
    if ($null -eq $servico) { return $false }
    if ($servico.Status -ne 'Running') {
        Write-Ok 'Serviço mosquitto já estava parado.'
        return $true
    }

    Write-Passo 'Parando o serviço do Windows "mosquitto"...'
    try {
        Stop-Service -Name 'mosquitto' -Force -ErrorAction Stop
        Write-Ok 'Serviço mosquitto parado.'
        return $true
    } catch {
        Write-Erro "Não consegui parar o serviço mosquitto: $($_.Exception.Message)"
        Write-Aviso 'Parar um serviço exige PowerShell como Administrador.'
        return $false
    }
}

# ===========================================================================
# EXECUÇÃO
# ===========================================================================
Write-Titulo 'eyeWatcher — derrubando a stack'

$encerrados = 0

# ---------------------------------------------------------------------------
# Modo 1: pelo arquivo de estado gravado pelo start-all.ps1
# ---------------------------------------------------------------------------
if (-not $ByPort) {
    if (-not (Test-Path $arquivoEstado)) {
        Write-Aviso "Arquivo de estado não encontrado: $arquivoEstado"
        Write-Aviso 'Provavelmente o start-all.ps1 não foi usado nesta sessão.'
        Write-Aviso 'Tentando descobrir pelos números de porta...'
        $ByPort = $true
    } else {
        Write-Passo "Lendo $arquivoEstado"
        $registros = @()
        try {
            $conteudo  = Get-Content -Path $arquivoEstado -Raw
            $registros = @($conteudo | ConvertFrom-Json)
        } catch {
            Write-Erro 'Arquivo de estado corrompido — vou usar o modo por porta.'
            $ByPort = $true
        }

        foreach ($r in $registros) {
            if ($KeepInflux    -and $r.Nome -eq 'influxd')   { Write-Aviso 'InfluxDB mantido (-KeepInflux).';    continue }
            if ($KeepMosquitto -and $r.Nome -eq 'mosquitto') { Write-Aviso 'Mosquitto mantido (-KeepMosquitto).'; continue }

            if ($r.Tipo -eq 'servico') {
                $parou = Stop-ServicoMosquitto
                if ($parou) { $encerrados++ }
                continue
            }

            $matou = Stop-ArvoreProcesso -ProcessId ([int]$r.ProcessId) -Rotulo $r.Nome
            if ($matou) { $encerrados++ }
        }

        if ($registros.Count -gt 0) {
            Remove-Item -Path $arquivoEstado -Force -ErrorAction SilentlyContinue
            Write-Ok 'Arquivo de estado removido.'
        }
    }
}

# ---------------------------------------------------------------------------
# Modo 2: por porta
# ---------------------------------------------------------------------------
if ($ByPort) {
    Write-Titulo 'Procurando por porta'

    if ($KeepMosquitto -eq $false) {
        Stop-ServicoMosquitto | Out-Null
    }

    foreach ($p in $PORTAS) {
        if ($KeepInflux    -and $p.Porta -eq 8086) { continue }
        if ($KeepMosquitto -and ($p.Porta -eq 1883 -or $p.Porta -eq 9001)) { continue }

        $pids = Get-PidsPorPorta -Porta $p.Porta
        if ($pids.Count -eq 0) {
            Write-Host "  $($p.Nome.PadRight(24)) porta $($p.Porta)  [já parado]" -ForegroundColor DarkGray
            continue
        }

        foreach ($processId in $pids) {
            $matou = Stop-ArvoreProcesso -ProcessId $processId -Rotulo "$($p.Nome) [porta $($p.Porta)]"
            if ($matou) { $encerrados++ }
        }
    }

    if (Test-Path $arquivoEstado) {
        Remove-Item -Path $arquivoEstado -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------------------
# Conferência final
# ---------------------------------------------------------------------------
Write-Titulo 'Conferência das portas'
Start-Sleep -Milliseconds 800

$aindaNoAr = @()
foreach ($p in $PORTAS) {
    $rotulo = $p.Nome.PadRight(24)
    if (Test-PortaAberta -Porta $p.Porta) {
        Write-Host "  $rotulo porta $($p.Porta)  [AINDA NO AR]" -ForegroundColor Yellow
        $aindaNoAr += $p
    } else {
        Write-Host "  $rotulo porta $($p.Porta)  [parado]" -ForegroundColor Green
    }
}

Write-Host ''
Write-Ok "Processos encerrados: $encerrados"

if ($aindaNoAr.Count -gt 0) {
    Write-Host ''
    Write-Aviso 'Ainda há portas ocupadas. Possíveis motivos:'
    Write-Aviso '  - o componente foi iniciado fora do start-all.ps1;'
    Write-Aviso '  - o Mosquitto está rodando como serviço e falta permissão de Administrador;'
    Write-Aviso '  - o processo é de outro usuário.'
    Write-Host ''
    Write-Host '  Tente:  .\scripts\stop-all.ps1 -ByPort     (num PowerShell como Administrador)' -ForegroundColor Yellow
}

Write-Host ''
