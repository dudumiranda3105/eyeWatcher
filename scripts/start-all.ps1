<#
.SYNOPSIS
    Sobe toda a stack do eyeWatcher: Mosquitto, InfluxDB, backend (uvicorn) e
    frontend (Vite), cada um na sua própria janela.

.DESCRIPTION
    Cada componente é iniciado em sequência e o script SÓ avança depois que a
    porta correspondente estiver aceitando conexões (docs/CONTRACT.md seção 7):

        Mosquitto TCP ... 1883
        InfluxDB ........ 8086
        Backend FastAPI . 8000
        Frontend Vite ... 5173

    Se alguma dependência não estiver instalada (Mosquitto, influxd, venv do
    backend, node_modules do frontend), o script avisa CLARAMENTE e diz o que
    fazer, em vez de falhar em silêncio.

    Os PIDs iniciados são gravados em scripts\.eyewatcher-run.json para que o
    stop-all.ps1 saiba exatamente o que derrubar.

.PARAMETER SkipMosquitto
.PARAMETER SkipInflux
.PARAMETER SkipBackend
.PARAMETER SkipFrontend
    Pula o componente correspondente (útil quando ele já está rodando).

.PARAMETER TimeoutSeconds
    Tempo máximo de espera por cada porta. Padrão: 60.

.PARAMETER BackendApp
    Caminho de importação da aplicação FastAPI para o uvicorn.
    Padrão: app.main:app

.EXAMPLE
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\scripts\start-all.ps1

.EXAMPLE
    # Só a infraestrutura (broker + banco), sem backend/frontend:
    .\scripts\start-all.ps1 -SkipBackend -SkipFrontend

.NOTES
    Compatível com Windows PowerShell 5.1 (sem &&, ||, ?: e ??).
#>

[CmdletBinding()]
param(
    [switch]$SkipMosquitto,
    [switch]$SkipInflux,
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [int]   $TimeoutSeconds = 60,
    [string]$BackendApp     = 'app.main:app'
)

$ErrorActionPreference = 'Stop'

# Portas do contrato (docs/CONTRACT.md seção 7)
$PORTA_MQTT     = 1883
$PORTA_MQTT_WS  = 9001
$PORTA_INFLUX   = 8086
$PORTA_BACKEND  = 8000
$PORTA_FRONTEND = 5173

$raizRepo    = Split-Path -Parent $PSScriptRoot
$dirBackend  = Join-Path $raizRepo 'backend'
$dirFrontend = Join-Path $raizRepo 'frontend'
$arquivoEstado = Join-Path $PSScriptRoot '.eyewatcher-run.json'

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
# Portas
# ---------------------------------------------------------------------------
function Test-PortaAberta {
    param([string]$ComputerName = '127.0.0.1', [int]$Porta, [int]$TimeoutMs = 800)
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

function Wait-Porta {
    <# Espera a porta abrir. Devolve $true se abriu dentro do tempo. #>
    param([int]$Porta, [string]$Rotulo, [int]$Segundos = 60)

    Write-Passo "Aguardando $Rotulo na porta $Porta (até ${Segundos}s)..."
    $limite = (Get-Date).AddSeconds($Segundos)

    while ((Get-Date) -lt $limite) {
        if (Test-PortaAberta -Porta $Porta) {
            Write-Ok "$Rotulo respondendo na porta $Porta."
            return $true
        }
        Start-Sleep -Milliseconds 700
    }

    Write-Erro "$Rotulo NÃO respondeu na porta $Porta dentro de ${Segundos}s."
    Write-Aviso 'Confira a janela que foi aberta para esse componente: o erro real está lá.'
    return $false
}

# ---------------------------------------------------------------------------
# Estado (PIDs) para o stop-all.ps1
# ---------------------------------------------------------------------------
$script:Processos = @()

function Register-Processo {
    param([string]$Nome, [int]$ProcessId, [int]$Porta, [string]$Tipo = 'processo')
    $script:Processos += [pscustomobject]@{
        Nome      = $Nome
        ProcessId = $ProcessId
        Porta     = $Porta
        Tipo      = $Tipo
        IniciadoEm = (Get-Date).ToString('s')
    }
}

function Save-Estado {
    if ($script:Processos.Count -eq 0) {
        Write-Aviso 'Nenhum processo novo foi iniciado — arquivo de estado não atualizado.'
        return
    }
    $json = $script:Processos | ConvertTo-Json -Depth 4
    # UTF-8 sem BOM, para o ConvertFrom-Json do stop-all.ps1 nunca tropeçar nele.
    $semBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($arquivoEstado, $json, $semBom)
    Write-Ok "Estado gravado em: $arquivoEstado"
}

# ---------------------------------------------------------------------------
# Inicialização genérica de um componente
# ---------------------------------------------------------------------------
function Start-Componente {
    <#
        Abre uma janela nova rodando $Executavel com $Argumentos e devolve o
        objeto Process (ou $null em caso de falha).
    #>
    param(
        [string]  $Nome,
        [string]  $Executavel,
        [string[]]$Argumentos = @(),
        [string]  $DiretorioTrabalho
    )

    Write-Passo "Iniciando $Nome..."
    try {
        $parametros = @{
            FilePath    = $Executavel
            PassThru    = $true
            WindowStyle = 'Normal'
        }
        if ($Argumentos.Count -gt 0)   { $parametros['ArgumentList']     = $Argumentos }
        if ($DiretorioTrabalho)        { $parametros['WorkingDirectory'] = $DiretorioTrabalho }

        $proc = Start-Process @parametros
        Write-Ok "$Nome iniciado (PID $($proc.Id))."
        return $proc
    } catch {
        Write-Erro "Falha ao iniciar $Nome : $($_.Exception.Message)"
        return $null
    }
}

function Find-DiretorioMosquitto {
    $candidatos = @(
        "$env:ProgramFiles\mosquitto",
        "${env:ProgramFiles(x86)}\mosquitto",
        "$env:ProgramW6432\mosquitto"
    )
    foreach ($dir in $candidatos) {
        if ([string]::IsNullOrWhiteSpace($dir)) { continue }
        if (Test-Path (Join-Path $dir 'mosquitto.exe')) { return $dir }
    }
    $cmd = Get-Command 'mosquitto' -ErrorAction SilentlyContinue
    if ($cmd) { return (Split-Path -Parent $cmd.Source) }
    return $null
}

# ===========================================================================
# EXECUÇÃO
# ===========================================================================
Write-Titulo 'eyeWatcher — subindo a stack completa'
Write-Host "  Repositório: $raizRepo" -ForegroundColor DarkGray

$falhas = @()

# ---------------------------------------------------------------------------
# 1) Mosquitto
# ---------------------------------------------------------------------------
Write-Titulo '1/4 — Mosquitto (broker MQTT, portas 1883 e 9001)'

if ($SkipMosquitto) {
    Write-Aviso 'Pulado (-SkipMosquitto).'
} elseif (Test-PortaAberta -Porta $PORTA_MQTT) {
    Write-Ok "Já existe algo escutando na porta $PORTA_MQTT — reaproveitando."
} else {
    $servico = Get-Service -Name 'mosquitto' -ErrorAction SilentlyContinue

    if ($servico) {
        # Instalação padrão do Windows registra o Mosquitto como serviço.
        Write-Passo "Serviço 'mosquitto' encontrado (status: $($servico.Status)). Iniciando..."
        try {
            Start-Service -Name 'mosquitto'
            Write-Ok 'Serviço mosquitto iniciado.'
            Register-Processo -Nome 'mosquitto' -ProcessId 0 -Porta $PORTA_MQTT -Tipo 'servico'
        } catch {
            Write-Erro "Não consegui iniciar o serviço mosquitto: $($_.Exception.Message)"
            Write-Aviso 'Iniciar um serviço exige PowerShell como Administrador.'
            $falhas += 'mosquitto'
        }
    } else {
        $dirMosq = Find-DiretorioMosquitto
        if (-not $dirMosq) {
            Write-Erro 'Mosquitto não está instalado (nem como serviço, nem no PATH).'
            Write-Aviso 'Instale com:  .\scripts\install-windows.ps1   (como Administrador)'
            $falhas += 'mosquitto'
        } else {
            $exe  = Join-Path $dirMosq 'mosquitto.exe'
            $conf = Join-Path $dirMosq 'mosquitto.conf'
            if (-not (Test-Path $conf)) {
                Write-Aviso "Não achei o mosquitto.conf em $dirMosq — o broker vai subir com os padrões."
                Write-Aviso 'Para instalar a configuração do projeto (inclui a porta 9001 WebSocket):'
                Write-Aviso '    .\scripts\install-windows.ps1 -SkipMosquitto -SkipInflux'
                $proc = Start-Componente -Nome 'Mosquitto' -Executavel $exe -Argumentos @('-v') -DiretorioTrabalho $dirMosq
            } else {
                $proc = Start-Componente -Nome 'Mosquitto' -Executavel $exe -Argumentos @('-c', $conf, '-v') -DiretorioTrabalho $dirMosq
            }
            if ($proc) { Register-Processo -Nome 'mosquitto' -ProcessId $proc.Id -Porta $PORTA_MQTT }
            else       { $falhas += 'mosquitto' }
        }
    }

    if ($falhas -notcontains 'mosquitto') {
        $ok = Wait-Porta -Porta $PORTA_MQTT -Rotulo 'Mosquitto (MQTT/TCP)' -Segundos $TimeoutSeconds
        if (-not $ok) { $falhas += 'mosquitto' }
    }
}

# Checagem informativa do listener WebSocket (não bloqueia a subida).
if ($falhas -notcontains 'mosquitto') {
    if (Test-PortaAberta -Porta $PORTA_MQTT_WS) {
        Write-Ok "Listener WebSocket ativo na porta $PORTA_MQTT_WS."
    } else {
        Write-Aviso "Porta $PORTA_MQTT_WS (WebSocket) não está aberta."
        Write-Aviso 'O backend e o firmware usam a 1883, então nada quebra — mas o'
        Write-Aviso 'mosquitto.conf do projeto não parece estar aplicado. Rode:'
        Write-Aviso '    .\scripts\install-windows.ps1 -SkipMosquitto -SkipInflux -Force'
    }
}

# ---------------------------------------------------------------------------
# 2) InfluxDB
# ---------------------------------------------------------------------------
Write-Titulo '2/4 — InfluxDB 2.x (porta 8086)'

if ($SkipInflux) {
    Write-Aviso 'Pulado (-SkipInflux).'
} elseif (Test-PortaAberta -Porta $PORTA_INFLUX) {
    Write-Ok "Já existe algo escutando na porta $PORTA_INFLUX — reaproveitando."
} else {
    $influxd = Get-Command 'influxd' -ErrorAction SilentlyContinue
    if ($null -eq $influxd) {
        Write-Erro 'influxd não encontrado no PATH.'
        Write-Aviso 'Instale com:  .\scripts\install-windows.ps1   (como Administrador)'
        Write-Aviso 'Ou baixe em:  https://www.influxdata.com/downloads/'
        $falhas += 'influxdb'
    } else {
        $proc = Start-Componente -Nome 'InfluxDB' -Executavel $influxd.Source
        if ($proc) {
            Register-Processo -Nome 'influxd' -ProcessId $proc.Id -Porta $PORTA_INFLUX
            $ok = Wait-Porta -Porta $PORTA_INFLUX -Rotulo 'InfluxDB' -Segundos $TimeoutSeconds
            if (-not $ok) { $falhas += 'influxdb' }
        } else {
            $falhas += 'influxdb'
        }
    }
}

# ---------------------------------------------------------------------------
# 3) Backend (FastAPI/uvicorn na venv de backend/)
# ---------------------------------------------------------------------------
Write-Titulo '3/4 — Backend FastAPI (porta 8000)'

if ($SkipBackend) {
    Write-Aviso 'Pulado (-SkipBackend).'
} elseif (Test-PortaAberta -Porta $PORTA_BACKEND) {
    Write-Ok "Já existe algo escutando na porta $PORTA_BACKEND — reaproveitando."
} else {
    $pythonVenv = Join-Path $dirBackend '.venv\Scripts\python.exe'
    $envBackend = Join-Path $dirBackend '.env'

    if (-not (Test-Path $pythonVenv)) {
        Write-Erro "Não encontrei a venv do backend: $pythonVenv"
        Write-Aviso 'Crie e instale as dependências:'
        Write-Aviso '    cd backend'
        Write-Aviso '    python -m venv .venv'
        Write-Aviso '    .\.venv\Scripts\Activate.ps1'
        Write-Aviso '    pip install -r requirements.txt'
        $falhas += 'backend'
    } else {
        if (-not (Test-Path $envBackend)) {
            Write-Aviso "backend\.env não existe — o backend não vai achar o INFLUX_TOKEN."
            Write-Aviso 'Gere com:  .\scripts\setup-influx.ps1'
        }

        $proc = Start-Componente -Nome 'Backend (uvicorn)' `
                                 -Executavel $pythonVenv `
                                 -Argumentos @('-m', 'uvicorn', $BackendApp,
                                               '--host', '0.0.0.0',
                                               '--port', "$PORTA_BACKEND",
                                               '--reload') `
                                 -DiretorioTrabalho $dirBackend
        if ($proc) {
            Register-Processo -Nome 'backend' -ProcessId $proc.Id -Porta $PORTA_BACKEND
            $ok = Wait-Porta -Porta $PORTA_BACKEND -Rotulo 'Backend FastAPI' -Segundos $TimeoutSeconds
            if (-not $ok) {
                Write-Aviso "Confira se o módulo '$BackendApp' existe em backend\."
                Write-Aviso 'Se o caminho for outro, use:  .\scripts\start-all.ps1 -BackendApp <modulo>:<app>'
                $falhas += 'backend'
            }
        } else {
            $falhas += 'backend'
        }
    }
}

# ---------------------------------------------------------------------------
# 4) Frontend (Vite)
# ---------------------------------------------------------------------------
Write-Titulo '4/4 — Frontend Vite (porta 5173)'

if ($SkipFrontend) {
    Write-Aviso 'Pulado (-SkipFrontend).'
} elseif (Test-PortaAberta -Porta $PORTA_FRONTEND) {
    Write-Ok "Já existe algo escutando na porta $PORTA_FRONTEND — reaproveitando."
} else {
    $packageJson = Join-Path $dirFrontend 'package.json'
    $nodeModules = Join-Path $dirFrontend 'node_modules'
    $npm = Get-Command 'npm.cmd' -ErrorAction SilentlyContinue
    if ($null -eq $npm) { $npm = Get-Command 'npm' -ErrorAction SilentlyContinue }

    if ($null -eq $npm) {
        Write-Erro 'npm não encontrado no PATH — o Node.js não está instalado.'
        Write-Aviso 'Instale o Node.js LTS em https://nodejs.org/  (ou: winget install OpenJS.NodeJS.LTS)'
        $falhas += 'frontend'
    } elseif (-not (Test-Path $packageJson)) {
        Write-Erro "Não encontrei $packageJson — o frontend ainda não foi criado."
        Write-Aviso 'Pule esta etapa por enquanto com:  .\scripts\start-all.ps1 -SkipFrontend'
        $falhas += 'frontend'
    } else {
        if (-not (Test-Path $nodeModules)) {
            Write-Aviso 'node_modules não existe — as dependências do frontend não foram instaladas.'
            Write-Aviso 'Rode antes:  cd frontend ; npm install'
            $falhas += 'frontend'
        } else {
            $proc = Start-Componente -Nome 'Frontend (vite)' `
                                     -Executavel $npm.Source `
                                     -Argumentos @('run', 'dev') `
                                     -DiretorioTrabalho $dirFrontend
            if ($proc) {
                Register-Processo -Nome 'frontend' -ProcessId $proc.Id -Porta $PORTA_FRONTEND
                $ok = Wait-Porta -Porta $PORTA_FRONTEND -Rotulo 'Frontend Vite' -Segundos $TimeoutSeconds
                if (-not $ok) { $falhas += 'frontend' }
            } else {
                $falhas += 'frontend'
            }
        }
    }
}

# ---------------------------------------------------------------------------
# Resumo
# ---------------------------------------------------------------------------
Save-Estado

Write-Titulo 'Resumo'

$componentes = @(
    @{ Nome = 'Mosquitto (MQTT/TCP)'; Porta = $PORTA_MQTT     },
    @{ Nome = 'Mosquitto (WebSocket)'; Porta = $PORTA_MQTT_WS },
    @{ Nome = 'InfluxDB'            ; Porta = $PORTA_INFLUX   },
    @{ Nome = 'Backend FastAPI'     ; Porta = $PORTA_BACKEND  },
    @{ Nome = 'Frontend Vite'       ; Porta = $PORTA_FRONTEND }
)

foreach ($c in $componentes) {
    $rotulo = $c.Nome.PadRight(24)
    if (Test-PortaAberta -Porta $c.Porta) {
        Write-Host "  $rotulo porta $($c.Porta)  [NO AR]" -ForegroundColor Green
    } else {
        Write-Host "  $rotulo porta $($c.Porta)  [FORA]"  -ForegroundColor Red
    }
}

Write-Host ''
Write-Host '  Endereços úteis:' -ForegroundColor White
Write-Host "    Dashboard  : http://localhost:$PORTA_FRONTEND" -ForegroundColor White
Write-Host "    API / docs : http://localhost:$PORTA_BACKEND/docs" -ForegroundColor White
Write-Host "    Health     : http://localhost:$PORTA_BACKEND/api/health" -ForegroundColor White
Write-Host "    InfluxDB UI: http://localhost:$PORTA_INFLUX" -ForegroundColor White
Write-Host ''
Write-Host '  Para derrubar tudo:  .\scripts\stop-all.ps1' -ForegroundColor White
Write-Host '  Para testar o MQTT:  .\scripts\test-mqtt.ps1' -ForegroundColor White
Write-Host ''

if ($falhas.Count -gt 0) {
    Write-Erro ("Componentes com problema: " + ($falhas -join ', '))
    Write-Aviso 'Leia as mensagens acima — cada falha diz o que instalar ou configurar.'
    Write-Host ''
    exit 1
}

Write-Ok 'Stack no ar.'
Write-Host ''
