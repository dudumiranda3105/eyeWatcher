@echo off
rem ============================================================================
rem  eyeWatcher - sobe tudo com dois cliques (Windows)
rem
rem  1. confere o que o computador precisa ter e avisa o que falta instalar
rem  2. abre o Docker Desktop se ele estiver fechado
rem  3. roda "docker compose up -d --build" (compila e inicia os 16 servicos)
rem  4. espera a aplicacao responder, mostra os logins e abre o navegador
rem
rem  Nao precisa configurar chave nenhuma: as senhas sao geradas sozinhas na
rem  primeira subida e ficam em secrets\CREDENCIAIS.txt.
rem
rem  EYEWATCHER_SEM_NAVEGADOR=1 evita abrir o navegador (usado nos testes).
rem ============================================================================
setlocal
cd /d "%~dp0"
title eyeWatcher - iniciando
set "URL=http://localhost:8080"

echo.
echo ===== eyeWatcher: iniciando =====
echo.
echo Conferindo o que o computador precisa ter...
echo.

rem ---- 1. Docker instalado? ---------------------------------------------------
where docker >nul 2>nul
if errorlevel 1 goto sem_docker
echo [ok] Docker instalado

rem ---- 2. Docker aberto? ------------------------------------------------------
docker info >nul 2>nul
if not errorlevel 1 goto docker_aberto
echo [!!] O Docker Desktop esta fechado. Abrindo para voce...
set "DOCKER_EXE=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
if not exist "%DOCKER_EXE%" goto docker_manual
start "" "%DOCKER_EXE%"
set /a TENTATIVAS=0

:esperar_docker
docker info >nul 2>nul
if not errorlevel 1 goto docker_aberto
set /a TENTATIVAS+=1
if %TENTATIVAS% GEQ 48 goto docker_nao_subiu
echo      aguardando o Docker ficar pronto... %TENTATIVAS%/48
ping -n 6 127.0.0.1 >nul
goto esperar_docker

:docker_aberto
echo [ok] Docker aberto e funcionando

rem ---- 3. Docker Compose ------------------------------------------------------
docker compose version >nul 2>nul
if errorlevel 1 goto sem_compose
echo [ok] Docker Compose disponivel

rem ---- 4. Memoria que o Docker enxerga ----------------------------------------
set "MEM="
for /f %%m in ('docker info --format "{{.MemTotal}}" 2^>nul') do set "MEM=%%m"
set /a MEM_MB=0
if defined MEM if not "%MEM:~6%"=="" set /a MEM_MB=%MEM:~0,-6%
if %MEM_MB% EQU 0 goto mem_fim
if %MEM_MB% GEQ 7500 goto mem_ok
echo [!!] AVISO: o Docker so enxerga cerca de %MEM_MB% MB de memoria.
echo      O projeto precisa de uns 8 GB. Com menos, o Assistente de IA pode
echo      travar ou falhar. No Windows com WSL2, crie o arquivo .wslconfig na
echo      sua pasta de usuario com memory=8GB e reinicie o Docker Desktop.
goto mem_fim
:mem_ok
echo [ok] Memoria para o Docker: cerca de %MEM_MB% MB
:mem_fim

rem ---- 5. Espaco em disco -----------------------------------------------------
set "LIVRE_GB="
for /f %%d in ('powershell -NoProfile -Command "[math]::Floor((Get-PSDrive ($env:SystemDrive.Substring(0,1))).Free / 1GB)" 2^>nul') do set "LIVRE_GB=%%d"
if not defined LIVRE_GB goto disco_fim
if %LIVRE_GB% GEQ 15 goto disco_ok
echo [!!] AVISO: so ha %LIVRE_GB% GB livres no disco do sistema.
echo      A primeira subida baixa e guarda cerca de 10 GB entre imagens e o
echo      modelo de IA. Libere espaco se o download falhar.
goto disco_fim
:disco_ok
echo [ok] Espaco em disco: %LIVRE_GB% GB livres
:disco_fim

rem ---- 6. curl (usado para esperar a aplicacao) -------------------------------
set "SEM_CURL="
where curl.exe >nul 2>nul
if errorlevel 1 set "SEM_CURL=1"
if defined SEM_CURL echo [!!] AVISO: curl.exe nao encontrado. Nao vou conseguir esperar a aplicacao responder.

rem ---- 7. Portas livres -------------------------------------------------------
rem  So confere se o eyeWatcher ainda nao esta rodando; senao as portas ocupadas
rem  seriam as dele mesmo.
set "RODANDO="
for /f %%i in ('docker compose ps -q 2^>nul') do set "RODANDO=1"
if defined RODANDO goto portas_fim
set "OCUPADAS="
call :checar_porta 8080
call :checar_porta 15672
call :checar_porta 8086
call :checar_porta 8081
if defined OCUPADAS goto portas_ocupadas
echo [ok] Portas 8080, 15672, 8086 e 8081 livres
:portas_fim

echo.
echo Tudo certo. Subindo os servicos...
echo Na primeira vez demora: compila as imagens e baixa o modelo de IA, cerca de 2 GB.
echo E precisa de internet nessa primeira vez.
echo.
docker compose up -d --build
if errorlevel 1 goto falhou

echo.
if defined SEM_CURL goto app_ok
echo Aguardando a aplicacao responder em %URL% ...
set /a TENTATIVAS=0

:esperar_app
curl.exe -s -f -o nul %URL%/
if not errorlevel 1 goto app_ok
set /a TENTATIVAS+=1
if %TENTATIVAS% GEQ 120 goto app_demorou
ping -n 4 127.0.0.1 >nul
goto esperar_app

:app_ok
echo.
echo ===== Pronto =====
echo.
if exist "secrets\CREDENCIAIS.txt" type "secrets\CREDENCIAIS.txt"
echo.
echo Aplicacao: %URL%
if not defined EYEWATCHER_SEM_NAVEGADOR start "" %URL%
echo.
echo Obs.: o Assistente (IA) pode levar alguns minutos ate mostrar "Modelo pronto".
echo Para desligar tudo, de dois cliques em parar.bat
echo.
pause
exit /b 0

rem ============================================================================
rem  Avisos de erro
rem ============================================================================

:checar_porta
netstat -ano | findstr /R /C:":%1 .*LISTENING" >nul
if not errorlevel 1 set "OCUPADAS=%OCUPADAS% %1"
exit /b 0

:sem_docker
echo.
echo ============================================================
echo  FALTA INSTALAR: Docker Desktop
echo ============================================================
echo.
echo  O eyeWatcher roda dentro do Docker, e ele nao esta instalado
echo  neste computador. Faca isto uma vez so:
echo.
echo   1. Baixe e instale o Docker Desktop:
echo      https://www.docker.com/products/docker-desktop/
echo      Vou abrir essa pagina para voce.
echo   2. Se o instalador pedir, reinicie o computador.
echo   3. Abra o Docker Desktop, aceite os termos e espere o icone da
echo      baleia parar de animar.
echo   4. De dois cliques em iniciar.bat de novo.
echo.
echo  Requisitos: Windows 10 ou 11 de 64 bits, virtualizacao ligada na
echo  BIOS, 8 GB de RAM ou mais e uns 15 GB livres no disco.
echo.
if not defined EYEWATCHER_SEM_NAVEGADOR start "" https://www.docker.com/products/docker-desktop/
pause
exit /b 1

:docker_manual
echo.
echo [XX] O Docker esta instalado mas nao esta rodando, e nao achei o
echo      Docker Desktop no lugar de sempre. Abra o Docker pelo Menu
echo      Iniciar, espere ele ficar pronto e rode este arquivo de novo.
echo.
pause
exit /b 1

:sem_compose
echo.
echo ============================================================
echo  FALTA ATUALIZAR: Docker Compose
echo ============================================================
echo.
echo  O Docker esta instalado, mas sem o comando "docker compose"
echo  ou numa versao antiga. Atualize o Docker Desktop para a versao
echo  mais recente e rode este arquivo de novo:
echo  https://www.docker.com/products/docker-desktop/
echo.
pause
exit /b 1

:docker_nao_subiu
echo.
echo ============================================================
echo  O Docker Desktop nao ficou pronto a tempo
echo ============================================================
echo.
set "VIRT="
for /f %%v in ('powershell -NoProfile -Command "[bool]((Get-CimInstance Win32_ComputerSystem).HypervisorPresent -or (Get-CimInstance Win32_Processor).VirtualizationFirmwareEnabled)" 2^>nul') do set "VIRT=%%v"
if /i "%VIRT%"=="False" echo  [!!] A virtualizacao parece estar DESLIGADA na BIOS. Ligue a opcao
if /i "%VIRT%"=="False" echo       SVM Mode ^(AMD^) ou Intel VT-x, ou Virtualization Technology.
if /i "%VIRT%"=="False" echo.
echo  Causas mais comuns:
echo   1. O Docker Desktop abriu uma janela pedindo para aceitar os termos
echo      ou fazer login. Aceite na janela dele.
echo   2. Virtualizacao desligada na BIOS.
echo   3. WSL2 nao instalado: abra o PowerShell como administrador, rode
echo      wsl --install e reinicie o computador.
echo   4. O computador precisa ser reiniciado depois de instalar o Docker.
echo.
echo  Resolva e rode este arquivo de novo.
echo.
pause
exit /b 1

:portas_ocupadas
echo.
echo ============================================================
echo  PORTA JA EM USO por outro programa:%OCUPADAS%
echo ============================================================
echo.
echo  O eyeWatcher usa estas portas: 8080 aplicacao, 15672 RabbitMQ,
echo  8086 InfluxDB e 8081 Adminer. Feche o programa que esta usando
echo  as portas acima e rode este arquivo de novo.
echo.
echo  Para descobrir quem usa uma porta, por exemplo a 8080:
echo    netstat -ano ^| findstr :8080
echo  O ultimo numero da linha e o PID; veja o nome no Gerenciador de Tarefas.
echo.
pause
exit /b 1

:falhou
echo.
echo ============================================================
echo  Algo deu errado ao subir os servicos
echo ============================================================
echo.
echo  Leia as mensagens acima. Causas comuns:
echo   - Sem internet: na primeira vez o Docker baixa imagens e o modelo de IA.
echo   - Pouco espaco em disco.
echo   - Docker Desktop travado: feche, abra de novo e rode este arquivo.
echo.
echo  Para ver os detalhes: docker compose logs
echo.
pause
exit /b 1

:app_demorou
echo.
echo A aplicacao ainda nao respondeu. Os containers continuam subindo em segundo plano.
echo Confira com: docker compose ps
echo e abra %URL% quando todos estiverem healthy.
echo.
pause
exit /b 1
